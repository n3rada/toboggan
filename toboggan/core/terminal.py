# Local application/library specific imports
from toboggan.core import logbook
from toboggan.core.executor import Executor
from toboggan.core.action import NamedPipe

# Third party library imports
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import ThreadedAutoSuggest, AutoSuggestFromHistory
from prompt_toolkit.history import ThreadedHistory, InMemoryHistory
from prompt_toolkit.cursor_shapes import CursorShape


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

        self._logger.info(f"Terminal prefix is: {self.__prefix}")

        while True:
            try:
                user_input = self.__prompt_session.prompt(message=self.__prompt())
                if not user_input:
                    continue
            except KeyboardInterrupt:
                self._logger.warning("Keyboard interruption received.")

                if (
                    self.__target.os == "unix"
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
                        self.__target.os == "unix"
                        and self.__executor.os_helper.is_fifo_active()
                    ):
                        self.__executor.os_helper.fifo_execute(user_input)
                        continue

                    if result := self.__executor.remote_execute(command=user_input):
                        print(result)

                    continue

                command_parts = user_input[len(self.__prefix) :].strip().split()

                if not command_parts:
                    continue

                command = command_parts[0].lower()
                # Remaining parts as arguments
                args = command_parts[1:]

                if command in ["e", "ex", "exit"]:
                    self._logger.info("🛝 Sliding back up the toboggan.")
                    break

                if command in ["help", "h"]:
                    print(self.__get_help())
                    continue

                if action_details := self.__executor.action_manager.get_actions().get(
                    command
                ):
                    if action_class := self.__executor.action_manager.load_action_from_path(
                        action_details["path"]
                    ):

                        if issubclass(action_class, NamedPipe):
                            self.__executor.os_helper.start_named_pipe(
                                action_class, *args
                            )
                            continue

                        try:
                            action_output = action_class(self.__executor).run(*args)
                        except TypeError as exc:
                            self._logger.warning(
                                f"⚠️ Incorrect arguments for '{command}': {exc}"
                            )
                            continue
                        except Exception as exc:
                            self._logger.error(f"Action failed: {exc}")
                            continue

                        if action_output is not None:
                            print(action_output)

                        continue

                    self._logger.error(f"❌ Failed to load action '{command}'.")

    # Private methods

    def __get_help(self) -> str:
        """Generates a well-formatted help message for available actions."""
        actions = self.__executor.action_manager.get_actions()

        if not actions:
            return "❌ No available actions found."

        # Define ANSI colors for terminal output
        BOLD = "\033[1m"
        GREEN = "\033[92m"
        CYAN = "\033[96m"
        RESET = "\033[0m"

        # Determine max length for alignment
        max_action_length = max(len(action) for action in actions.keys()) + 2

        # Create header
        help_message = f"\n📌{BOLD}Available Actions:{RESET}\n"
        help_message += "-" * (max_action_length + 50) + "\n"

        # Sort actions alphabetically and format output
        for action, details in sorted(actions.items()):
            action_name = f"{GREEN}{action}{RESET}"
            try:
                description = details["description"]
            except KeyError:
                description = "No description available"

            # Align descriptions properly
            help_message += f"🔹 {action_name.ljust(max_action_length)} → {CYAN}{description}{RESET}\n"
            if details["parameters"]:
                param_list = ", ".join(details["parameters"])
                help_message += f"    ⚙️ Parameters: {param_list}\n"

        help_message += "-" * (max_action_length + 50) + "\n"
        help_message += f"{BOLD}Usage:{RESET} Type '!action_name' followed by parameters if required.\n"

        return help_message

    def __prompt(self) -> str:
        """Generates a dynamic shell prompt based on available target information."""

        if self.__target.os == "unix" and self.__executor.os_helper.is_fifo_active():
            return ""

        # Add user if available, otherwise use only hostname
        if self.__target.user and self.__target.hostname and self.__target.pwd:
            return f"({self.__target.user}@{self.__target.hostname})-[{self.__target.pwd}]$ "

        return "$ "
