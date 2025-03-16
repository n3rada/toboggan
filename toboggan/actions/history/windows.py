# Local application/library specific imports
from toboggan.core.action import BaseAction


class HistoryAction(BaseAction):
    DESCRIPTION = "Retrieve all users' shell command history"

    def run(self) -> str:
        return self._executor.remote_execute(
            r'foreach($user in ((ls C:\users).fullname)){echo "--- History of $user"; cat "$user\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadline\ConsoleHost_history.txt" -ea 0}'
        )
