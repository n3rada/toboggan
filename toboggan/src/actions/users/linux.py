import shutil

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.src.action import BaseAction


class GetUsersAction(BaseAction):
    DESCRIPTION = (
        "Retrieve users and their groups from /etc/passwd in a structured format."
    )

    def run(self) -> str:
        terminal_width = shutil.get_terminal_size((80, 20)).columns

        passwd_data = self._executor.remote_execute("cat /etc/passwd")
        group_data = self._executor.remote_execute("cat /etc/group")

        if not passwd_data or not group_data:
            return "⚠️ Could not read /etc/passwd or /etc/group."

        # Parse /etc/group
        gid_to_group = {}
        user_to_groups = {}

        for line in group_data.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 4:
                group_name, _, gid, users = parts
                gid_to_group[gid] = group_name
                for user in users.split(","):
                    if user:
                        user_to_groups.setdefault(user, []).append(group_name)

        non_system_users = []
        system_users = []

        for line in passwd_data.strip().splitlines():
            parts = line.strip().split(":")
            if len(parts) < 7:
                continue
            username, _, uid, gid, _, _, shell = parts
            try:
                uid = int(uid)
                gid = int(gid)
            except ValueError:
                continue

            primary_group = gid_to_group.get(str(gid), f"GID:{gid}")
            additional_groups = user_to_groups.get(username, [])
            other_groups = (
                ", ".join(sorted(additional_groups)) if additional_groups else "-"
            )

            user_info = (
                f"{username} ({uid})",
                f"{primary_group} ({gid})",
                other_groups,
                shell,
            )

            if uid >= 1000 or username == "nobody":
                non_system_users.append(user_info)
            else:
                system_users.append(user_info)

        def format_table(title, data):
            if not data:
                return f"⚠️ No {title.lower()} found.\n"

            data.sort(key=lambda x: x[0])
            max_user_len = max(len(u[0]) for u in data) + 2
            max_group_len = max(len(u[1]) for u in data) + 2
            max_shell_len = max(len(u[3]) for u in data) + 2

            # Find actual max content length for other_groups
            actual_other_len = max(len(u[2]) for u in data)
            max_other_len = min(
                terminal_width - (max_user_len + max_group_len + max_shell_len + 10),
                actual_other_len + 2,
            )

            total_width = (
                max_user_len + max_group_len + max_other_len + max_shell_len + 10
            )

            section = f"\n{title}:\n"
            section += "-" * min(terminal_width, total_width) + "\n"
            section += (
                f"{'User':<{max_user_len}}| "
                f"{'Primary Group':<{max_group_len}}| "
                f"Groups{' ' * (max_other_len - 6)}| "
                f"Shell\n"
            )
            section += "-" * min(terminal_width, total_width) + "\n"

            for user, primary_group, other_groups, shell in data:
                if len(other_groups) > max_other_len:
                    wrapped = [
                        other_groups[i : i + max_other_len]
                        for i in range(0, len(other_groups), max_other_len)
                    ]
                    section += (
                        f"{user:<{max_user_len}}| "
                        f"{primary_group:<{max_group_len}}| "
                        f"{wrapped[0]:<{max_other_len}}| "
                        f"{shell:<{max_shell_len}}\n"
                    )
                    for line in wrapped[1:]:
                        section += (
                            f"{' ' * max_user_len}| "
                            f"{' ' * max_group_len}| "
                            f"{line:<{max_other_len}}| "
                            f"{' ' * max_shell_len}\n"
                        )
                else:
                    section += (
                        f"{user:<{max_user_len}}| "
                        f"{primary_group:<{max_group_len}}| "
                        f"{other_groups:<{max_other_len}}| "
                        f"{shell:<{max_shell_len}}\n"
                    )

            section += "-" * min(terminal_width, total_width) + "\n"
            return section

        output = format_table("📦 System users", system_users)
        output += format_table("📜 Non-system users", non_system_users)

        return output
