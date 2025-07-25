# toboggan/actions/read_others.py

from toboggan.core.action import BaseAction


class ReadableOtherHomes(BaseAction):
    """
    Scans for readable files in other users' home directories.
    Useful for identifying permission misconfigurations or information leaks.

    This action uses the `find` command to look through `/home`, skipping the current
    user's own directory. It lists files that are world-readable or accessible by the
    current user due to permissive file settings.

    Errors like permission denials are suppressed to focus on positive hits.
    """

    DESCRIPTION = "Scan other users' home directories for readable files."

    def run(self):
        command = (
            'find /home -path "$HOME" -prune -o -readable -type f -print 2>/dev/null'
        )

        result = self._executor.remote_execute(command=command).strip()

        if result:
            self._logger.info(
                "🧾 Readable files found in other users' home directories:"
            )
            directory_map = {}

            for file_path in result.split("\n"):
                if "/" not in file_path:
                    continue
                directory, file_name = file_path.rsplit("/", 1)
                directory_map.setdefault(directory, []).append(file_name)

            for directory, files in sorted(directory_map.items()):
                print(f"\t📁 {directory}")
                for file in sorted(files):
                    print(f"\t   - {file}")
        else:
            self._logger.warning(
                "🔒 No readable files found in other users' directories."
            )
