# toboggan/core/actions/hide/linux.py

# Built-in imports
import base64
import re
import os

# Third party library imports
from loguru import logger
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
    """
    Obfuscate and execute commands using AES-256-CBC encryption or base64 encoding.

    **IMPORTANT**: This action is initialized during executor setup, before obfuscation
    is enabled. Only openssl path is looked up during __init__ to avoid circular dependency.
    Basic commands (echo, base64) are used directly without path lookup.

    Requirements:
        - Remote system must have: echo, base64 (standard on all Unix systems)
        - Optional: openssl (for AES encryption, falls back to base64 if missing)
    """

    DESCRIPTION = (
        "Obfuscate and execute a command using OpenSSL or base64-based wrapping."
    )

    def __init__(self, executor):
        super().__init__(executor)

        # Only lookup openssl path during init (before obfuscation is enabled)
        # Use basic command names for echo and base64 (available in PATH on all systems)
        self.__openssl_path = self._executor.os_helper.get_command_location("openssl")

        if self.__openssl_path:
            self.__openssl_path = self.__openssl_path.strip()
            self._AES_KEY, self._AES_IV = generate_key_iv()
            logger.info("🔑 OpenSSL detected, AES encryption enabled.")
            logger.debug(f"🔐 AES Key: {self._AES_KEY}")
            logger.debug(f"🔐 AES IV: {self._AES_IV}")
        else:
            logger.warning(
                "⚠️ OpenSSL not found on target, falling back to base64 obfuscation."
            )

    def run(self, command: str) -> str:
        # Add redirection unless user explicitly added it
        if re.search(r"(1?>>?|2>>&?|>>?|[0-9]+>&[0-9]+)", command) is None:
            command += " 2>&1"

        if self.__openssl_path:
            encrypted = encrypt_command(command, self._AES_KEY, self._AES_IV)
            # Use 'sh' in the inner decrypt pipeline to avoid $0 context issues
            decrypt_pipeline = (
                f"echo {encrypted}|"
                f"{self.__openssl_path} enc -aes-256-cbc -d -a -K {self._AES_KEY} -iv {self._AES_IV}"
            )
            logger.trace(f"Encrypted command (AES-256-CBC): {encrypted}")
        else:
            # fallback: just base64 + decode
            encoded = base64.b64encode(command.encode()).decode()
            decrypt_pipeline = f"echo {encoded}|base64 -d"
            logger.trace(f"Encoded command (base64): {encoded}")

        # Base64 encode the entire pipeline
        encoded_pipeline = base64.b64encode(decrypt_pipeline.encode()).decode()

        hidden_command = f"echo {encoded_pipeline}|base64 -d|$0|$0|base64 -w0|rev"

        logger.trace(f"Final obfuscated command: {hidden_command}")

        return hidden_command
