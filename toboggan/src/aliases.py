class Aliases:
    """
    Manage and resolve command aliases for the terminal interface.

    Attributes:
        __prefix: Prefix used for the alias commands.
        __command_map: A mapping of alias commands to their actual commands.
    """

    def __init__(self, os: str, prefix: str = None):
        if prefix is None:
            raise ValueError("A prefix must be defined for Aliases initialisation.")
        # The prefix to call for the alias
        self.__prefix = prefix

        # Define command map with nested OS-specific commands
        self.__command_map = {
            "upgrade": {
                "unix": self.__unix_upgrade(),
                "windows": self.__windows_upgrade(),
            },
            "users": {
                "unix": "for user in $(cut -d':' -f1 /etc/passwd 2>/dev/null);do id $user;done 2>/dev/null | sort",
                "windows": r"""glu | ? Enabled | % { $u=$_.Name; $g=(glg | ? { (glgm -Group $_.Name -ea 0).Name -contains "localhost\$u" }).Name -join ', '; [PSCustomObject]@{ User=$u; SID=$_.SID; FullName=$_.FullName; Desc=$_.Description; Groups=$g } } | ft -AutoSize""",
            },
            "drives": {
                "unix": '(mount | grep -E \'^/dev/| /mnt/\' | awk \'{print $1, $3}\' | while read dev mnt; do size=$(df -h --output=size "$mnt" | tail -n 1); content=$(tree -L 2 "$mnt" | head -n 50); echo "\n$dev $mnt $size\n$content"; done)',
                "windows": r"""Get-WmiObject Win32_LogicalDisk | Where-Object { $_.DriveType -eq 2 -or $_.DriveType -eq 3 -or $_.DriveType -eq 4 } | ForEach-Object { $drive = $_.DeviceID; $size = if ($_.Size) { [math]::Round(($_.Size / 1GB), 2) } else { "Unknown" }; $content = Get-ChildItem -Path $drive -Depth 0 -ea 0 | Select-Object -First 50 | Out-String; "$drive ($size GB)`n$content" }""",
            },
            "startup_apps": {
                "unix": 'echo "Cron Jobs:" && crontab -l 2>/dev/null; echo "Systemd User Services:" && systemctl --user list-unit-files --state=enabled 2>/dev/null; echo "XDG Autostart:" && ls ~/.config/autostart/ 2>/dev/null',
                "windows": r"""(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run','HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -ea 0 | ForEach-Object { $_.PSObject.Properties | Where-Object { -not ($_ -match "PSParentPath|PSChildName|PSDrive|PSProvider|PSPath") } | ForEach-Object { "$($_.Name) --> $($_.Value)" } }) + (Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup" | ForEach-Object { $_.FullName })""",
            },
            "auth_failures": {
                "unix": "zgrep -C 2 'FAILED su' /var/log/auth.log*",
                "windows": r"Get-WinEvent -LogName Security | Where-Object { $_.ID -eq 4625 }",
            },
            "history": {
                "unix": 'for user_home in /home/*; do echo "---- History of $(basename $user_home)"; for history_file in $user_home/.*history; do [ -f "$history_file" ] && echo "-- $history_file" && cat $history_file; done; done',
                "windows": r'foreach($user in ((ls C:\users).fullname)){echo "--- History of $user"; cat "$user\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadline\ConsoleHost_history.txt" -ea 0}',
            },
            "hidden_files": {
                "unix": 'find /home -type f -name ".*" -exec ls -l {} \; 2>/dev/null',
                "windows": r'gci $env:USERPROFILE -File -Hidden -Rec -ea 0 | ? { $_.FullName -notlike "*\AppData\*" } | ForEach-Object { $_.FullName }',
            },
            "plain_files": {
                "unix": None,
                "windows": r"""gci $env:USERPROFILE, 'C:\Users\Public' -Include *.txt,*.pdf,*.xls,*.xlsx,*odt,*.md,*.rtf,*.csv,.doc,*.docx,*ini -rec -ea 0 | ForEach-Object { "$($_.FullName) -> $((gc $_.FullName) -join ' ')" }""",
            },
            "installed_apps": {
                "unix": "dpkg -l | grep -i version",
                "windows": r'''Write-Host "Checking 32-bit registry:" -ForegroundColor Yellow; gip "HKLM:\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" | ? { $_.DisplayName -and $_.InstallLocation } | select DisplayName, InstallLocation; Write-Host "Checking 64-bit registry:" -ForegroundColor Yellow; gip "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" | ? { $_.DisplayName -and $_.InstallLocation } | select DisplayName, InstallLocation; Write-Host "Checking Program Files directories:" -ForegroundColor Yellow; gci 'C:\Program Files*'; Write-Host "Checking Downloads directory:" -ForegroundColor Yellow; gci "$env:USERPROFILE\Downloads"''',
            },
            "privbins": {
                "unix": 'echo "------- SUID (Set User ID) Files:" && find / -perm -u=s -type f -ls 2>/dev/null ; echo "------- SGID (Set Group ID) Files:" && find / -perm -g=s -type f -ls 2>/dev/null',
                "windows": r"""gci $env:USERPROFILE -rec -file -inc *.exe -ea 0 | ? { (Get-Acl $_.FullName).Access | ? { $_.FileSystemRights -like "*FullControl*" } } | ForEach-Object { $_.FullName }""",
            },
            "worldw": {
                "unix": """echo "------- World Writable Directories:" && find / \( -path /proc -o -path /sys -o -path /run/lock \) -prune -o -perm -o=w -type d -print 2>/dev/null && echo "------- World Writable Files:" && find / \( -path /proc -o -path /sys -o -path /run/lock \) -prune -o -perm -o=w -type f -print 2>/dev/null""",
                "windows": None,
            },
            "services": {
                "unix": "systemctl list-units --type=service --all",
                "windows": r"""Get-CimInstance -ClassName win32_service | where {$_.StartMode -ne "Disabled" -and $_.PathName -notmatch "C:\\Windows"} | select StartName, Name, StartMode, State, PathName, Description | fl""",
            },
        }

        # Select the commands for the given OS
        self.__command_map = {
            self.__prefix + k: v[os] for k, v in self.__command_map.items()
        }

    # Dunders
    def __contains__(self, full_command: str) -> str:
        # Check if the given command starts with the defined prefix
        return (
            full_command.startswith(self.__prefix)
            and full_command in self.__command_map
        )

    def __getitem__(self, full_command: str) -> str:
        """Return the actual command associated with the given custom command."""
        return self.__command_map.get(full_command)

    # Public methods

    def display_aliases(self) -> str:
        """
        Display a list of all available command aliases.

        Returns:
            str: A formatted string listing all command aliases.
        """
        # Determine the maximum length of aliases for proper alignment
        max_alias_length = max(len(alias) for alias in self.__command_map.keys())

        aliases_str = "[Toboggan] Aliases Mapping:\n"
        for alias, cmd in sorted(self.__command_map.items()):
            if (
                alias != f"{self.__prefix}aliases"
            ):  # Don't display the alias for the \aliases command itself
                # Use ljust to left-align the alias and pad with spaces to max_alias_length, then add a tab character
                aliases_str += f"\t{alias.ljust(max_alias_length)}\t=> {cmd}\n"
        return aliases_str

    # Private methods

    def __unix_upgrade(self) -> str:
        """
        Generate an upgrade command for UNIX systems.

        Returns:
            str: Command string for UNIX upgrade.
        """
        shell_path = "/bin/bash"
        # Break the `upgrade` command for UNIX into parts
        python3_upgrade = (
            f"""/usr/bin/python3 -c 'import pty; pty.spawn("{shell_path}")'"""
        )
        python_upgrade = (
            f"""/usr/bin/python -c 'import pty; pty.spawn("{shell_path}")'"""
        )
        script_upgrade = f"SHELL={shell_path} script -q /dev/null"
        return f"{python3_upgrade} || {python_upgrade} || {script_upgrade}"

    def __windows_upgrade(self) -> str:
        """
        Generate an upgrade command for Windows systems. (Currently unimplemented)

        Returns:
            str: Command string for Windows upgrade. None since it's unimplemented.
        """
        return None

    # Properties
    @property
    def prefix(self):
        """Returns the prefix used for the alias commands."""
        return self.__prefix
