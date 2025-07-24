
# Local application/library specific imports
from toboggan.core.action import BaseAction


class ReconAction(BaseAction):
    """Enumerate more."""

    DESCRIPTION = "Show useful information about the targeted sytem."

    def run(self):
        self._logger.info(f"Identity: {self._executor.remote_execute(command='/usr/bin/id').strip()}")
        self.__analyse_path_variable()
        self.__analyse_readable_files_other_users()
        self.__analyse_weak_file_permissions()

    def __analyse_path_variable(self) -> None:
        raw_path = self._executor.remote_execute(command="/bin/echo $PATH").strip()
        self._logger.info("Binary and script searching order (PATH):")
        for index, entry in enumerate(raw_path.split(":"), start=1):
            print(f"\t{index}. {entry}")

    def __analyse_readable_files_other_users(self) -> None:
        """
        Scans for and reports files in other users' home directories that are readable by the current user,
        while suppressing error messages to clean up the output.

        This method leverages the 'find' command to explore the '/home' directory, excluding the current user's
        home directory to focus on others. It lists files that are marked as readable, potentially highlighting improper
        permission settings or sensitive information exposure. Error messages, such as 'Permission denied', are
        suppressed to ensure the output is focused on successfully found readable files.

        Note:
        - Designed for user-level permissions to identify misconfigurations or security risks from a non-privileged standpoint.
        - Error messages are suppressed to clean up the output, focusing on readable files.
        """
        # Execute the command with error output suppression
        command_result = self._executor.remote_execute(
            command='find /home -path "$HOME" -prune -o -readable -type f -print 2>/dev/null'
        ).strip()

        if command_result:
            self._logger.info("Readable files have been found in other user land:")

            # Organize files by their parent directories
            directory_map = {}
            for file_path in command_result.split("\n"):
                directory, file_name = file_path.rsplit("/", 1)
                if directory in directory_map:
                    directory_map[directory].append(file_name)
                else:
                    directory_map[directory] = [file_name]

            # Print the organized list
            for directory, files in directory_map.items():
                print(f"\t• {directory}")
                for file_name in files:
                    print(f"\t\t- {file_name}")
        else:
            self._logger.warning("No readable files found in other user's directories.")

    def __analyse_weak_file_permissions(self) -> None:
        """
        Analyzes the file permissions of certain critical files on the system.
        Checks for world-writable or group-writable permissions and evaluates if
        they pose a risk based on the current user's group memberships.
        """

        def check_group_ownership(file: str) -> str:
            """
            Returns the group ownership of a given file.

            Args:
                file (str): Path to the file whose group ownership is to be checked.

            Returns:
                str: Name of the group that owns the file.
            """
            return self._executor.remote_execute(command=f"/usr/bin/stat -c '%G' {file}").strip()

        def current_user_groups() -> set:
            """
            Fetches the list of groups the current user is a part of.

            Returns:
                set: A set containing names of groups the current user belongs to.
            """
            return set(self._executor.remote_execute(command="/usr/bin/id -Gn").strip().split())

        user_groups = current_user_groups()

        def analyze_file(file: str) -> None:
            """
            Analyzes the permissions of a given file. Prints out a warning message
            if the file is world-writable or group-writable and poses a risk.

            Args:
                file (str): Path to the file to be analyzed.
            """
            perms = self._executor.remote_execute(command=f"/usr/bin/stat -c '%A' {file}").strip()
            file_group = check_group_ownership(file)

            if "w" in perms[7]:
                self._logger.warning(f"{file} is world-writable!")
            elif "w" in perms[5]:
                if file_group in user_groups:
                    self._logger.warning(f"{file} is group-writable and the current user is part of the '{file_group}' group!")
                else:
                    self._logger.warning(f"{file} is group-writable by the '{file_group}' group, but the current user isn't part of it.")
            else:
                self._logger.info(f"{file} permissions are appropriately configured.")

        # Checking /etc/shadow permissions
        analyze_file("/etc/shadow")
        # Checking /etc/passwd permissions
        analyze_file("/etc/passwd")
        # Checking for /etc/sudoers
        analyze_file("/etc/sudoers")