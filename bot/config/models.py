from typing import Any, Dict, List, Union

from pydantic import BaseModel


class GeneralModel(BaseModel):
    language: str = "en"
    send_channel_messages: bool = True
    cache_file_name: str = "TTMediaBotCache.dat"
    blocked_commands: List[str] = []
    delete_uploaded_files_after: int = 300
    time_format: str = r"%H:%M"
    start_commands: List[str] = []
    search_results_mode: bool = False

class PlayerModel(BaseModel):
    default_volume: int = 50
    max_volume: int = 100
    volume_fading: bool = True
    volume_fading_interval: float = 0.025
    seek_step: int = 5
    # Leave empty to auto-detect: ffmpeg(.exe) in the bot folder first, then the
    # ffmpeg installed on the system (PATH). Or set a full path / a folder.
    ffmpeg_path: str = ""
    # Seconds of decoded audio kept ahead of playback to ride out network jitter.
    buffer_seconds: float = 5.0
    # Seconds without any network data before a stream is considered dead.
    network_timeout: float = 30.0
    # "cubic" matches the loudness curve of the former mpv player, "linear" is a
    # plain percentage.
    volume_curve: str = "cubic"

class TeamTalkUserModel(BaseModel):
    admins: List[str] = ["admin"]
    banned_users: List[str] = []


class EventHandlingModel(BaseModel):
    load_event_handlers: bool = False
    event_handlers_file_name: str = "event_handlers.py"


class TeamTalkModel(BaseModel):
    hostname: str = "localhost"
    tcp_port: int = 10333
    udp_port: int = 10333
    encrypted: bool = False
    nickname: str = "TTMediaBot"
    status: str = ""
    gender: str = "n"
    username: str = ""
    password: str = ""
    channel: Union[int, str] = "/"
    channel_password: str = ""
    license_name: str = ""
    license_key: str = ""
    reconnection_attempts: int = -1
    reconnection_timeout: int = 10
    users: TeamTalkUserModel = TeamTalkUserModel()
    event_handling: EventHandlingModel = EventHandlingModel()




class YtModel(BaseModel):
    enabled: bool = True
    cookiefile_path: str = ""
    search_results: int = 1




class YtmModel(BaseModel):
    enabled: bool = True
    search_results: int = 1


class ServicesModel(BaseModel):
    default_service: str = "yt"
    yt: YtModel = YtModel()
    ytm: YtmModel = YtmModel()


class LoggerModel(BaseModel):
    log: bool = True
    level: str = "INFO"
    format: str = "%(levelname)s [%(asctime)s]: %(message)s in %(threadName)s file: %(filename)s line %(lineno)d function %(funcName)s"
    mode: Union[int, str] = "FILE"
    file_name: str = "TTMediaBot.log"
    max_file_size: int = 0
    backup_count: int = 0


class ShorteningModel(BaseModel):
    shorten_links: bool = False
    service: str = "clckru"
    service_params: Dict[str, Any] = {}


class ConfigModel(BaseModel):
    config_version: int = 0
    general: GeneralModel = GeneralModel()
    player: PlayerModel = PlayerModel()
    teamtalk: TeamTalkModel = TeamTalkModel()
    services: ServicesModel = ServicesModel()
    logger: LoggerModel = LoggerModel()
    shortening: ShorteningModel = ShorteningModel()
