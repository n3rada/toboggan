# toboggan/core/helpers/windows.py

# Built-in imports
import secrets
import random
import re

# External library imports
from loguru import logger

# Local application/library specific imports
from . import base


class WindowsHelper(base.OSHelperBase):
    """
    Windows-specific operations like handling binaries and shell paths.
    """

    def __init__(self, executor):
        super().__init__(executor)
        self.__shell_type = self.__detect_shell_type()
        logger.trace(f"Initialized WindowsHelper (shell: {self.__shell_type})")

    def get_hostname(self) -> str:
        return self._executor.remote_execute(command="hostname").strip()

    def get_current_user(self) -> str:
        return self._executor.remote_execute(command="whoami").strip()

    def get_current_path(self) -> str:
        """
        Get current working directory using shell-specific commands.
        Returns normalized Windows path.
        """
        if self.__shell_type == "powershell":
            commands = [
                "$pwd.Path",  # PowerShell automatic variable (most reliable)
                "(Get-Location).Path",  # PowerShell cmdlet
                "(Resolve-Path .).Path",  # Resolves any . or .. in the path
            ]
        else:  # cmd
            commands = [
                "cd",  # CMD builtin
                "echo %CD%",  # CMD environment variable
                "chdir",  # CMD alternative
            ]

        for command in commands:
            try:
                result = self._executor.remote_execute(command=command).strip()
                if result:
                    # Normalize path separators and remove any quotes
                    return result.replace("/", "\\").strip("\"'")
            except Exception as e:
                logger.debug(f"Path retrieval failed for '{command}': {e}")
                continue

        return ""

    def format_working_directory(self) -> str:
        """
        Generate a stealthy temp directory path for Windows.
        """
        # Define base directories and their corresponding naming patterns
        base_dirs = {
            "C:\\ProgramData": [
                "Mozilla",
                "Microsoft",
                "Google",
                "Adobe",
                "Chrome",
                "Edge",
            ],
            "C:\\Users\\Public": [
                "Libraries",
                "Documents",
                "Downloads",  # Common Windows folders
                "Pictures",
                "Videos",
                "Desktop",  # Standard user directories
            ],
        }

        directory = random.choice(list(base_dirs.keys()))
        prefix = random.choice(base_dirs[directory])

        # Generate a Mozilla-style GUID for ProgramData or a Windows-style GUID for Public
        if directory == "C:\\ProgramData":
            # Format: Mozilla-1de4eec8-1241-4177-a864-e594e8d1fb38
            guid = f"{secrets.token_hex(4)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(6)}"
            name = f"{prefix}-{guid}"
        else:
            # Format: Libraries-4627-4456-9876-5678ABCD
            guid = f"{secrets.token_hex(2)[:4]}-{secrets.token_hex(2)[:4]}-{secrets.token_hex(2)[:4]}-{secrets.token_hex(4)[:8]}".upper()
            name = f"{prefix}-{guid}"
        return f"{directory}\\{name}"

    def start_named_pipe(self, action_class, **kwargs) -> None:
        """Stub for Windows named pipe support. Not implemented yet."""
        raise NotImplementedError(
            "start_named_pipe is not implemented for WindowsHelper."
        )

    def is_shell_prompt_in(self, stdout_pathput: str) -> bool:
        """
        Detects if the command output appears to be a Windows shell prompt.

        Args:
            stdout_pathput (str): The latest command output to analyze.

        Returns:
            bool: True if the output appears to be a Windows shell prompt, False otherwise.
        """
        prompt_patterns = [
            r"PS [A-Z]:\\.*>",  # PowerShell default prompt
            r"[A-Z]:\\.*>",  # CMD default prompt
            r"PS.*>",  # Generic PowerShell prompt
        ]
        return any(re.search(pattern, stdout_pathput) for pattern in prompt_patterns)

    def __detect_shell_type(self) -> str:
        """
        Detects whether we're running in PowerShell or CMD.

        Returns:
            str: 'powershell' or 'cmd' depending on the shell type
        """
        # Try PowerShell-specific command first
        try:
            result = self._executor.remote_execute(
                command="$PSVersionTable.PSVersion.Major"
            ).strip()
            if result and result.isdigit():
                logger.info(f"Detected PowerShell (version {result})")
                return "powershell"
        except Exception:
            pass

        # Try CMD-specific environment variable
        try:
            result = self._executor.remote_execute(command="echo %CMDCMDLINE%").strip()
            if "cmd.exe" in result.lower():
                logger.info("Detected CMD")
                return "cmd"
        except Exception:
            pass

        # Additional check using command availability
        try:
            # Test a PowerShell-specific alias
            result = self._executor.remote_execute(command="Get-Alias ls").strip()
            if "Get-ChildItem" in result:
                logger.info("Detected PowerShell (alias test)")
                return "powershell"
        except Exception:
            pass

        # Default to CMD if we can't definitively detect PowerShell
        logger.warning("Shell type detection inconclusive, defaulting to CMD")
        return "cmd"

    # Properties
    @property
    def shell_type(self) -> str:
        return self.__shell_type
