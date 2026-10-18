"""Turns the text of an AI model into plain text for a TeamTalk message.

TeamTalk shows messages as they are, so the Markdown the models like to write
(``**bold**``, ``# headings``, code fences...) would only appear as stray
symbols. Underscore italics are left alone on purpose: they would damage
names such as ``snake_case`` and URLs.
"""

import re

_FENCE = re.compile(r"^[ \t]*```[^\n]*\n?", re.MULTILINE)
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_BULLET = re.compile(r"^([ \t]*)[*+][ \t]+", re.MULTILINE)
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_QUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE)
_RULE = re.compile(r"^[ \t]*([-*_])\1{2,}[ \t]*$", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)


def _link(match: "re.Match[str]") -> str:
    label, url = match.group(1).strip(), match.group(2)
    return url if label == url else "{} ({})".format(label, url)


def to_plain_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FENCE.sub("", text)
    text = _LINK.sub(_link, text)
    text = _BOLD.sub(lambda m: m.group(2), text)
    text = _BULLET.sub(lambda m: m.group(1) + "- ", text)
    text = _ITALIC.sub(lambda m: m.group(1), text)
    text = _INLINE_CODE.sub(lambda m: m.group(1), text)
    text = _HEADING.sub("", text)
    text = _QUOTE.sub("", text)
    text = _RULE.sub("", text)
    text = _TRAILING_SPACE.sub("", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def shorten(text: str, limit: int) -> str:
    """Cuts text to about ``limit`` characters at a sentence or word end."""
    if limit <= 0 or len(text) <= limit:
        return text
    ellipsis = "..."
    room = max(limit - len(ellipsis), 1)
    cut = text[:room]
    window = max(int(room * 0.75), 1)
    for separator in ("\n", ". ", "! ", "? ", " "):
        index = cut.rfind(separator)
        if index >= window:
            cut = cut[: index + (1 if separator.strip() else 0)]
            break
    return cut.rstrip() + ellipsis
