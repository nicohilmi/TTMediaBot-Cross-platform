"""Who may ask the AI, how often, and who is in the middle of a chat."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from bot.ai.errors import AIError
from bot.ai.provider import AIAnswer, AIProvider, ProviderFactory, create_provider

# Remembered users beyond this number are pruned (oldest first).
MAX_TRACKED_USERS = 256


@dataclass
class _Chat:
    username: str
    conversation_id: Optional[str]
    last_active: float


@dataclass
class _Usage:
    busy: bool = False
    last_finished: float = float("-inf")


class AIManager:
    def __init__(
        self,
        get_config: Callable[[], Any],
        provider_factory: ProviderFactory = create_provider,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._get_config = get_config
        self._provider_factory = provider_factory
        self._clock = clock
        self._lock = threading.RLock()
        self._provider: Optional[AIProvider] = None
        self._provider_signature: Optional[str] = None
        self._chats: Dict[int, _Chat] = {}
        self._usage: Dict[int, _Usage] = {}
        self._slots = threading.BoundedSemaphore(
            max(int(get_config().max_concurrent_requests), 1)
        )

    # -------------------------------------------------------------- provider

    @property
    def config(self) -> Any:
        return self._get_config()

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled)

    def provider(self) -> AIProvider:
        """The service in use; rebuilt when its settings were changed."""
        config = self.config
        signature = "{}|{!r}".format(config.provider, getattr(config, config.provider, None))
        with self._lock:
            if self._provider is None or signature != self._provider_signature:
                self._provider = self._provider_factory(config)
                self._provider_signature = signature
            return self._provider

    def provider_title(self) -> str:
        try:
            return self.provider().title or "AI"
        except AIError:
            return "AI"

    # ----------------------------------------------------------------- chats

    def _expired(self, chat: _Chat) -> bool:
        minutes = float(self.config.chat_idle_minutes)
        return minutes > 0 and self._clock() - chat.last_active > minutes * 60

    def _chat_of(self, user: Any) -> Optional[_Chat]:
        chat = self._chats.get(user.id)
        if chat is None:
            return None
        # A TeamTalk user id can be given to someone else after a disconnect.
        if chat.username != user.username or self._expired(chat):
            del self._chats[user.id]
            return None
        return chat

    def is_chatting(self, user: Any) -> bool:
        with self._lock:
            return self._chat_of(user) is not None

    def start_chat(self, user: Any) -> None:
        with self._lock:
            self._chats[user.id] = _Chat(user.username, None, self._clock())

    def clear_chat(self, user: Any) -> None:
        with self._lock:
            chat = self._chat_of(user)
            if chat is not None:
                chat.conversation_id = None
                chat.last_active = self._clock()

    def end_chat(self, user: Any) -> bool:
        with self._lock:
            return self._chats.pop(user.id, None) is not None

    # ------------------------------------------------------------------- ask

    def _begin(self, user: Any, question: str) -> _Usage:
        config = self.config
        if not config.enabled:
            raise AIError("disabled")
        if not question:
            raise AIError("empty_question")
        limit = int(config.max_question_length)
        if limit > 0 and len(question) > limit:
            raise AIError("too_long", str(limit))
        with self._lock:
            if len(self._usage) > MAX_TRACKED_USERS:
                for key in sorted(self._usage, key=lambda k: self._usage[k].last_finished)[:32]:
                    if not self._usage[key].busy:
                        del self._usage[key]
            usage = self._usage.setdefault(user.id, _Usage())
            if usage.busy:
                raise AIError("user_busy")
            wait = float(config.cooldown_seconds) - (self._clock() - usage.last_finished)
            if wait > 0:
                raise AIError("cooldown", retry_after=wait)
            usage.busy = True
            return usage

    def check_ready(self) -> None:
        """Raises AIError when a question could not be answered at all right now."""
        if not self.enabled:
            raise AIError("disabled")
        if not self.provider().is_configured():
            raise AIError("not_configured")

    def ask(
        self,
        user: Any,
        question: str,
        chat: bool = False,
        on_start: Optional[Callable[[], None]] = None,
    ) -> AIAnswer:
        """Answers a question. With ``chat`` the answer continues the user's chat.

        ``on_start`` is called when the question is accepted and the request is
        about to be made (it can show "AI is thinking...").
        """
        question = (question or "").strip()
        usage = self._begin(user, question)
        try:
            if not self._slots.acquire(blocking=False):
                raise AIError("busy_global")
            try:
                provider = self.provider()
                with self._lock:
                    session = self._chat_of(user) if chat else None
                    conversation_id = session.conversation_id if session else None
                if on_start is not None:
                    on_start()
                answer = provider.ask(
                    question,
                    conversation_id=conversation_id,
                    keep_history=session is not None,
                )
                if session is not None:
                    with self._lock:
                        session.conversation_id = answer.conversation_id
                        session.last_active = self._clock()
                return answer
            finally:
                self._slots.release()
        finally:
            with self._lock:
                usage.busy = False
                usage.last_finished = self._clock()
