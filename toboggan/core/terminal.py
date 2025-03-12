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
        self.__logger = logbook.get_logger()

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

        # For named pipe
        self.__named_pipe_instance = None
        self.tty = False

    # Public methods
    def start_named_pipe(
        self,
        action_class,
        read_interval: float = 0.4,
        command_in: str = None,
        command_out: str = None,
    ):
        """
        Initializes and starts a named pipe (FIFO) action.

        Args:
            action_class (type): The class representing the named pipe action.
            read_interval (float, optional): Interval for reading output. Defaults to 0.4s.
            session_identifier (str, optional): Unique identifier for the session.
            command_in (str, optional): Path for input pipe.
            command_out (str, optional): Path for output pipe.
        """

        if not issubclass(action_class, NamedPipe):
            self.__logger.error(
                f"❌ {action_class.__name__} is not a valid NamedPipe action."
            )
            return

        self.__logger.info(
            f"🎭 Initializing named pipe action: {action_class.__name__}"
        )

        try:
            # Create an instance of the NamedPipe action with the provided parameters
            self.__named_pipe_instance = action_class(
                executor=self.__executor,
                read_interval=float(read_interval),
                command_in=command_in,
                command_out=command_out,
            )

            # Setup and start the named pipe
            self.__named_pipe_instance.setup()
            self.__named_pipe_instance.run()

            self.__logger.success(
                f"✅ Named pipe {action_class.__name__} started successfully!"
            )

        except Exception as e:
            self.__logger.error(
                f"⚠️ Failed to start named pipe action '{action_class.__name__}': {e}"
            )
            self.__named_pipe_instance = None  # Ensure cleanup in case of failure

    def start(self) -> None:
        result = None
        user_input = ""

        self.__logger.info(f"Terminal prefix is: {self.__prefix}")

        while True:
            try:
                user_input = self.__prompt_session.prompt(message=self.__prompt())
                if not user_input:
                    continue
            except KeyboardInterrupt:
                self.__logger.warning("Keyboard interruption received.")
                if self.__named_pipe_instance:
                    self.__named_pipe_instance.stop()

                self.__logger.info(
                    f"🗑️ Deleting remote working directory: {self.__executor.working_directory}"
                )
                try:
                    self.__executor.remote_execute(
                        f"rm -rf {self.__executor.working_directory}"
                    )
                except Exception as exc:
                    self.__logger.warning(
                        f"⚠️ Failed to delete remote working directory: {exc}"
                    )

                break
            except Exception as exc:
                self.__logger.warning(f"Exception occured: {exc}")
                continue
            else:
                if not user_input.startswith(self.__prefix):

                    if self.__named_pipe_instance is not None:
                        self.__named_pipe_instance.execute(user_input)
                        continue

                    if result := self.__executor.remote_execute(command=user_input):
                        print(result)

                    continue

                command_parts = user_input[len(self.__prefix) :].strip().split()

                if not command_parts:
                    continue

                command = command_parts[0].lower()
                args = command_parts[1:]  # Remaining parts as arguments

                if command in ["e", "ex", "exit"]:
                    self.__logger.info("🛝 Sliding back up the toboggan.")

                    if self.__named_pipe_instance is not None:
                        self.__named_pipe_instance.stop()
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
                            self.start_named_pipe(action_class, *args)
                            continue

                        try:
                            action_output = action_class(self.__executor).run(*args)
                        except TypeError as exc:
                            self.__logger.warning(
                                f"⚠️ Incorrect arguments for '{command}': {exc}"
                            )
                            continue
                        except Exception as exc:
                            self.__logger.error(f"Action failed: {exc}")
                            continue

                        if action_output is not None:
                            print(action_output)

                        continue

                    self.__logger.error(f"❌ Failed to load action '{command}'.")

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

        if self.__named_pipe_instance:
            return ""

        # Add user if available, otherwise use only hostname
        if self.__target.user and self.__target.hostname and self.__target.pwd:
            return f"({self.__target.user}@{self.__target.hostname})-[{self.__target.pwd}]$ "

        return "$ "
