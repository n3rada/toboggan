class Target:
    def __init__(
        self,
        os: str,
        user: str = None,
        hostname: str = None,
        pwd: str = None,
        system_info: str = None,
    ):
        self.os = os

        if ["whoami:", "not found", "introuvable"] in user.lower():
            user = None
        else:
            self.user = user

        if ["hostname:", "not found", "introuvable"] in hostname.lower():
            hostname = None
        else:
            self.hostname = hostname

        self.pwd = pwd
        self._system_info = system_info
        self._architecture = None

        if system_info:
            self._update_architecture()

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
