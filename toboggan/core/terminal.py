# Built-in imports
import shlex
import re

# External library imports
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import ThreadedAutoSuggest, AutoSuggestFromHistory
from prompt_toolkit.history import ThreadedHistory, InMemoryHistory
from prompt_toolkit.cursor_shapes import CursorShape

# Local library imports
from toboggan.core import logbook
from toboggan.core.executor import Executor
from toboggan.core.action import NamedPipe


class Terminal:
    def __init__(self, executor: Executor, prefix="!"):
        self._logger = logbook.get_logger()

        self.__prompt_session = PromptSession(
            cursor=CursorShape.BLINKING_BLOCK,
            multiline=False,
            enable_history_search=True,
            wrap_lines=True,
            auto_suggest=ThreadedAutoSuggest(auto_suggest=AutoSuggestFromHistory()),
            history=ThreadedHistory(history=InMemoryHistory()),
        )

        self.__target = executor.target
        self.__executor = executor
        self.__prefix = prefix

    # Public methods

    def start(self) -> None:
        result = None
        user_input = ""

        self._logger.info(
            f"🔧 Prefix set to '{self.__prefix}' — use '{self.__prefix}h' for available commands."
        )

        while True:
            try:
                user_input = self.__prompt_session.prompt(message=self.__prompt())
                if not user_input:
                    continue
            except KeyboardInterrupt:
                self._logger.warning("Keyboard interruption received.")

                if (
                    self.__target.os == "linux"
                    and self.__executor.os_helper.is_fifo_active()
                ):
                    self.__executor.os_helper.stop_named_pipe()

                self.__executor.delete_working_directory()

                break
            except Exception as exc:
                self._logger.warning(f"Exception occured: {exc}")
                continue
            else:
                if not user_input.startswith(self.__prefix):
                    if (
                        self.__target.os == "linux"
                        and self.__executor.os_helper.is_fifo_active()
                    ):
                        self.__executor.os_helper.fifo_execute(user_input)
                        continue

                    if result := self.__executor.remote_execute(command=user_input):
                        print(result)

                    continue

                try:
                    command_parts = shlex.split(
                        user_input[len(self.__prefix) :].strip()
                    )
                except ValueError as e:
                    self._logger.error(f"❌ Command parsing failed: {e}")
                    continue

                if not command_parts:
                    continue

                command = command_parts[0].lower().replace("-", "_")

                raw_args = command_parts[1:]

                if command in ["e", "ex", "exit"]:
                    self._logger.info("🛝 Sliding back up the toboggan.")
                    break

                if command in ["help", "h"]:
                    print(self.__get_help())
                    continue

                if command == "max_size":
                    if raw_args:
                        self.__executor.chunk_max_size = int(raw_args[0])
                    else:
                        self.__executor.chunk_max_size = (
                            self.__executor.calculate_max_chunk_size()
                        )

                    continue

                actions_dict = self.__executor.action_manager.get_actions()

                if targeted_action := actions_dict.get(command):
                    if action_class := self.__executor.action_manager.load_action_from_path(
                        targeted_action["path"]
                    ):

                        if issubclass(action_class, NamedPipe):
                            self.__executor.os_helper.start_named_pipe(
                                action_class, *raw_args
                            )
                            continue

                        # Parse args into kwargs and positionals
                        keyword_args = {}
                        positional_args = []

                        i = 0
                        while i < len(raw_args):
                            arg = raw_args[i]

                            # Handle --key=value
                            if arg.startswith("--") and "=" in arg:
                                key, value = arg[2:].split("=", 1)
                                keyword_args[key] = value
                                i += 1
                                continue

                            # Handle --key value
                            if arg.startswith("--"):
                                key = arg[2:]

                                # If next token exists and is not another --flag, treat it as value
                                if i + 1 < len(raw_args) and not raw_args[
                                    i + 1
                                ].startswith("--"):
                                    keyword_args[key] = raw_args[i + 1]
                                    i += 2
                                else:
                                    keyword_args[key] = True  # Boolean flag
                                    i += 1
                                continue

                            # Handle positional argument
                            positional_args.append(arg)
                            i += 1

                        if raw_args:
                            self._logger.info(
                                f"▶️ Running '{command}' with args: {raw_args}"
                            )
                        else:
                            self._logger.info(f"▶️ Running '{command}'")

                        try:
                            action = action_class(self.__executor)

                            if positional_args or keyword_args:
                                action_output = action.run(
                                    *positional_args, **keyword_args
                                )
                            else:
                                action_output = action.run()

                        except TypeError as exc:
                            self._logger.warning(
                                f"⚠️ Incorrect arguments for '{command}': {exc}"
                            )
                            continue
                        except Exception as exc:
                            self._logger.error(f"❌ Action '{command}' failed: {exc}")
                            continue

                        if action_output is not None:
                            print(action_output)

                        continue

                self._logger.error(
                    f"❌ Unknown command: '{command}'. Type '!help' to see available commands."
                )

    # Private methods

    def __get_help(self) -> str:
        """Generates a well-formatted help message for available actions."""
        actions = self.__executor.action_manager.get_actions()

        if not actions:
            return "❌ No available actions found."

        # ANSI styles
        BOLD = "\033[1m"
        GREEN = "\033[92m"
        CYAN = "\033[96m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        def ansi_ljust(text: str, width: int) -> str:
            """Left-justify while ignoring ANSI escape codes."""
            ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
            visible_length = len(ansi_escape.sub("", text))
            return text + " " * (width - visible_length)

        # Align column widths
        max_action_length = max(len(action) for action in actions) + 2

        lines = []
        lines.append(f"\n{BOLD}Available Actions:{RESET}")
        lines.append(DIM + "-" * (max_action_length + 50) + RESET)

        for action, details in sorted(actions.items()):
            description = details.get("description", "No description available")
            action_colored = f"{GREEN}{action}{RESET}"
            lines.append(
                f"🔹 {ansi_ljust(action_colored, max_action_length)} → {CYAN}{description}{RESET}"
            )
            if details.get("parameters"):
                params = ", ".join(details["parameters"])
                lines.append(f"    ⚙️ Parameters: {params}")

        lines.append(DIM + "-" * (max_action_length + 50) + RESET)
        lines.append(
            f"{BOLD}Usage:{RESET} Type '!action_name' followed by parameters if required.\n"
        )

        # Built-in commands
        lines.append(f"{BOLD}Built-in Commands:{RESET}")
        lines.append(DIM + "-" * (max_action_length + 50) + RESET)
        lines.append(
            f"🔹 {ansi_ljust(f'{GREEN}max_size{RESET}', max_action_length)} → "
            f"{CYAN}Probe or manually set the max command size.{RESET}"
        )
        lines.append(f"    ⚙️ Parameters: bytes (optional, multiple of 1024)")
        lines.append(
            f"🔹 {ansi_ljust(f'{GREEN}exit{RESET}', max_action_length)} → "
            f"{CYAN}Exit the toboggan shell session.{RESET}"
        )

        return "\n".join(lines)

    def __prompt(self) -> str:
        """Generates a dynamic shell prompt based on available target information."""

        if self.__target.os == "linux" and self.__executor.os_helper.is_fifo_active():
            return ""
        
        user = self.__target.user
        host = self.__target.hostname
        pwd = self.__target.pwd

        # Build prompt with available information
        if user and host and pwd:
            return f"({user}@{host})-[{pwd}]$ "
        elif user and host:
            return f"{user}@{host}:~$ "
        elif host and pwd:
            return f"{host}:{pwd}$ "
        elif user and pwd:
            return f"{user}:{pwd}$ "
        elif pwd:
            return f"{pwd}$ "
        elif user:
            return f"{user}@localhost:~$ "
        elif host:
            return f"{host}:~$ "
        
        return "$ "
