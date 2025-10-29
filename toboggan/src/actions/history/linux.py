# Local application/library specific imports
from toboggan.src.action import BaseAction


class HistoryAction(BaseAction):
    DESCRIPTION = "Retrieve all users' shell command history"

    def run(self) -> str:
        return self._executor.remote_execute(
            'for user_home in /home/*; do echo "---- History of $(basename $user_home)"; for history_file in $user_home/.*history; do [ -f "$history_file" ] && echo "-- $history_file" && cat $history_file; done; done'
        )
