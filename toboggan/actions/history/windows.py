# Local application/library specific imports
from toboggan.core.action import BaseAction


class HistoryAction(BaseAction):
    DESCRIPTION = "Retrieve all users' shell command history"

    def run(self) -> str:
        """
        Retrieves command history for all users based on shell type.
        PowerShell: PSReadline history files
        CMD: doskey history and command prompt history files
        """
        if self._os_helper.shell_type == "powershell":
            # PowerShell one-liner
            return self._executor.remote_execute(
                r'foreach($user in ((ls C:\users).fullname)){echo "--- History of $user"; cat "$user\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadline\ConsoleHost_history.txt" -ea 0}'
            )
 
        return "⚠️ CMD only stores your command history in memory for the current session."