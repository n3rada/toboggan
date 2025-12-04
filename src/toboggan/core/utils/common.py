# toboggan/core/utils/common.py

# Built-in imports
import secrets
import pathlib
import base64
import io
import gzip
import uuid

# Third party library imports
from loguru import logger
from lxml import html, etree

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


def generate_uuid() -> str:
    """Generates a random UUID string."""
    return str(uuid.uuid4())


def random_float_in_range(
    min_value: float, max_value: float, precision: float = 10**10
) -> float:
    rand_int = secrets.randbelow(precision)
    normalized_float = min_value + (max_value - min_value) * (rand_int / precision)
    return normalized_float


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
        if "\\" in path or ":" in path:
            # Windows path
            p = pathlib.PureWindowsPath(path)
            return p.is_absolute()
        else:
            # Unix path
            p = pathlib.PurePosixPath(path)
            return p.is_absolute()
    except Exception as e:
        return False

def normalize_html_text(body: str) -> str:
    """
    Remove scripts, styles, comments and return only normalized visible text.
    """
    try:
        doc = html.fromstring(body)

        # Remove script/style/meta/noscript/iframe/svg
        for bad in doc.xpath(
            "//script|//style|//noscript|//meta|//iframe|//svg|//link|//head"
        ):
            bad.drop_tree()

        # Remove HTML comments
        etree.strip_tags(doc, etree.Comment)

        # Extract visible text
        text = doc.text_content()

        # Normalize whitespace
        text = " ".join(text.split())

        return text.lower()

    except Exception as e:
        logger.trace(f"HTML normalization failed: {e}")
        return body.lower()

def extract_html_title(body: str) -> str | None:
    """
    Extract the <title> from HTML if present.
    Returns None if not found or invalid HTML.
    """
    try:
        doc = html.fromstring(body)
        title = doc.findtext(".//title")
        if title:
            return title.strip().lower()
    except Exception as e:
        logger.trace(f"Title extraction failed: {e}")

    return None


def analyze_response(body: str) -> bool:
    if not body:
        return False

    title = extract_html_title(body)

    if not title:
        return False

    logger.info(f"Title of the webpage is: {title}")

    blocked_keywords = [
        "access denied",
        "proxy authentication",
        "intercepted",
        "blocked by",
        "content filtered",
        "security policy",
        "bluecoat",
        "zscaler",
        "fortigate",
        "checkpoint",
    ]

    for kw in blocked_keywords:
        if kw in title:
            logger.debug(f"Matched {kw}")
            return False

    return True



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
        if "\\" in path or ":" in path:
            # Windows path
            p = pathlib.PureWindowsPath(path)
            return p.is_absolute() and not path.endswith("\\")
        else:
            # Unix path
            p = pathlib.PurePosixPath(path)
            return p.is_absolute() and not path.endswith("/")
    except Exception as e:
        return False
