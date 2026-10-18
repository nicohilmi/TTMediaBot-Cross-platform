"""Gemini through Google's official ``google-genai`` SDK.

This uses the Interactions API (``client.interactions.create``), which Google
recommends for new development, with the ``google_search`` tool for
"Grounding with Google Search". A chat keeps its history on Google's side and is
continued with ``previous_interaction_id``; a single question is sent with
``store=False`` so nothing is kept.

Documentation:
https://ai.google.dev/gemini-api/docs/interactions-overview
https://ai.google.dev/gemini-api/docs/google-search
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from bot.ai.errors import AIError
from bot.ai.provider import AIAnswer, AIProvider

ENV_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
MAX_SOURCES = 5
MAX_DETAIL_LENGTH = 200

DEFAULT_INSTRUCTION = (
    "You are an assistant that answers text messages sent in a TeamTalk voice chat "
    "server. Reply in the language of the user's message. Keep answers short and "
    "clear, ideally under 900 characters. Write plain text only: no Markdown, no "
    "asterisks, no headings, no tables and no code fences. A short list may use "
    "lines that start with '- '. For the weather, news, prices, sports results and "
    "anything else that changes, search Google and say which day or time the "
    "answer is for."
)


def _get(obj: Any, name: str) -> Any:
    """Reads a field from an SDK object or from a plain dictionary."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def build_instruction(custom: str = "", now: Optional[datetime] = None) -> str:
    base = (custom or "").strip() or DEFAULT_INSTRUCTION
    stamp = now or datetime.now().astimezone()
    return "{}\nCurrent date and time: {} ({}).".format(
        base, stamp.strftime("%A, %d %B %Y, %H:%M"), stamp.strftime("%Z %z").strip()
    )


