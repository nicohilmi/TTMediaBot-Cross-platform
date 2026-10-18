"""What every AI service (Gemini now, others later) has to offer the bot."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from bot.ai.errors import AIError


@dataclass
class AIAnswer:
    text: str
    # (title, url) of the pages the answer is based on, when it was grounded.
    sources: List[Tuple[str, str]] = field(default_factory=list)
    # Identifies the conversation so the next question can continue it. None when
    # the service keeps nothing (a single question).
    conversation_id: Optional[str] = None
    # True when the service had to forget the conversation (it had expired).
    conversation_reset: bool = False
    searched: bool = False


class AIProvider(ABC):
    name = ""
    # Shown to people ("Welcome to Gemini chat!").
    title = ""

    @abstractmethod
    def is_configured(self) -> bool:
        """True when everything needed to ask (an API key...) is present."""

    @abstractmethod
    def ask(
        self,
        question: str,
        conversation_id: Optional[str] = None,
        keep_history: bool = False,
    ) -> AIAnswer:
        """Answers one question; raises AIError when that is not possible."""


ProviderFactory = Callable[[Any], AIProvider]


def _gemini(ai_config: Any) -> AIProvider:
    # Imported here so the bot starts even when google-genai is not installed.
    from bot.ai.gemini import GeminiProvider

    return GeminiProvider(ai_config.gemini)


# Another service is added by writing a class like GeminiProvider and listing it
# here; ``ai.provider`` in config.json then selects it.
PROVIDERS: Dict[str, ProviderFactory] = {"gemini": _gemini}


def create_provider(ai_config: Any) -> AIProvider:
    name = str(ai_config.provider).strip().lower()
    try:
        factory = PROVIDERS[name]
    except KeyError:
        raise AIError("unknown_provider", name)
    return factory(ai_config)
