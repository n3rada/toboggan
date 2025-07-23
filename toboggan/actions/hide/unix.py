# Built-in imports
import base64
import re
import os

# Third party library imports
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad

# Local application/library specific imports
from toboggan.core.action import BaseAction


def generate_key_iv():
    """
    Generates a random 32-byte key and a 16-byte IV for AES-256-CBC.
    Returns (key, iv) as hex-encoded strings.
    """
    key = os.urandom(32)
    iv = os.urandom(16)
    return key.hex(), iv.hex()


def encrypt_command(command: str, key_hex: str, iv_hex: str) -> str:
    """
    Encrypts a command using AES-256-CBC (OpenSSL-compatible).
    """
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(iv_hex)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(command.encode(), AES.block_size)
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode()


class HideAction(BaseAction):
    DESCRIPTION = (
        "Obfuscate and execute a command using OpenSSL or base64-based wrapping."
    )

    def __init__(self, executor):
        super().__init__(executor)
        self.__openssl_path = self._executor.remote_execute("command -v openssl")
        if self.__openssl_path:
            self.__openssl_path = self.__openssl_path.strip()
            self._AES_KEY, self._AES_IV = generate_key_iv()
            self._logger.info("🔑 OpenSSL detected, AES encryption enabled.")
            self._logger.debug(f"🔐 AES Key: {self._AES_KEY}")
            self._logger.debug(f"🔐 AES IV: {self._AES_IV}")
        else:
            self._logger.warning(
                "⚠️ OpenSSL not found on target, falling back to base64 obfuscation."
            )

    def run(self, command: str) -> str:
        # Add redirection unless user explicitly added it
        if re.search(r"(1?>>?|2>>&?|>>?|[0-9]+>&[0-9]+)", command) is None:
            command += " 2>&1"

        if self.__openssl_path:
            encrypted = encrypt_command(command, self._AES_KEY, self._AES_IV)
            decrypt_pipeline = (
                f"echo '{encrypted}'|base64 -d|"
                f"{self.__openssl_path} enc -aes-256-cbc -d -K {self._AES_KEY} -iv {self._AES_IV}|{self._executor.shell}"
            )
        else:
            # fallback: just base64 + decode
            encoded = base64.b64encode(command.encode()).decode()
            decrypt_pipeline = f"echo '{encoded}'|base64 -d|{self._executor.shell}"

        # Obfuscate further: gzip + base64 + reverse + base64 encode all
        obfuscated = base64.urlsafe_b64encode(
            f"{decrypt_pipeline}|gzip|base64 -w0|rev".encode()
        ).decode()

        final_cmd = f"echo '{obfuscated}'|base64 -d|{self._executor.shell}"

        return final_cmd
