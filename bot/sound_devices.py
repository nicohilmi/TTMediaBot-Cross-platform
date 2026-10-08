from __future__ import annotations
from enum import Enum
import logging
import sys
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from bot import Bot


class SoundDevice:
    def __init__(self, name: str, id: Union[int, str], type: SoundDeviceType) -> None:
        self.name = name
        self.id = id
        self.type = type


class SoundDeviceType(Enum):
    Output = 0
    Input = 1


class SoundDeviceManager:
    """Prepares audio output for the bot.

    The bot no longer plays through a sound card. FFmpeg decodes the media and
    the PCM is handed to TeamTalk's virtual sound device, so there is nothing
    to select (the old ``sound_devices`` section of config.json is ignored).
    """

    def __init__(self, bot: Bot) -> None:
        self.ttclient = bot.ttclient

    def initialize(self) -> None:
        logging.debug("Initializing the TeamTalk virtual sound device")
        if not self.ttclient.init_virtual_input_device():
            error = (
                "Could not initialize the TeamTalk virtual sound device. The "
                "TeamTalk SDK library (TeamTalk5.dll / libTeamTalk5.so) is probably "
                "too old: SDK 5.11 or newer is required."
            )
            logging.error(error)
            sys.exit(error)
        logging.debug("Sound devices initialized")
