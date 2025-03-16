import re
import shutil

# Local application/library specific imports
from toboggan.core.action import BaseAction


class GetUsersAction(BaseAction):
    DESCRIPTION = (
        "Retrieve users and their groups from /etc/passwd in a structured format."
    )

    def run(self) -> str:
        """
        Fetches all system users and displays their primary and additional groups in a table,
        while ensuring output stays within terminal width.

        Returns:
            str: Formatted list of users with their groups.
        """
        # Get terminal width
        terminal_width = shutil.get_terminal_size((80, 20)).columns

        # Fetch all users and their group info
        raw_output = self._executor.remote_execute(
            "getent passwd | cut -d: -f1 | xargs -I{} id {} 2>/dev/null"
        )

        if not raw_output:
            return "⚠️ No users found or access denied."

        users_data = []

        for line in raw_output.splitlines():
            match = re.match(r"uid=(\d+)\((\w+)\) gid=(\d+)\((\w+)\) groups=(.+)", line)
            if match:
                user_id, username = match.group(1), match.group(2)
                group_id, primary_group = match.group(3), match.group(4)

                # Extract additional groups (with their IDs)
                other_groups = [
                    g.replace("(", " (").replace(")", ")")
                    for g in match.group(5).split(", ")
                ]

                users_data.append(
                    (
                        f"{username} ({user_id})",
                        f"{primary_group} ({group_id})",
                        ", ".join(other_groups),
                    )
                )

        # Sort users alphabetically
        users_data.sort(key=lambda x: x[0])

        # Determine column sizes dynamically
        max_user_len = max(len(row[0]) for row in users_data) + 2
        max_group_len = max(len(row[1]) for row in users_data) + 2

        # Calculate space left for "Other Groups" column
        max_other_groups_len = terminal_width - (max_user_len + max_group_len + 10)
        max_other_groups_len = max(20, max_other_groups_len)  # Ensure minimum width

        total_width = max_user_len + max_group_len + max_other_groups_len + 10

        # Format table output
        formatted_output = "\n📜 System Users & Groups:\n"
        formatted_output += "-" * min(terminal_width, total_width) + "\n"
        formatted_output += f"{'🆔 User':<{max_user_len}}| {'👥 Primary Group':<{max_group_len}}| 📂 Other Groups\n"
        formatted_output += "-" * min(terminal_width, total_width) + "\n"

        for user, primary_group, other_groups in users_data:
            if len(other_groups) > max_other_groups_len:
                wrapped_groups = [
                    other_groups[i : i + max_other_groups_len]
                    for i in range(0, len(other_groups), max_other_groups_len)
                ]
                formatted_output += f"{user:<{max_user_len}} | {primary_group:<{max_group_len}} | {wrapped_groups[0]}\n"
                for group_line in wrapped_groups[1:]:
                    formatted_output += (
                        f"{' ' * max_user_len} | {' ' * max_group_len} | {group_line}\n"
                    )
            else:
                formatted_output += f"{user:<{max_user_len}} | {primary_group:<{max_group_len}} | {other_groups}\n"

        formatted_output += "-" * min(terminal_width, total_width) + "\n"

        return formatted_output
