# Built-in imports
from pathlib import Path
import secrets
import base64
import io
import gzip
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


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


def aes_encrypt(command: str) -> tuple:
    command = command.encode("utf-8")

    # Padding for the data to be AES-compatible
    pad = (
        lambda s: s
        + (AES.block_size - len(s) % AES.block_size)
        * chr(AES.block_size - len(s) % AES.block_size).encode()
    )

    data = pad(command)

    # AES encryption
    key = get_random_bytes(16)  # 128-bit AES key
    cipher = AES.new(key, AES.MODE_CBC)
    iv = cipher.iv
    encrypted = cipher.encrypt(data)

    # Output the encrypted data, key, and IV in base64
    return (
        base64.b64encode(encrypted).decode(),
        base64.b64encode(key).decode(),
        base64.b64encode(iv).decode(),
    )


def yes_no_query(prompt: str = "") -> bool:
    """
    Asks a yes/no question and returns the user's response as a boolean.

    Args:
        - param prompt: The question to ask the user.

    Returns:
        - bool: True if the user answers 'yes', False if the user answers 'no'.
    """
    while True:
        try:
            response = input(f"{prompt} (YES/no): ").strip().lower()
            if response == "" or response.startswith("y"):
                return True

            return False
        except KeyboardInterrupt:
            print()
            return False


def generate_random_token(min_length=3, max_length=6) -> str:
    token_length = secrets.randbelow(max_length - min_length + 1) + min_length
    return secrets.token_hex(token_length // 2 + 1)[:token_length]


def random_float_in_range(
    min_value: float, max_value: float, precision: float = 10**10
) -> float:
    rand_int = secrets.randbelow(precision)
    normalized_float = min_value + (max_value - min_value) * (rand_int / precision)
    return normalized_float
