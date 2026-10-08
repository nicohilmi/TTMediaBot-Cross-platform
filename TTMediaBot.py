from typing import Optional

from os import path

from argparse import ArgumentParser

from bot import Bot, app_vars, ffmpeg_locator, logger
from bot.config import save_default_file

parser = ArgumentParser()
parser.add_argument(
    "-c",
    "--config",
    help="Path to the configuration file",
    default=path.join(app_vars.directory, "config.json"),
)
parser.add_argument("-C", "--cache", help="Path to the cache file", default=None)
parser.add_argument("-l", "--log", help="Path to the log file", default=None)
parser.add_argument(
    "--devices",
    "--check",
    dest="devices",
    help="Show which FFmpeg the bot will use and how audio is sent, then exit",
    action="store_true",
)
parser.add_argument(
    "--default-config",
    help='Save default config to "config_default.json" and exit',
    action="store_true",
)
args = parser.parse_args()


def main(
    config: str = args.config,
    cache: Optional[str] = args.cache,
    log: Optional[str] = args.log,
    devices: bool = args.devices,
    default_config: bool = args.default_config,
) -> None:
    if devices:
        logger.release_bootstrap()
        echo_audio_setup()
    elif default_config:
        save_default_file()
        print("Successfully dumped to config_default.json")
    else:
        bot = Bot(config, cache, log)
        bot.initialize()
        try:
            bot.run()
        except KeyboardInterrupt:
            bot.close()


def echo_audio_setup() -> None:
    print("Audio is decoded by FFmpeg and sent straight to TeamTalk (virtual sound")
    print("device). There is no sound card or output device to select.")
    print()
    try:
        path = ffmpeg_locator.get_ffmpeg()
    except ffmpeg_locator.FFmpegNotFoundError as error:
        print("FFmpeg: NOT FOUND")
        print(error)
        return
    print("FFmpeg: " + path)
    print("Version: " + ffmpeg_locator.get_version())


if __name__ == "__main__":
    main()
