# toboggan/core/actions/ssh_find/linux.py


# Local library imports
from toboggan.core.action import BaseAction

class FindSshKeysAction(BaseAction):
    DESCRIPTION = "Search for SSH private keys on the system (user and host keys)."

    def run(self) -> str:
        find_cmd = "find /home/*/.ssh /root/.ssh /etc/ssh -type f -exec grep -l 'PRIVATE KEY-' {} + 2>/dev/null"

        result = self._executor.remote_execute(find_cmd, timeout=60)

        if not result:
            return "🔍 No SSH private keys found."

        keys = result.strip().splitlines()
        keys = sorted(set(keys))

        output = "\n🔐 Found SSH Private Keys\n"
        output += "-" * 60 + "\n"
        for key_path in keys:
            output += f"📁 {key_path}\n"
        output += "-" * 60 + "\n"

        return output
