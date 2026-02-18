# toboggan/core/terminal.py

# Built-in imports
import shlex
import os
import re
from pathlib import Path
import tempfile
from typing import Iterable

# External library imports
from loguru import logger

from modwrap import ModuleWrapper

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import ThreadedAutoSuggest, AutoSuggestFromHistory
from prompt_toolkit.history import ThreadedHistory, InMemoryHistory, FileHistory
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

# Local library imports
from .utils import logbook
from .executor import Executor
from .action import NamedPipe


class TerminalCompleter(Completer):
    """Completer for terminal commands and actions."""

    def __init__(self, prefix: str, executor: Executor):
        self._prefix = prefix
        self._executor = executor

        # Built-in commands with descriptions (including aliases)
        self._builtins = {
            "exit": "Exit the terminal",
            "e": "Exit the terminal (alias)",
            "ex": "Exit the terminal (alias)",
            "help": "Show help message",
            "h": "Show help message (alias)",
            "size": "Probe or manually set the max command size",
            "cmdsize": "Probe or manually set the max command size (alias)",
            "debug": "Toggle debug mode on/off",
            "trace": "Toggle trace mode on/off",
            "paths": "Show custom paths and command location cache",
        }

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterable[Completion]:
        text = document.text_before_cursor

        # If text is empty or doesn't start with prefix, no completions
        if not text or not text.startswith(self._prefix):
            return

        # Remove prefix for processing
        text = text[len(self._prefix) :].lstrip()

        # Get all available actions
        available_actions = self._executor.action_manager.get_actions()

        # If no text entered yet, suggest all commands and actions
        if not text:
            # Suggest built-in commands
            for cmd, desc in self._builtins.items():
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
        for cmd, desc in self._builtins.items():
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
            # Create .toboggan directory in user's home for persistent history
            self.__history_dir = Path.home() / ".toboggan"
            self.__history_dir.mkdir(exist_ok=True)

            # Create unique history file using hostname
            self.__history_file = (
                self.__history_dir / f"{executor.target.hostname}_history"
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
            logger.info(f"💾 Persistent command history: {self.__history_file}")

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
            completer=TerminalCompleter(prefix, executor),
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
    def start(self) -> int:
        """Start the interactive terminal session.

        Runs the main command loop, handling user input, executing commands,
        and dispatching to appropriate handlers (built-in commands, actions, or remote execution).
        Continues until the user exits or an unrecoverable error occurs.

        Returns:
            int: Exit code (0 for normal exit or EOF/Control-D, 130 for SIGINT/Control-C)
        """
        result = None
        user_input = ""

        logger.info(
            f"🔧 Prefix set to '{self.__prefix}' — use '{self.__prefix}h' for available commands."
        )

        try:
            while True:
                try:
                    user_input = self.__prompt_session.prompt(message=self.__prompt())
                    if not user_input:
                        continue
                except EOFError:
                    # Control-D pressed - normal exit
                    self._exit()
                    return 0
                except KeyboardInterrupt:
                    # Control-C pressed - check if buffer has text first
                    if self.__prompt_session.app.current_buffer.text:
                        continue

                    if self._exit():
                        return 130  # SIGINT exit code

                    continue

                except Exception as exc:
                    logger.warning(f"Exception occurred: {exc}")
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
                            if result := self.__executor.remote_execute(
                                command=user_input
                            ):
                                print(result)

                            continue
                        except KeyboardInterrupt:
                            print("\r", end="", flush=True)  # Clear the ^C
                            logger.warning(
                                "Keyboard interruption received during remote command execution."
                            )
                            continue
                        except Exception as exc:
                            logger.error(f"❌ Command execution failed: {exc}")
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
                            return 0

                        continue

                    if command in ["help", "h"]:
                        print(self.__get_help())
                        continue

                    raw_args = command_parts[1:]

                    if command == "size" or command == "cmdsize":
                        try:
                            if raw_args:
                                self.__executor.command_max_size = int(raw_args[0])
                            else:
                                self.__executor.command_max_size = (
                                    self.__executor.calculate_max_command_size()
                                )
                        except ValueError as e:
                            logger.error(f"❌ Invalid command size: {e}")
                        except Exception as e:
                            logger.error(f"❌ Failed to set command size: {e}")

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
                        try:
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
                        except Exception as e:
                            logger.error(f"❌ Paths command failed: {e}")

                        continue

                    try:
                        actions_dict = self.__executor.action_manager.get_actions()
                    except Exception as e:
                        logger.error(f"❌ Failed to get actions: {e}")
                        continue

                    # Check if action exists in the file system but failed to load
                    if command not in actions_dict:
                        # Try to detect if the action file exists but had loading issues
                        try:
                            action_manager = self.__executor.action_manager
                            expected_path = action_manager._action_directory / command

                            if expected_path.exists() and expected_path.is_dir():
                                # Action directory exists but didn't load - likely syntax/import error
                                logger.error(
                                    f"❌ Action '{command}' exists but failed to load. "
                                    "Check for syntax errors or missing dependencies."
                                )
                            else:
                                # Truly unknown command
                                logger.error(
                                    f"❌ Unknown command: '{command}'. Type '!help' to see available commands."
                                )
                        except Exception as e:
                            logger.error(
                                f"❌ Unknown command: '{command}'. Type '!help' to see available commands."
                            )

                        continue

                    if targeted_action := actions_dict.get(command):
                        try:
                            action_class = (
                                self.__executor.action_manager.load_action_from_path(
                                    targeted_action["path"]
                                )
                            )

                            if not action_class:
                                # Action exists in dict but failed to load from path
                                logger.error(
                                    f"❌ Action '{command}' failed to load. Check for syntax errors or missing dependencies."
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
                                    # Convert hyphens to underscores for Python parameter names
                                    key = key.replace("-", "_")
                                    keyword_args[key] = value
                                    i += 1
                                    continue

                                # Handle --key value
                                if arg.startswith("--"):
                                    key = arg[2:]
                                    # Convert hyphens to underscores for Python parameter names
                                    key = key.replace("-", "_")

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

                                # Handle -h (short flag for help)
                                if arg == "-h":
                                    keyword_args["h"] = True
                                    i += 1
                                    continue

                                # Handle positional argument
                                positional_args.append(arg)
                                i += 1

                            # Filter out 'executor' from keyword_args - it's injected automatically
                            if "executor" in keyword_args:
                                logger.warning(
                                    "⚠️ Ignoring '--executor' parameter (automatically provided)"
                                )
                                keyword_args.pop("executor")

                            # Check for help flag
                            if keyword_args.get("help") or keyword_args.get("h"):
                                print(self.__get_action_help(command, action_class))
                                continue

                            if raw_args:
                                logger.debug(
                                    f"▶️ Running '{command}' with args: {raw_args}"
                                )
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

                        except Exception as exc:
                            logger.error(
                                f"❌ Failed to execute action '{command}': {exc}"
                            )
                            continue

        except Exception as exc:
            logger.exception(f"💥 Unhandled exception in terminal: {exc}")
            return 1

        # This should never be reached due to while True loop
        return 0

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
            f"🔹 {ansi_ljust(f'{GREEN}help{RESET} ({DIM}h{RESET})', max_action_length)} → "
            f"{CYAN}Show this help message.{RESET}"
        )
        lines.append(
            f"🔹 {ansi_ljust(f'{GREEN}exit{RESET} ({DIM}e, ex{RESET})', max_action_length)} → "
            f"{CYAN}Exit the toboggan shell session.{RESET}"
        )
        lines.append(
            f"🔹 {ansi_ljust(f'{GREEN}size{RESET}', max_action_length)} → "
            f"{CYAN}Probe or manually set the max command size.{RESET}"
        )
        lines.append(f"    ⚙️ Parameters: [bytes] (optional, must be multiple of 1024)")
        lines.append(
            f"🔹 {ansi_ljust(f'{GREEN}debug{RESET}', max_action_length)} → "
            f"{CYAN}Toggle debug logging on/off.{RESET}"
        )
        lines.append(
            f"🔹 {ansi_ljust(f'{GREEN}trace{RESET}', max_action_length)} → "
            f"{CYAN}Toggle trace logging on/off.{RESET}"
        )
        lines.append(
            f"🔹 {ansi_ljust(f'{GREEN}paths{RESET}', max_action_length)} → "
            f"{CYAN}Show custom paths and command location cache.{RESET}"
        )
        lines.append(f"    ⚙️ Subcommands: add <paths>, clear")

        return "\n".join(lines)

    def __get_action_help(self, action_name: str, action_class) -> str:
        """Generate detailed help for a specific action.

        Args:
            action_name: Name of the action
            action_class: The action class

        Returns:
            str: Formatted help text with parameters, types, defaults, and description.
        """
        # ANSI styles
        BOLD = "\033[1m"
        GREEN = "\033[92m"
        CYAN = "\033[96m"
        YELLOW = "\033[93m"
        DIM = "\033[2m"
        RESET = "\033[0m"

        lines = []
        lines.append(f"\n{BOLD}{GREEN}Action:{RESET} {action_name}")
        lines.append(DIM + "-" * 70 + RESET)

        # Get description
        description = getattr(action_class, "DESCRIPTION", None)
        if description:
            lines.append(f"{BOLD}Description:{RESET}")
            lines.append(f"  {CYAN}{description}{RESET}")
            lines.append("")

        # Get the action info from action manager
        actions_dict = self.__executor.action_manager.get_actions()
        action_info = actions_dict.get(action_name)

        if not action_info:
            lines.append(f"{YELLOW}⚠️  Could not retrieve action information{RESET}")
            lines.append("")
            lines.append(f"{BOLD}Usage:{RESET}")
            lines.append(
                f"  {GREEN}!{action_name}{RESET} {DIM}[--param value ..]{RESET}"
            )
            lines.append(DIM + "-" * 70 + RESET)
            return "\n".join(lines)

        # Try to get detailed signature using modwrap
        try:
            action_path = action_info["path"]
            wrapper = ModuleWrapper(action_path)

            logger.trace(repr(wrapper))

            # Determine which method to get signature from
            class_name = action_class.__name__
            if issubclass(action_class, NamedPipe):
                method_path = f"{class_name}.__init__"
            else:
                method_path = f"{class_name}.run"

            # Get detailed signature with types and defaults
            signature = wrapper.get_signature(method_path)

            if signature:
                lines.append(f"{BOLD}Parameters:{RESET}")

                has_params = False
                for param_name, param_info in signature.items():
                    # Skip 'executor' parameter - it's injected automatically
                    if param_name == "executor":
                        continue

                    has_params = True
                    # Convert underscores to hyphens for CLI convention
                    cli_param_name = param_name.replace("_", "-")
                    param_type = param_info.get("type", "Any")
                    default_value = param_info.get("default")

                    if default_value is None and "default" not in param_info:
                        # Required parameter (no default key means required)
                        status = f"{GREEN}[required]{RESET}"
                        lines.append(
                            f"  {YELLOW}--{cli_param_name}{RESET} {DIM}({param_type}){RESET} {status}"
                        )
                    else:
                        # Optional parameter with default
                        lines.append(
                            f"  {YELLOW}--{cli_param_name}{RESET} {DIM}({param_type}){RESET} "
                            f"{DIM}[default: {default_value}]{RESET}"
                        )

                if not has_params:
                    lines.append(f"{DIM}  No parameters required{RESET}")

                lines.append("")
            else:
                lines.append(f"{DIM}  No parameters required{RESET}")
                lines.append("")

            # Get docstring
            try:
                docstring = wrapper.get_doc(method_path)

                if docstring:
                    lines.append(f"{BOLD}Details:{RESET}")
                    # Indent each line of the docstring
                    for line in docstring.split("\n"):
                        if line.strip():
                            lines.append(f"  {DIM}{line.strip()}{RESET}")
                    lines.append("")
            except Exception as e:
                logger.debug(f"Could not extract docstring for {action_name}: {e}")

        except Exception as e:
            logger.debug(f"Could not use modwrap for {action_name}: {e}")

            # Fallback to basic parameter list from action_info
            parameters = action_info.get("parameters", [])

            if parameters:
                lines.append(f"{BOLD}Parameters:{RESET}")

                has_params = False
                for param_str in parameters:
                    # Parse parameter string format: "name (default)" or "name"
                    if "(" in param_str and param_str.endswith(")"):
                        # Has default value
                        param_name = param_str[: param_str.index("(")].strip()

                        # Skip 'executor' parameter
                        if param_name == "executor":
                            continue

                        has_params = True
                        # Convert underscores to hyphens for CLI convention
                        cli_param_name = param_name.replace("_", "-")
                        default_value = param_str[param_str.index("(") + 1 : -1].strip()

                        lines.append(
                            f"  {YELLOW}--{cli_param_name}{RESET} {DIM}[default: {default_value}]{RESET}"
                        )
                    else:
                        # Required parameter (no default)
                        param_name = param_str.strip()

                        # Skip 'executor' parameter
                        if param_name == "executor":
                            continue

                        has_params = True
                        # Convert underscores to hyphens for CLI convention
                        cli_param_name = param_name.replace("_", "-")
                        status = f"{GREEN}[required]{RESET}"
                        lines.append(f"  {YELLOW}--{cli_param_name}{RESET} {status}")

                if not has_params:
                    lines.append(f"{DIM}  No parameters required{RESET}")

                lines.append("")
            else:
                lines.append(f"{DIM}  No parameters required{RESET}")
                lines.append("")

        # Usage example
        lines.append(f"{BOLD}Usage:{RESET}")
        lines.append(f"  {GREEN}!{action_name}{RESET} {DIM}[--param value ..]{RESET}")
        lines.append(DIM + "-" * 70 + RESET)

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
