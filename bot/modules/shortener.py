# Python 3.15 (PEP 810) loads pyshorteners (and the web libraries it pulls in) only when a link
# is shortened. It is off by default, so most bots never pay for it; older Python versions
# treat this line as a plain list and import it at once, as before.
__lazy_modules__ = ["pyshorteners"]

import logging

import pyshorteners

from bot.config.models import ShorteningModel


class Shortener:
    def __init__(self, config: ShorteningModel) -> None:
        self.shorten_links = config.shorten_links
        self.shortener = pyshorteners.Shortener(**config.service_params)
        if config.service not in self.shortener.available_shorteners:
            logging.error("Unknown shortener service, this feature will be disabled")
            self.shorten_links = False
        self.shorten_service = getattr(self.shortener, config.service, None)

    def get(self, url: str) -> str:
        try:
            if self.shorten_links:
                return self.shorten_service.short(url)
        except Exception:
            logging.error("", exc_info=True)
            self.shorten_links = False
        return url
