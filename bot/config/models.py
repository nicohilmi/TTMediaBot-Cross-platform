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
    # Stopping with "s" first lowers the volume to silence, then stops. Admins
    # switch it on and off, or set its length, with the "fo" command.
    fade_out_on_stop: bool = True
    fade_out_duration: float = 3.0

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


class UpdaterModel(BaseModel):
    # Looks on GitHub (the git remote of the bot folder) for new commits and tells
    # the TeamTalk channel; an administrator then sends "install" to update.
    enabled: bool = True
    # How often GitHub is checked, in minutes (1 or more).
    check_interval_minutes: int = 60
    # The git remote to watch. The branch is always the one the bot folder is on.
    remote: str = "origin"


class GeminiModel(BaseModel):
    # Create a key at https://aistudio.google.com/apikey. When it is left empty the
    # GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable is used instead.
    api_key: str = ""
    # Google renames and retires models from time to time; the current names are
    # listed at https://ai.google.dev/gemini-api/docs/models
    model: str = "gemini-3.8-flash"
    # Answer with up-to-date information found by Google Search ("grounding").
    google_search: bool = True
    # How long the model thinks before it answers: "low" (fastest), "medium" or
    # "high". Leave it empty to use the default of the model.
    thinking_level: str = "low"
    # Seconds to wait for Google before one request is given up.
    timeout_seconds: float = 60.0
    # How many times a request is repeated when Google is busy or the network fails.
    max_retries: int = 2
    # Extra instructions that shape every answer. Empty uses the built-in ones.
    system_instruction: str = ""


class AIModel(BaseModel):
    # Users type "ai QUESTION" to ask, or "chat" to hold a conversation.
    enabled: bool = True
    # The service that answers. Only "gemini" exists for now.
    provider: str = "gemini"
    # Seconds a user has to wait between two questions.
    cooldown_seconds: float = 2.0
    # The longest question accepted, in characters (0 = no limit).
    max_question_length: int = 2000
    # The longest answer sent, in characters; a longer one is cut (0 = no limit).
    max_answer_length: int = 1500
    # Name the websites an answer found with Google Search is based on.
    show_sources: bool = True
    # A chat ends by itself after this many minutes without a message (0 = never).
    chat_idle_minutes: int = 30
    # Questions that are answered at the same time, over all users.
    max_concurrent_requests: int = 3
    gemini: GeminiModel = GeminiModel()


# Raised whenever config.json gets a new layout that needs more than adding the
# missing settings (see bot/migrators/config_migrator.py).
CONFIG_VERSION = 2


class ConfigModel(BaseModel):
    config_version: int = CONFIG_VERSION
    general: GeneralModel = GeneralModel()
    player: PlayerModel = PlayerModel()
    teamtalk: TeamTalkModel = TeamTalkModel()
    services: ServicesModel = ServicesModel()
    logger: LoggerModel = LoggerModel()
    shortening: ShorteningModel = ShorteningModel()
    updater: UpdaterModel = UpdaterModel()
    ai: AIModel = AIModel()
