# Built-in imports
import shlex
import os
import re
from pathlib import Path
import tempfile
from typing import Iterable

# External library imports
from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import ThreadedAutoSuggest, AutoSuggestFromHistory
from prompt_toolkit.history import ThreadedHistory, InMemoryHistory, FileHistory
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

# Local library imports
from toboggan.src.utils import logbook
from toboggan.src.executor import Executor
from toboggan.src.action import NamedPipe


class TobogganCompleter(Completer):
    """Completer for Toboggan terminal commands and actions."""

    def __init__(self, prefix: str, executor: Executor):
        self.prefix = prefix
        self.executor = executor

        # Built-in commands with descriptions
        self.builtins = {
            "exit": "Exit the terminal",
            "help": "Show help message",
            "chunksize": "Probe or manually set the max command size",
            "debug": "Toggle debug mode on/off",
            "trace": "Toggle trace mode on/off",
            "paths": "Show custom paths and command location cache",
        }

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterable[Completion]:
        text = document.text_before_cursor

        # If text is empty or doesn't start with prefix, no completions
        if not text or not text.startswith(self.prefix):
            return

        # Remove prefix for processing
        text = text[len(self.prefix) :].lstrip()

        # Get all available actions
        available_actions = self.executor.action_manager.get_actions()

        # If no text entered yet, suggest all commands and actions
        if not text:
            # Suggest built-in commands
            for cmd, desc in self.builtins.items():
                yield Completion(cmd, start_position=0, display_meta=desc)

            # Suggest available actions
            for action_name, action_info in available_actions.items():
                yield Completion(
                    action_name,
                    start_position=0,
                    display_meta=action_info.get(
                        "description", "No description available"
                    ),
                )
            return

        # If text entered, filter suggestions
        for cmd, desc in self.builtins.items():
            if cmd.startswith(text):
                yield Completion(cmd[len(text) :], display_meta=desc)

        for action_name, action_info in available_actions.items():
            if action_name.startswith(text):
                yield Completion(
                    action_name[len(text) :],
                    display_meta=action_info.get(
                        "description", "No description available"
                    ),
                )


