from __future__ import annotations
import logging
import os
import subprocess
import sys
import time
from typing import Optional, TYPE_CHECKING
from queue import Empty

from bot.commands.command import Command
from bot.player.enums import State
from bot import app_vars, errors, update_state
from bot.updater import UpdateError, short_sha

if TYPE_CHECKING:
    from bot.TeamTalk.structs import User


class BlockCommandCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate(
            "+/-COMMAND Blocks or unblocks commands. +COMMAND adds command to the blocklist. -COMMAND removes from it. Without a command shows the blocklist"
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        arg = arg.lower()
        if len(arg) >= 1 and arg[1:] not in self.command_processor.commands_dict:
            raise errors.InvalidArgumentError()
        if not arg:
            return (
                ", ".join(self.config.general.blocked_commands)
                if self.config.general.blocked_commands
                else self.translator.translate("The list is empty")
            )
        if arg[0] == "+":
            if arg[1::] not in self.config.general.blocked_commands:
                self.config.general.blocked_commands.append(arg[1::])
                return self.translator.translate("Added")
            else:
                return self.translator.translate("This command is already added")
        elif arg[0] == "-":
            if arg[1::] in self.config.general.blocked_commands:
                del self.config.general.blocked_commands[
                    self.config.general.blocked_commands.index(arg[1::])
                ]
                return self.translator.translate("Deleted")
            else:
                return self.translator.translate("This command is not blocked")
        else:
            raise errors.InvalidArgumentError()


class ChangeGenderCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate(
            "GENDER Changes bot's gender. n neutral, m male, f female"
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        try:
            self.ttclient.change_gender(arg)
            self.config.teamtalk.gender = arg
        except KeyError:
            raise errors.InvalidArgumentError()


class ChangeLanguageCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("LANGUAGE Changes bot's language")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        if arg:
            try:
                self.translator.set_locale(arg)
                self.config.general.language = arg
                self.ttclient.change_status_text("")
                return self.translator.translate("The language has been changed")
            except errors.LocaleNotFoundError:
                return self.translator.translate("Incorrect language")
        else:
            return self.translator.translate(
                "Current language: {current_language}. Available languages: {available_languages}"
            ).format(
                current_language=self.translator.get_locale(),
                available_languages=", ".join(self.translator.get_locales()),
            )


class ChangeNicknameCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("NICKNAME Changes bot's nickname")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        self.ttclient.change_nickname(arg)
        self.config.teamtalk.nickname = arg


class ClearCacheCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate(
            "r/f Clears bot's cache. r clears recents, f clears favorites, without an option clears the entire cache"
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        if not arg:
            self.cache.recents.clear()
            self.cache.favorites.clear()
            self.cache_manager.save()
            return self.translator.translate("Cache cleared")
        elif arg == "r":
            self.cache.recents.clear()
            self.cache_manager.save()
            return self.translator.translate("Recents cleared")
        elif arg == "f":
            self.cache.favorites.clear()
            self.cache_manager.save()
            return self.translator.translate("Favorites cleared")


class JoinChannelCommand(Command):
    # Seconds to wait for the server to confirm that the bot joined.
    JOIN_TIMEOUT = 10

    @property
    def help(self) -> str:
        return self.translator.translate(
            'Join channel. first argument is channel name or id, second argument is password, split argument " | ", if password is undefined, don\'t type second argument'
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        args = self.command_processor.split_arg(arg)
        if not arg:
            channel = self.config.teamtalk.channel
            password = self.config.teamtalk.channel_password
        elif len(args) == 2:
            channel = args[0]
            password = args[1]
        else:
            channel = arg
            password = ""
        if isinstance(channel, str) and channel.isdigit():
            channel = int(channel)
        try:
            cmd = self.ttclient.join_channel(channel, password)
        except ValueError:
            return self.translator.translate("This channel does not exist")
        # Wait for the server to answer, but never forever: the old loop had no
        # exit, so a lost confirmation left this command thread spinning and the
        # user without any reply.
        deadline = time.monotonic() + self.JOIN_TIMEOUT
        while time.monotonic() < deadline:
            try:
                event = self.ttclient.event_success_queue.get_nowait()
                if event.source == cmd:
                    return self.translator.translate("Joined the channel")
                self.ttclient.event_success_queue.put(event)
            except Empty:
                pass
            try:
                error = self.ttclient.errors_queue.get_nowait()
                if error.command_id == cmd:
                    return self.translator.translate(
                        "Error joining channel: {error}"
                    ).format(error=error.message)
                self.ttclient.errors_queue.put(error)
            except Empty:
                pass
            time.sleep(app_vars.loop_timeout)
        logging.warning(
            f"JoinChannelCommand: no server confirmation for command id {cmd} "
            f"within {self.JOIN_TIMEOUT}s (channel={channel!r})"
        )
        return self.translator.translate(
            "No confirmation from the server, the bot may not have joined the channel"
        )


""" class TaskSchedulerCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("Task scheduler")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        if arg[0] == "+":
            self._add(arg[1::])

    def _add(self, arg: str) -> None:
        args = arg.split("|")
        timestamp = self._get_timestamp(args[0])
        task = []
        for arg in args[1::]:
            try:
                command, arg = self.parse_command(message.text)
                if self.check_access(message.user, command):
                    command = self.get_command(command, message.user)
                    task.append((command, arg))
            except errors.AccessDeniedError as e:
                return e
            except (errors.ParseCommandError, errors.UnknownCommandError):
                return self.translator.translate("Unknown command. Send \"h\" for help.")
            except errors.InvalidArgumentError:
                return self.help(command, message.user)
        if timestamp in self.module_manager.task_scheduler.tasks:
            self.module_manager.task_scheduler[timestamp].append(task)
        else:
            self.module_manager.task_scheduler.tasks[timestamp] = [task,]


    def _get_timestamp(self, t):
        return int(datetime.combine(datetime.today(), datetime.strptime(t, self.config["general"]["time_format"]).time()).timestamp())
 """


class VoiceTransmissionCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("Enables or disables voice transmission")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        if not self.ttclient.is_voice_transmission_enabled:
            self.ttclient.enable_voice_transmission()
            if self.player.state == State.Stopped:
                self.ttclient.change_status_text(
                    self.translator.translate("Voice transmission enabled")
                )
            return self.translator.translate("Voice transmission enabled")
        else:
            self.ttclient.disable_voice_transmission()
            if self.player.state == State.Stopped:
                self.ttclient.change_status_text("")
            return self.translator.translate("Voice transmission disabled")


class LockCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("Locks or unlocks the bot")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        self.command_processor.locked = not self.command_processor.locked
        return (
            self.translator.translate("Locked")
            if self.command_processor.locked
            else self.translator.translate("Unlocked")
        )


class ChangeStatusCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("STATUS Changes bot's status")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        self.ttclient.change_status_text(arg)
        self.config.teamtalk.status = arg


class EventHandlingCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("Enables or disables event handling")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        self.config.teamtalk.event_handling.load_event_handlers = (
            not self.config.teamtalk.event_handling.load_event_handlers
        )
        return (
            self.translator.translate("Event handling is enabled")
            if self.config.teamtalk.event_handling.load_event_handlers
            else self.translator.translate("Event handling is disabled")
        )


class ChannelMessagesCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate(
            "Enables or disables sending of channel messages"
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        self.config.general.send_channel_messages = (
            not self.config.general.send_channel_messages
        )
        return (
            self.translator.translate("Channel messages enabled")
            if self.config.general.send_channel_messages
            else self.translator.translate("Channel messages disabled")
        )


class SaveConfigCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("Saves bot's configuration")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        self.config_manager.save()
        return self.translator.translate("Configuration saved")


class AdminUsersCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate(
            "+/-USERNAME Manages a list of administrators. +USERNAME adds a user. -USERNAME removes it. Without an option shows the list"
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        if arg:
            if arg[0] == "+":
                self.config.teamtalk.users.admins.append(arg[1::])
                return self.translator.translate("Added")
            elif arg[0] == "-":
                try:
                    del self.config.teamtalk.users.admins[
                        self.config.teamtalk.users.admins.index(arg[1::])
                    ]
                    return self.translator.translate("Deleted")
                except ValueError:
                    return self.translator.translate(
                        "This user is not in the admin list"
                    )
        else:
            admins = self.config.teamtalk.users.admins.copy()
            if len(admins) > 0:
                if "" in admins:
                    admins[admins.index("")] = self.translator.translate("<Anonymous>")
                return ", ".join(admins)
            else:
                return self.translator.translate("The list is empty")


class BannedUsersCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate(
            "+/-USERNAME Manages a list of banned users. +USERNAME adds a user. -USERNAME removes it. Without an option shows the list"
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        if arg:
            if arg[0] == "+":
                self.config.teamtalk.users.banned_users.append(arg[1::])
                return self.translator.translate("Added")
            elif arg[0] == "-":
                try:
                    del self.config.teamtalk.users.banned_users[
                        self.config.teamtalk.users.banned_users.index(arg[1::])
                    ]
                    return self.translator.translate("Deleted")
                except ValueError:
                    return self.translator.translate("This user is not banned")
        else:
            banned_users = self.config.teamtalk.users.banned_users.copy()
            if len(banned_users) > 0:
                if "" in banned_users:
                    banned_users[banned_users.index("")] = self.translator.translate("<Anonymous>")
                return ", ".join(banned_users)
            else:
                return self.translator.translate("The list is empty")


class QuitCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("Quits the bot")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        self._bot.close()


class RestartCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("Restarts the bot")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        self._bot.close()
        args = sys.argv
        if sys.platform == "win32":
            # os.execv does not replace the process on Windows: start a fresh
            # copy and leave, so restarts do not pile up nested processes.
            subprocess.Popen([sys.executable] + args, close_fds=True)
            os._exit(0)
        else:
            args.insert(0, sys.executable)
            os.execv(sys.executable, args)


class FadeOutCommand(Command):
    MIN_SECONDS = 0.5
    MAX_SECONDS = 15.0

    @property
    def help(self) -> str:
        return self.translator.translate(
            "[on/off/SECONDS] Turns the fade-out when stopping playback on or off. A number of seconds sets its length and turns it on. Without an option it switches between on and off"
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        player_config = self.config.player
        arg = arg.strip().lower()
        if not arg:
            player_config.fade_out_on_stop = not player_config.fade_out_on_stop
        elif arg == "on":
            player_config.fade_out_on_stop = True
        elif arg == "off":
            player_config.fade_out_on_stop = False
        else:
            try:
                seconds = float(arg.replace(",", "."))
            except ValueError:
                raise errors.InvalidArgumentError()
            if not self.MIN_SECONDS <= seconds <= self.MAX_SECONDS:
                raise errors.InvalidArgumentError()
            player_config.fade_out_duration = seconds
            player_config.fade_out_on_stop = True  # a length only matters when on
        if not player_config.fade_out_on_stop:
            return self.translator.translate("Fade-out on stop is disabled")
        return self.translator.translate(
            "Fade-out on stop is enabled ({seconds} seconds)"
        ).format(seconds="{:g}".format(player_config.fade_out_duration))


class InstallUpdateCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate(
            "Installs the latest update from GitHub, then restarts the bot"
        )

    def __call__(self, arg: str, user: User) -> Optional[str]:
        checker = self._bot.update_checker
        if not checker.install_lock.acquire(blocking=False):
            return self.translator.translate("An update is already being installed")
        try:
            message = self._install(checker, user)
        finally:
            checker.install_lock.release()
        if message is not None:
            return message
        # Installed: leave a note for the next start, say goodbye and restart.
        try:
            update_state.write_success_marker(
                self._bot.config_manager.config_dir, *self._installed
            )
        except OSError as error:
            logging.warning(f"Could not write the update marker file: {error}")
        self._bot.is_updating = True
        RestartCommand(self.command_processor)("", user)
        return None

    _installed = ("", "")

    def _install(self, checker, user: User) -> Optional[str]:
        """Returns a message for the user, or None when the bot should restart."""
        translate = self.translator.translate
        try:
            info = checker.check()
        except UpdateError as error:
            return translate("Unable to check for updates: {error}").format(error=error)
        if info is None:
            return translate("TTMediaBot is up to date (version {version}).").format(
                version=app_vars.app_version
            )
        self.ttclient.send_message(
            translate("Installing the update. This takes a moment."), user
        )
        try:
            new_sha = checker.install(info)
        except UpdateError as error:
            return translate("The update could not be installed: {error}").format(
                error=error
            )
        self._installed = (short_sha(info.local_sha), short_sha(new_sha))
        if info.requirements_changed:
            # The packages cannot be replaced while the bot is using them. They are
            # installed during the restart, before the bot loads them (see
            # tools/apply_update.py), the way an OS finishes an update on reboot.
            try:
                update_state.request_requirements_install()
            except OSError as error:
                logging.warning(f"Could not ask for the package installation: {error}")
                return translate(
                    "The update was installed, but it changes the required Python packages. Run pip install -r requirements.txt on the bot's computer, then send rs to restart the bot."
                )
            self.ttclient.send_message(
                translate(
                    "Update installed. The bot restarts now and installs the required Python packages while it starts."
                ),
                user,
            )
            time.sleep(0.5)
            return None
        self.ttclient.send_message(
            translate("Update installed. Restarting now to apply it."), user
        )
        time.sleep(0.5)
        return None


class GetChannelIDCommand(Command):
    @property
    def help(self) -> str:
        return self.translator.translate("Returns current channel's ID")

    def __call__(self, arg: str, user: User) -> Optional[str]:
        return str(self.ttclient.channel.id)