def _short(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    text = "{}: {}".format(type(exc).__name__, text) if text else type(exc).__name__
    if len(text) > MAX_DETAIL_LENGTH:
        text = text[: MAX_DETAIL_LENGTH - 3] + "..."
    return text


def _status(exc: BaseException) -> Optional[int]:
    candidates = (
        _get(exc, "code"),
        _get(exc, "status_code"),
        _get(_get(exc, "response"), "status_code"),
    )
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value < 600:
            return value
    return None


def classify_error(exc: BaseException) -> Tuple[str, bool]:
    """Returns (kind, retryable) for an exception raised by the SDK.

    Only the HTTP status and the wording of the error are used, so this works
    with every exception type the SDK has had.
    """
    status = _status(exc)
    text = "{} {}".format(type(exc).__name__, exc).lower()

    if "location is not supported" in text or "not available in your country" in text:
        return "region", False
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout", True
    if status in (401, 403) or any(
        word in text
        for word in ("api key", "api_key_invalid", "permission_denied", "unauthenticated")
    ):
        return "auth", False
    if status == 429 or "resource_exhausted" in text or "quota" in text:
        # "Please retry in 24s" is a per-minute limit that clears by itself; a
        # daily limit or a missing plan does not.
        clears_soon = "retry in" in text or "retrydelay" in text
        permanent = not clears_soon and any(
            word in text
            for word in ("per day", "perday", "daily", "billing", "limit: 0", "check your plan")
        )
        return "quota", not permanent
    if "thinking" in text and status in (400, None):
        return "thinking_level", False
    if "interaction" in text and any(
        word in text for word in ("not found", "expired", "invalid", "does not exist")
    ):
        return "conversation_lost", False
    if status == 404 or "not_found" in text:
        return "model", False
    if status is not None and status >= 500:
        return "server", True
    if any(word in text for word in ("unavailable", "overloaded", "internal")):
        return "server", True
    if isinstance(exc, OSError) or any(
        word in text
        for word in ("connecterror", "connection", "getaddrinfo", "name or service", "network")
    ):
        return "network", True
    if status == 400:
        return "rejected", False
    return "unknown", False


class GeminiProvider(AIProvider):
    name = "gemini"
    title = "Gemini"

    def __init__(
        self,
        config: Any,
        client_factory: Optional[Callable[[Any], Any]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._client: Any = None
        self._client_lock = threading.Lock()
        self._sleep = sleep

    # ------------------------------------------------------------------ setup

    def _api_key(self) -> str:
        key = str(self._config.api_key or "").strip()
        if key:
            return key
        for name in ENV_KEYS:
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return ""

    def is_configured(self) -> bool:
        return bool(self._api_key()) or self._client_factory is not None

    def _get_client(self) -> Any:
        with self._client_lock:
            if self._client is not None:
                return self._client
            if self._client_factory is not None:
                self._client = self._client_factory(self._config)
                return self._client
            try:
                from google import genai
            except ImportError:
                raise AIError("sdk_missing", "google-genai is not installed")
            key = self._api_key()
            options = None
            try:
                from google.genai import types

                options = types.HttpOptions(
                    timeout=int(float(self._config.timeout_seconds) * 1000)
                )
            except Exception:
                options = None  # The timeout below still applies.
            if options is not None:
                self._client = genai.Client(api_key=key, http_options=options)
            else:
                self._client = genai.Client(api_key=key)
            return self._client

    # ------------------------------------------------------------------- ask

    def ask(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        keep_history: bool = False,
    ) -> AIAnswer:
        if not self.is_configured():
            raise AIError("not_configured")
        client = self._get_client()
        retries = max(int(self._config.max_retries), 0)
        use_thinking = True
        previous = conversation_id
        reset = False
        attempt = 0
        started = time.monotonic()
        while True:
            try:
                interaction = self._call(client, question, previous, keep_history, use_thinking)
                break
            except AIError:
                raise
            except Exception as exc:
                kind, retryable = classify_error(exc)
                if kind == "thinking_level" and use_thinking and self._config.thinking_level:
                    logging.warning(
                        "[AI] the model rejected thinking_level=%r; asking without it. "
                        "Set ai.gemini.thinking_level to an empty text to stop this warning.",
                        self._config.thinking_level,
                    )
                    use_thinking = False
                    continue
                if kind == "conversation_lost" and previous:
                    logging.info("[AI] the stored conversation is gone; starting a new one")
                    previous = None
                    reset = True
                    continue
                if retryable and attempt < retries:
                    attempt += 1
                    delay = min(2.0 ** (attempt - 1), 8.0)
                    logging.warning(
                        "[AI] %s (%s); retry %d of %d in %.0f s",
                        kind, _short(exc), attempt, retries, delay,
                    )
                    self._sleep(delay)
                    continue
                if kind == "unknown":
                    logging.error("[AI] unexpected error from the SDK", exc_info=True)
                else:
                    logging.warning("[AI] request failed (%s): %s", kind, _short(exc))
                raise AIError(kind, _short(exc)) from exc
        answer = self._to_answer(interaction, reset, keep_history)
        logging.info(
            "[AI] gemini model=%s search=%s answered in %.1f s (%d characters, %d source(s))",
            self._config.model, answer.searched, time.monotonic() - started,
            len(answer.text), len(answer.sources),
        )
        return answer

    def _request(
        self,
        question: str,
        previous: Optional[str],
        keep_history: bool,
        use_thinking: bool,
    ) -> dict:
        request: dict = {
            "model": self._config.model,
            "input": question,
            "system_instruction": build_instruction(self._config.system_instruction),
            "store": bool(keep_history),
        }
        if self._config.google_search:
            request["tools"] = [{"type": "google_search"}]
        if use_thinking and self._config.thinking_level:
            request["generation_config"] = {"thinking_level": self._config.thinking_level}
        if previous:
            request["previous_interaction_id"] = previous
        return request

    def _call(
        self,
        client: Any,
        question: str,
        previous: Optional[str],
        keep_history: bool,
        use_thinking: bool,
    ) -> Any:
        """One request, abandoned (not waited for) after timeout_seconds."""
        request = self._request(question, previous, keep_history, use_thinking)
        outcome: dict = {}
        done = threading.Event()

        def work() -> None:
            try:
                outcome["value"] = client.interactions.create(**request)
            except BaseException as exc:  # handed to the caller below
                outcome["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=work, name="GeminiRequest", daemon=True)
        thread.start()
        if not done.wait(float(self._config.timeout_seconds)):
            raise TimeoutError("no answer from Gemini within {} seconds".format(
                self._config.timeout_seconds
            ))
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]

    # -------------------------------------------------------------- response

    @staticmethod
    def _text_blocks(interaction: Any) -> Iterator[Any]:
        for step in _get(interaction, "steps") or []:
            if _get(step, "type") != "model_output":
                continue
            for block in _get(step, "content") or []:
                if _get(block, "type") == "text":
                    yield block

    @classmethod
    def _text(cls, interaction: Any) -> str:
        text = _get(interaction, "output_text")
        if isinstance(text, str) and text.strip():
            return text
        parts = [_get(block, "text") or "" for block in cls._text_blocks(interaction)]
        return "".join(parts)

    @classmethod
    def _sources(cls, interaction: Any) -> List[Tuple[str, str]]:
        sources: List[Tuple[str, str]] = []
        seen = set()
        for block in cls._text_blocks(interaction):
            for note in _get(block, "annotations") or []:
                if _get(note, "type") not in (None, "url_citation"):
                    continue
                url = _get(note, "url") or _get(note, "uri") or ""
                title = (_get(note, "title") or urlparse(url).netloc or "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                sources.append((title, url))
                if len(sources) >= MAX_SOURCES:
                    return sources
        return sources

    def _to_answer(self, interaction: Any, reset: bool, keep_history: bool) -> AIAnswer:
        text = self._text(interaction).strip()
        if not text:
            raise AIError("empty")
        steps = _get(interaction, "steps") or []
        searched = any(_get(step, "type") == "google_search_call" for step in steps)
        conversation_id = _get(interaction, "id") if keep_history else None
        return AIAnswer(
            text=text,
            sources=self._sources(interaction),
            conversation_id=conversation_id if isinstance(conversation_id, str) else None,
            conversation_reset=reset,
            searched=searched,
        )
