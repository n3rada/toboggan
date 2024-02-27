# Built-in imports
from typing import TYPE_CHECKING
import sys

# Local library imports
from toboggan.src import operating_systems

# Type checking
if TYPE_CHECKING:
    from toboggan.src import executor


class Target:
    def __init__(self, command_executor: "executor.Executor" = None) -> None:
        if command_executor is None:
            raise ValueError(f"Executor should be defined.")
        self.__executor = command_executor

        if not self.__executor.is_alive():
            sys.exit(1)

        self.__os = self.__executor.os_guessing()

        if self.__os is None:
            raise ValueError("Impossible to determine remote OS.")

        print("[Toboggan] Sliding to the remote machine smoothly 🛝.")

        if self.__os == "unix":
            self.__executor.set_os(
                os_handler=operating_systems.UnixHandler(
                    execute_method=command_executor.execute
                )
            )
            self.__remote_wd = "/dev/shm"
            self.__shell = "/bin/bash"
        else:
            self.__executor.set_os(
                os_handler=operating_systems.WindowsHandler(
                    execute_method=command_executor.execute
                )
            )
            self.__remote_wd = "$env:TEMP"
            self.__shell = "powershell"

    # Public methods
    def upload(self, file_content: bytes, remote_path: str, chunk_size: int = None):
        self.__executor.upload_file(file_content, remote_path, chunk_size)

    def download(self, local_path: str, remote_path: str, chunk_size: int = None):
        self.__executor.download_file(
            local_path=local_path, remote_path=remote_path, chunk_size=chunk_size
        )

    def reverse_shell(
        self, ip_addr: str = None, port: int = 443, shell: str = None
    ) -> None:
        """
        Initiates a reverse shell connection to the specified IP address and port.

        Args:
            ip_addr (str): The IP address of the machine to connect back to.
                        This is typically the address of the machine running the listener.
            port (int, optional): The port number on which the listening machine is waiting for
                                incoming connections. Defaults to 443.
            shell (str, optional): Specifies the type of shell to be used for the reverse connection.
                                If not provided, the default shell will be used.
        """
        self.__executor.reverse_shell(ip_addr, port, shell or self.__shell)

    # Dunders
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Target):
            return NotImplemented
        return hash(self) == hash(other)

    def __hash__(self) -> int:
        return hash((self.__os, self.user, self.hostname, self.system_info))

    # Private methods

    # Properties
    @property
    def executor(self) -> "executor.Executor":
        return self.__executor

    @property
    def os(self) -> str:
        return self.__os

    @property
    def user(self) -> str:
        return self.__executor.user

    @property
    def hostname(self) -> str:
        return self.__executor.hostname

    @property
    def pwd(self) -> str:
        return self.__executor.pwd

    @property
    def system_info(self) -> str:
        return self.__executor.system_info

    @property
    def architecture(self) -> str:
        """Deducing architecture from system information

        Returns:
            str: Either 64-bit or 32-bit
        """
        # Deducing the architecture from system information
        if "64" in self.system_info:
            return "64-bit"

        return "32-bit"

    @property
    def remote_working_directory(self) -> str:
        return self.__remote_wd
