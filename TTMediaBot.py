import sys

if sys.version_info < (3, 10):
    sys.exit(
        "TTMediaBot needs Python 3.10 or newer (it is optimized for Python 3.15). "
        "This is Python {}.{}.{}. Install a newer Python, delete the venv folder and "
        "run install_windows.bat (Windows) or install.sh (Linux) again.".format(
            *sys.version_info[:3]
        )
    )

from typing import Optional

from os import path

from argparse import ArgumentParser


def _finish_pending_update() -> None:
    """Runs what the last update asked for (see tools/apply_update.py) before the
    bot and its packages are loaded. It can never keep the bot from starting."""
    try:
        import importlib.util

        script = path.join(path.dirname(path.abspath(__file__)), "tools", "apply_update.py")
        if not path.isfile(script):
            return
        spec = importlib.util.spec_from_file_location("ttbot_apply_update", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.run_pending()
    except Exception as error:
        print("Could not finish the update steps:", error)


_finish_pending_update()

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
