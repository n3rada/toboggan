import secrets
import re
import base64
import io
import gzip


# Third party library imports
from prompt_toolkit import shortcuts
from prompt_toolkit.styles import Style

# from Crypto.Cipher import AES
# from Crypto.Random import get_random_bytes


class SingletonMeta(type):
    """
    Metaclass for implementing Singleton pattern.
    Ensures only one instance of a class exists.
    """

    _instances = {}

    def __call__(cls, *args, **kwargs):
        """Ensure only one instance of the class is created."""
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


def banner() -> str:
    return r"""
    _____      _
   /__   \___ | |__   ___   __ _  __ _  __ _ _ __
     / /\/ _ \| '_ \ / _ \ / _` |/ _` |/ _` | '_ \
    / / | (_) | |_) | (_) | (_| | (_| | (_| | | | |
    \/   \___/|_.__/ \___/ \__, |\__, |\__,_|_| |_|
                            |___/ |___/
         Slides onto remote system with ease
                    @n3rada
    """


def is_shell_prompt_in(command_output: str) -> bool:
    """
    Detects if the command output is a shell prompt.

    Args:
        command_output (str): The latest command output to analyze.

    Returns:
        bool: True if the output appears to be a shell prompt, False otherwise.
    """
    prompt_patterns = [
        r"\$ $",  # Standard user bash-like prompt
        r"# $",  # Root shell prompt
        r"> $",  # Some interactive shells (e.g., Windows CMD)
        r".*@.*:.*\$",  # user@host:/path$ (common for interactive shells)
        r"┌──\((.*?)㉿(.*?)\)-\[.*\]",  # Kali-specific prompt: ┌──(user㉿hostname)-[path]
        r"root@.*?:.*?#",  # Generic root prompt
    ]

    return any(re.search(pattern, command_output) for pattern in prompt_patterns)


def base64_for_powershell(command: str) -> str:
    # Encode the command as UTF-16LE, PowerShell's default encoding
    encoded_command = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    return encoded_command


def compress_with_gzip(command: str) -> bytes:
    # Compress command with GZip and return bytes
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="w") as f:
        f.write(command.encode("utf-8"))
    return out.getvalue()


# def aes_encrypt(command: str) -> tuple:
#     command = command.encode("utf-8")

#     # Padding for the data to be AES-compatible
#     pad = (
#         lambda s: s
#         + (AES.block_size - len(s) % AES.block_size)
#         * chr(AES.block_size - len(s) % AES.block_size).encode()
#     )

#     data = pad(command)

#     # AES encryption
#     key = get_random_bytes(16)  # 128-bit AES key
#     cipher = AES.new(key, AES.MODE_CBC)
#     iv = cipher.iv
#     encrypted = cipher.encrypt(data)

#     # Output the encrypted data, key, and IV in base64
#     return (
#         base64.b64encode(encrypted).decode(),
#         base64.b64encode(key).decode(),
#         base64.b64encode(iv).decode(),
#     )


def generate_variable_length_token(min_length=3, max_length=6) -> str:
    """Generates a random token with a length between min_length and max_length."""
    token_length = secrets.randbelow(max_length - min_length + 1) + min_length
    return secrets.token_hex(token_length // 2 + 1)[:token_length]


def generate_fixed_length_token(length: int) -> str:
    """Generates a random token of a fixed length."""
    return secrets.token_hex(length // 2 + 1)[:length]


def random_float_in_range(
    min_value: float, max_value: float, precision: float = 10**10
) -> float:
    rand_int = secrets.randbelow(precision)
    normalized_float = min_value + (max_value - min_value) * (rand_int / precision)
    return normalized_float


def yes_no_query(query: str, title: str = "Hey! Listen!") -> bool:

    message_box = shortcuts.yes_no_dialog(
        title=title,
        text=query,
        style=Style.from_dict(
            {
                "dialog": "bg:#feda5c",
                "dialog frame.label": "bg:#ffffff #000000",
                "dialog.body": "bg:#000000 #00ff00",
                "dialog shadow": "bg:#00aa00",
            }
        ),
    )

    return message_box.run()
