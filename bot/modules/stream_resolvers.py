from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import html
import logging
import os
import re
from typing import Dict, Iterable, List, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
import requests

from bot import errors


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/111.0.0.0 Safari/537.36"
)
MAX_HTML_BYTES = 512 * 1024
MEDIA_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m3u",
    ".m3u8",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".pls",
    ".wav",
    ".webm",
}


@dataclass(frozen=True)
class StreamResolution:
    url: str
    name: str = ""
    format: str = ""
    http_headers: Optional[Dict[str, str]] = None


class StreamResolver(ABC):
    @abstractmethod
    def supports(self, url: str) -> bool:
        ...

    @abstractmethod
    def resolve(self, url: str) -> StreamResolution:
        ...


class HtmlMediaResolver(StreamResolver):
    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self._session = session or requests.Session()

    def resolve(self, url: str) -> StreamResolution:
        response = self._fetch_page(url)
        try:
            media_url = self._resolve_response(response)
            return StreamResolution(
                url=media_url,
                name=self._guess_name(media_url, url),
                format=self._guess_format(media_url),
                http_headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": response.url,
                },
            )
        finally:
            response.close()

    def _resolve_response(self, response: requests.Response) -> str:
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type.startswith(("audio/", "video/")):
            return response.url
        document = self._read_document(response)
        media_url = self._extract_media_url(document, response.url)
        if not media_url:
            raise errors.ServiceError("No playable media URL found in the page")
        return media_url

    def _fetch_page(self, url: str) -> requests.Response:
        try:
            response = self._session.get(
                url,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=(5, 15),
                allow_redirects=True,
                stream=True,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise errors.ServiceError(f"Failed to load stream page: {exc}") from exc

    @staticmethod
    def _read_document(response: requests.Response) -> str:
        chunks: List[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            remaining = MAX_HTML_BYTES - total
            if remaining <= 0:
                break
            chunks.append(chunk[:remaining])
            total += min(len(chunk), remaining)
            if total >= MAX_HTML_BYTES:
                break
        encoding = response.encoding or "utf-8"
        return b"".join(chunks).decode(encoding, errors="replace")

    @classmethod
    def _extract_media_url(cls, document: str, base_url: str) -> Optional[str]:
        soup = BeautifulSoup(document, "html.parser")
        candidates: List[str] = []

        for selector, attribute in (
            ("audio[src]", "src"),
            ("audio source[src]", "src"),
            ("video[src]", "src"),
            ("video source[src]", "src"),
            ("meta[property='og:audio']", "content"),
            ("meta[property='og:audio:url']", "content"),
            ("meta[name='twitter:player:stream']", "content"),
        ):
            candidates.extend(
                element.get(attribute, "") for element in soup.select(selector)
            )

        candidates.extend(cls._extract_script_candidates(document))
        candidates.extend(
            anchor.get("href", "")
            for anchor in soup.select("a[href]")
            if cls._looks_like_media_url(anchor.get("href", ""))
        )

        for candidate in cls._deduplicate(candidates):
            normalized = cls._normalize_candidate(candidate, base_url)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _extract_script_candidates(document: str) -> List[str]:
        patterns = (
            r"(?:mp3|audio(?:_?url)?|stream(?:_?url)?)\s*[:=]\s*[\"']([^\"']+)[\"']",
            r"(?:src|file)\s*[:=]\s*[\"']([^\"']+\.(?:mp3|m4a|aac|ogg|opus|wav|flac|m3u8?|pls)(?:\?[^\"']*)?)[\"']",
            r"[\"']([^\"']+\.(?:mp3|m4a|aac|ogg|opus|wav|flac|m3u8?|pls)(?:\?[^\"']*)?)[\"']",
        )
        candidates: List[str] = []
        for pattern in patterns:
            candidates.extend(re.findall(pattern, document, flags=re.IGNORECASE))
        return candidates

    @staticmethod
    def _deduplicate(values: Iterable[str]) -> Iterable[str]:
        seen = set()
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            yield value

    @classmethod
    def _normalize_candidate(cls, value: str, base_url: str) -> Optional[str]:
        value = html.unescape(value).replace(r"\/", "/").strip()
        if not value or value.startswith(("blob:", "data:", "javascript:")):
            return None
        resolved = urljoin(base_url, value)
        parsed = urlparse(resolved)
        if parsed.scheme not in ("http", "https"):
            return None
        if resolved == base_url:
            return None
        return resolved

    @staticmethod
    def _looks_like_media_url(value: str) -> bool:
        path = urlparse(value).path.lower()
        return any(path.endswith(extension) for extension in MEDIA_EXTENSIONS)

    @staticmethod
    def _guess_format(url: str) -> str:
        extension = os.path.splitext(urlparse(url).path)[1].lower().lstrip(".")
        return extension if extension else ""

    @staticmethod
    def _guess_name(media_url: str, source_url: str) -> str:
        media_path = unquote(urlparse(media_url).path)
        media_name = os.path.basename(media_path)
        if os.path.splitext(media_path)[1].lower() in MEDIA_EXTENSIONS and media_name:
            return media_name
        query = parse_qs(urlparse(source_url).query)
        source_name = unquote((query.get("file") or [""])[0])
        return source_name or media_name


class GetemStreamResolver(HtmlMediaResolver):
    HOSTNAMES = {"getem.boun.edu.tr", "www.getem.boun.edu.tr"}
    PLAYER_PATH = "/getemPlayerYeni/getemplayer.php"

    def supports(self, url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        return (
            hostname in self.HOSTNAMES
            and parsed.path.lower() == self.PLAYER_PATH.lower()
        )


class StreamResolverRegistry:
    def __init__(self, resolvers: Optional[List[StreamResolver]] = None) -> None:
        self._resolvers = resolvers or [GetemStreamResolver()]

    def resolve(self, url: str) -> Optional[StreamResolution]:
        for resolver in self._resolvers:
            if not resolver.supports(url):
                continue
            logging.info(
                "Resolving stream page with %s: %s",
                resolver.__class__.__name__,
                url,
            )
            return resolver.resolve(url)
        return None
