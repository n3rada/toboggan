

class Target:
    def __init__(self, os: str, user: str = None, hostname: str = None, pwd: str = None, system_info: str = None):
        self.os = os
        self.user = user
        self.hostname = hostname
        self.pwd = pwd
        self._system_info = system_info
        self._architecture = None

        if system_info:
            self._update_architecture()


    def _update_architecture(self):
        """Deduces architecture from system information."""
        if self._system_info and "64" in self._system_info:
            self._architecture = "64-bit"
        else:
            self._architecture = "32-bit"

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

