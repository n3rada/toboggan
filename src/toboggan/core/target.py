# toboggan/core/target.py


class Target:
    """Represents information about a remote target system.

    This class stores and manages information about the remote system being accessed,
    including OS type, user, hostname, working directory, and system architecture.
    """

    # Constructor
    def __init__(
        self,
        os: str,
        user: str = None,
        hostname: str = None,
        pwd: str = None,
        system_info: str = None,
    ):
        """Initialize a Target instance with system information.

        Args:
            os: The operating system type ('linux' or 'windows').
            user: The username on the remote system. Set to None if retrieval failed
                  (detected by error keywords like 'not found').
            hostname: The hostname of the remote system. Set to None if retrieval failed.
            pwd: The present working directory on the remote system.
            system_info: System information string (e.g., from 'uname -a') used to
                        deduce the architecture.
        """
        self.os = os

        if user and any(
            err in user.lower() for err in ["whoami:", "not found", "introuvable"]
        ):
            self.user = None
        else:
            self.user = user

        if hostname and any(
            err in hostname.lower() for err in ["hostname:", "not found", "introuvable"]
        ):
            self.hostname = None
        else:
            self.hostname = hostname

        self.pwd = pwd
        self._system_info = system_info
        self._architecture = None

        if system_info:
            self._update_architecture()

    # Properties
    @property
    def system_info(self) -> str | None:
        return self._system_info

    @system_info.setter
    def system_info(self, value: str | None):
        """Setter for system_info, updates architecture."""
        self._system_info = value
        self._update_architecture()

    @property
    def architecture(self) -> str | None:
        return self._architecture

    # Public methods

    # Protected methods
    def _update_architecture(self):
        """Deduces architecture from system information."""
        if not self._system_info:
            self._architecture = None
            return

        info = self._system_info.lower()

        if "aarch64" in info or "arm64" in info:
            self._architecture = "aarch64"
        elif "x86_64" in info or "amd64" in info or "64" in info:
            self._architecture = "x86_64"
        elif "i386" in info or "i686" in info or "x86" in info:
            self._architecture = "x86"
        else:
            self._architecture = None  # Unknown


