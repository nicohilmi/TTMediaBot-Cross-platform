"""Helpers for picking the right search result when only one track is wanted.

YouTube ranks results by relevance, and a "FULL ALBUM" or "non stop" upload can
outrank the single song that was asked for. When the bot plays exactly one search
result, that would start a one hour video instead of the song.
"""
from __future__ import annotations

import re
from typing import Sequence

# Markers of an upload that holds many songs. Deliberately conservative: a false
# positive only makes the bot look at a few more results, never drop a request.
_COLLECTION_RE = re.compile(
    r"\bfull[\s_-]*album\b"
    r"|\balbum[\s_-]*full\b"
    r"|\bnon[\s_-]*stop\b"
    r"|\bplaylist\b"
    r"|\bcompilation\b"
    r"|\bmegamix\b"
    r"|\b\d+(?:[.,]\d+)?[\s_-]*(?:hours?|hrs?|jam)\b",
    re.IGNORECASE,
)


def looks_like_collection(text: str) -> bool:
    """True when ``text`` (a title or a query) names a multi-song upload."""
    return bool(text) and _COLLECTION_RE.search(text) is not None


def pick_single_track_index(query: str, titles: Sequence[str]) -> int:
    """Index of the best result for a request of one song.

    The first result that is not a collection wins. If the query itself asks for
    a collection, or every result is one, the first result is kept.
    """
    if not titles or looks_like_collection(query):
        return 0
    for index, title in enumerate(titles):
        if not looks_like_collection(title or ""):
            return index
    return 0
