from toboggan.core.helpers import base


class WindowsHelper(base.OSHelperBase):
    """
    Windows-specific operations like handling binaries and shell paths.
    """

    def __init__(self, executor):
        super().__init__(executor)

    def get_current_path(self) -> str:
        return self._executor.remote_execute(command="(Get-Location).Path").strip()

    def create_working_directory_string(self) -> str:
        """Generate a temp directory path."""
        return ".\\Windows-error\\"

    # Properties
