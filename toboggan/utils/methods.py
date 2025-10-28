# Built-in imports
import secrets
import pathlib
import base64
import io
import gzip
from urllib.parse import urlparse

# Third party library imports
from prompt_toolkit import shortcuts
from prompt_toolkit.styles import Style


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


def is_valid_proxy(url):
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https", "socks4", "socks5"} and parsed.hostname


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



def is_valid_directory_path(path: str) -> bool:
    """
    Validates if the provided path is a valid Unix or Windows directory path.

    Args:
        path (str): The directory path to validate.
    Returns:
        bool: True if the path is valid absolute path, False otherwise.
    """
    try:
        # Detect if it's a Windows or Unix path
        if '\\' in path or ':' in path:
            # Windows path
            p = pathlib.PureWindowsPath(path)
            return p.is_absolute()
        else:
            # Unix path
            p = pathlib.PurePosixPath(path)
            return p.is_absolute()
    except Exception as e:
        return False


def is_valid_file_path(path: str) -> bool:
    r"""
    Validates if the provided path is a valid Unix or Windows file path (not ending with / or \).

    Args:
        path (str): The file path to validate.
    Returns:
        bool: True if the path is valid and doesn't end with / or \, False otherwise.
    """
    try:
        # Detect if it's a Windows or Unix path
        if '\\' in path or ':' in path:
            # Windows path
            p = pathlib.PureWindowsPath(path)
            return p.is_absolute() and not path.endswith('\\')
        else:
            # Unix path
            p = pathlib.PurePosixPath(path)
            return p.is_absolute() and not path.endswith('/')
    except Exception as e:
        return False