class Terminal:
    """Interactive terminal interface for executing commands on a remote target.

    Provides a prompt-based interface with command history, auto-completion,
    and support for both regular command execution and FIFO-based sessions.
    """

    def __init__(
        self,
        executor: Executor,
        prefix="!",
        history: bool = False,
        log_level: str = "INFO",
    ):
        """Initialize the Terminal instance.

        Args:
            executor: The Executor instance for running remote commands.
            prefix: Command prefix for built-in actions (default: '!').
            history: Whether to enable persistent command history (default: False).
            log_level: Initial logging level (default: 'INFO').
        """
        if history:
            # Create temp directory for history files
            self.__temp_dir = Path(tempfile.gettempdir()) / "toboggan"
            self.__temp_dir.mkdir(exist_ok=True)

            # Create unique history file using hostname
            self.__history_file = (
                self.__temp_dir / f"{executor.target.hostname}_history"
            )

            # Create the history file first if it doesn't exist
            self.__history_file.touch(exist_ok=True)

            # Set permissions to 0600 (rw-------)
            try:
                os.chmod(self.__history_file, 0o600)
            except PermissionError as e:
                logger.warning(
                    f"⚠️ Could not set secure permissions on history file: {e}"
                )

            history_backend = ThreadedHistory(FileHistory(str(self.__history_file)))
            logger.info("💾 Persistent command history enabled.")

        else:
            history_backend = ThreadedHistory(InMemoryHistory())  # in-memory history
            logger.debug("🗑️ In-memory command history enabled.")

        # Create prompt session with completer
        self.__prompt_session = PromptSession(
            cursor=CursorShape.BLINKING_BEAM,
            multiline=False,
            enable_history_search=True,
            wrap_lines=True,
            auto_suggest=ThreadedAutoSuggest(auto_suggest=AutoSuggestFromHistory()),
            history=history_backend,
            completer=TobogganCompleter(prefix, executor),
        )

        self.__target = executor.target
        self.__executor = executor
        self.__prefix = prefix

        self.__log_level = log_level

    # Private Methods
    def _exit(self) -> bool:
        """Clean up and exit the terminal session.

        Stops any active FIFO sessions and deletes the remote working directory.

        Returns:
            bool: True if terminal should exit completely, False if it should continue.
        """
        logger.info("🛝 Sliding back up the toboggan")

        if self.__target.os == "linux" and self.__executor.os_helper.is_fifo_active():
            self.__executor.os_helper.stop_named_pipe()
            return False

        self.__executor.delete_working_directory()
        return True

    # Public Methods
    def start(self) -> None:
        """Start the interactive terminal session.

        Runs the main command loop, handling user input, executing commands,
        and dispatching to appropriate handlers (built-in commands, actions, or remote execution).
        Continues until the user exits or an unrecoverable error occurs.
        """
        result = None
        user_input = ""

        logger.info(
            f"🔧 Prefix set to '{self.__prefix}' — use '{self.__prefix}h' for available commands."
        )

        while True:
            try:
                user_input = self.__prompt_session.prompt(message=self.__prompt())
                if not user_input:
                    continue
            except EOFError:
                # Control-D pressed
                self._exit()
                break
            except KeyboardInterrupt:
                if self.__prompt_session.app.current_buffer.text:
                    continue

                if self._exit():
                    break

                continue

            except Exception as exc:
                logger.warning(f"Exception occured: {exc}")
                continue
            else:
                if not user_input.startswith(self.__prefix):
                    if (
                        self.__target.os == "linux"
                        and self.__executor.os_helper.is_fifo_active()
                    ):
                        self.__executor.os_helper.fifo_execute(user_input)
                        continue

                    try:
                        if result := self.__executor.remote_execute(command=user_input):
                            print(result)

                        continue
                    except KeyboardInterrupt:
                        print("\r", end="", flush=True)  # Clear the ^C
                        logger.warning(
                            "Keyboard interruption received during remote command execution."
                        )
                        continue

                try:
                    command_parts = shlex.split(
                        user_input[len(self.__prefix) :].strip()
                    )
                except ValueError as e:
                    logger.error(f"❌ Command parsing failed: {e}")
                    continue

                if not command_parts:
                    continue

                command = command_parts[0].lower().replace("-", "_")

                if command in ["e", "ex", "exit"]:
                    if self._exit():
                        break

                    continue

                if command in ["help", "h"]:
                    print(self.__get_help())
                    continue

                raw_args = command_parts[1:]

                if command == "chunksize" or command == "chunk_size":
                    if raw_args:
                        self.__executor.chunk_max_size = int(raw_args[0])
                    else:
                        self.__executor.chunk_max_size = (
                            self.__executor.calculate_max_chunk_size()
                        )

                    continue

                if command == "debug":
                    # Toggle debug mode
                    if self.__log_level == "DEBUG":
                        self.__log_level = "INFO"
                        logbook.setup_logging(self.__log_level)
                        logger.info("🔇 Debug mode disabled")
                    else:
                        self.__log_level = "DEBUG"
                        logbook.setup_logging(self.__log_level)
                        logger.info("🔊 Debug mode enabled")

                    continue

                if command == "trace":
                    # Toggle trace mode
                    if self.__log_level == "TRACE":
                        self.__log_level = "INFO"
                        logbook.setup_logging(self.__log_level)
                        logger.info("🔇 Trace mode disabled")
                    else:
                        self.__log_level = "TRACE"
                        logbook.setup_logging(self.__log_level)
                        logger.info("🔊 Trace mode enabled")

                    continue

                if command == "paths":
                    # Handle paths subcommands
                    if raw_args and raw_args[0] in ["add", "a"]:
                        # Add new paths
                        if len(raw_args) > 1:
                            self.__handle_paths_add(raw_args[1:])
                        else:
                            logger.error(
                                "❌ No paths provided. Usage: !paths add /path1 /path2 or !paths add /path1:/path2"
                            )
                    elif raw_args and raw_args[0] in ["clear", "c"]:
                        # Clear cache
                        self.__handle_paths_clear()
                    else:
                        # Show paths info
                        print(self.__get_paths_info())
                    continue

                actions_dict = self.__executor.action_manager.get_actions()

                if targeted_action := actions_dict.get(command):
                    if action_class := self.__executor.action_manager.load_action_from_path(
                        targeted_action["path"]
                    ):

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
                            logger.debug(f"▶️ Running '{command}' with args: {raw_args}")
                        else:
                            logger.debug(f"▶️ Running '{command}'")

                        try:
                            if issubclass(action_class, NamedPipe):
                                self.__executor.os_helper.start_named_pipe(
                                    action_class=action_class, **keyword_args
                                )
                                continue

                            action = action_class(self.__executor)

                            if positional_args or keyword_args:
                                action_output = action.run(
                                    *positional_args, **keyword_args
                                )
                            else:
                                action_output = action.run()

                        except TypeError as exc:
                            logger.warning(
                                f"⚠️ Incorrect arguments for '{command}': {exc}"
                            )
                            continue
                        except Exception as exc:
                            logger.error(f"❌ Action '{command}' failed: {exc}")
                            continue

                        if action_output is not None:
                            print(action_output)

                        continue

                logger.error(
                    f"❌ Unknown command: '{command}'. Type '!help' to see available commands."
                )

    # Private methods

    def __get_help(self) -> str:
        """Generate a formatted help message listing available actions and built-in commands.

        Returns:
            str: Formatted help text with action names, descriptions, and parameters.
        """
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

    def __get_paths_info(self) -> str:
        """Generate formatted information about custom paths and command location cache.

        Returns:
            str: Formatted text showing custom paths and cached command locations.
        """
        # ANSI styles
        BOLD = "\033[1m"
        GREEN = "\033[92m"
        CYAN = "\033[96m"
        YELLOW = "\033[93m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        lines = []
        lines.append(f"\n{BOLD}📂 Custom Command Paths Configuration{RESET}")
        lines.append(DIM + "-" * 70 + RESET)

        # Check if OS helper has custom paths (Linux only)
        if self.__target.os == "linux":
            os_helper = self.__executor.os_helper
            custom_paths = getattr(os_helper, "_LinuxHelper__custom_paths", [])

            if custom_paths:
                lines.append(f"{GREEN}✓{RESET} Custom paths are configured:")
                for i, path in enumerate(custom_paths, 1):
                    lines.append(f"  {i}. {CYAN}{path}{RESET}")
            else:
                lines.append(
                    f"{YELLOW}ℹ{RESET} No custom paths configured (using standard detection methods)"
                )

            lines.append("")
            lines.append(f"{BOLD}💾 Command Location Cache{RESET}")
            lines.append(DIM + "-" * 70 + RESET)

            # Get the cache
            cache = os_helper.command_location_cache

            if cache:
                lines.append(
                    f"{GREEN}✓{RESET} Cached command locations ({len(cache)} entries):"
                )
                lines.append("")

                # Find longest command name for alignment
                max_cmd_length = max(len(cmd) for cmd in cache.keys()) if cache else 0

                for command, location in sorted(cache.items()):
                    if location:
                        lines.append(
                            f"  {CYAN}{command.ljust(max_cmd_length)}{RESET} → {GREEN}{location}{RESET}"
                        )
                    else:
                        lines.append(
                            f"  {CYAN}{command.ljust(max_cmd_length)}{RESET} → {DIM}(not found){RESET}"
                        )
            else:
                lines.append(f"{YELLOW}ℹ{RESET} No commands cached yet")

            lines.append("")
            lines.append(f"{DIM}Usage: !paths [add <paths>] [clear]{RESET}")
            lines.append(
                f"{DIM}  - !paths add /opt/bin /usr/local/bin   # Add space-separated paths{RESET}"
            )
            lines.append(
                f"{DIM}  - !paths add /opt/bin:/usr/local/bin  # Add colon-separated paths{RESET}"
            )
            lines.append(
                f"{DIM}  - !paths clear                        # Clear command cache{RESET}"
            )
        else:
            lines.append(
                f"{YELLOW}ℹ{RESET} Custom paths feature is only available for Linux targets"
            )

        lines.append(DIM + "-" * 70 + RESET)

        return "\n".join(lines)

    def __handle_paths_add(self, path_args: list) -> None:
        """Add new custom paths to the LinuxHelper configuration.

        Args:
            path_args: List of paths to add (can include colon-separated strings)
        """
        if self.__target.os != "linux":
            logger.error("❌ Custom paths feature is only available for Linux targets")
            return

        os_helper = self.__executor.os_helper
        custom_paths = getattr(os_helper, "_LinuxHelper__custom_paths", [])

        new_paths = []
        for arg in path_args:
            # Support both space-separated and colon-separated paths
            if ":" in arg:
                new_paths.extend([p.strip() for p in arg.split(":") if p.strip()])
            else:
                new_paths.append(arg.strip())

        # Remove duplicates while preserving order
        added_count = 0
        for path in new_paths:
            if path not in custom_paths:
                custom_paths.append(path)
                added_count += 1
                logger.success(f"✅ Added custom path: {path}")
            else:
                logger.info(f"ℹ️  Path already exists: {path}")

        # Update the LinuxHelper's custom paths
        setattr(os_helper, "_LinuxHelper__custom_paths", custom_paths)

        if added_count > 0:
            logger.success(f"📂 Added {added_count} new custom path(s)")
        else:
            logger.info("ℹ️  No new paths were added")

    def __handle_paths_clear(self) -> None:
        """Clear the command location cache."""
        if self.__target.os != "linux":
            logger.error("❌ Custom paths feature is only available for Linux targets")
            return

        os_helper = self.__executor.os_helper
        cache = os_helper.command_location_cache
        cache_size = len(cache)

        if cache_size > 0:
            os_helper.clear_command_cache()
            logger.success(f"🗑️  Cleared {cache_size} cached command location(s)")
        else:
            logger.info("ℹ️  Command cache is already empty")

    def __prompt(self) -> str:
        """Generate a dynamic shell prompt based on available target information.

        Creates a context-aware prompt showing user, hostname, and current directory
        when available. Returns empty string when in FIFO mode.

        Returns:
            str: The formatted prompt string (e.g., '(user@host)-[/path]$ ').
        """
        if self.__target.os == "linux" and self.__executor.os_helper.is_fifo_active():
            return ""

        user = self.__target.user
        host = self.__target.hostname
        pwd = self.__target.pwd

        # Build prompt with available information
        if user and host and pwd:
            return f"({user}@{host})-[{pwd}]$ "

        if user and host:
            return f"{user}@{host}:~$ "

        if host and pwd:
            return f"{host}:{pwd}$ "

        if user and pwd:
            return f"{user}:{pwd}$ "

        if pwd:
            return f"{pwd}$ "

        if user:
            return f"{user}@localhost:~$ "

        if host:
            return f"{host}:~$ "

        return "$ "
