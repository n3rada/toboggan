# toboggan/core/actions/unhide/linux.py

# Built-in imports
import base64

# Third-party imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.action import BaseAction


class UnHideAction(BaseAction):
    """
    Reverse the HideAction obfuscation transformation.

    **IMPORTANT**: This action performs local Python-based decoding and does NOT
    execute any commands on the remote system. It only uses pure Python operations
    (string reversal and base64 decoding) to decode command output.

    Requirements:
        - None (all operations are performed locally in Python)
    """

    DESCRIPTION = (
        "Reverse the HideAction transformation (rev → base64 → gzip decompress)."
    )

    def run(self, command: str) -> str:
        try:
            logger.debug(f"🔓 De-obfuscating output: {len(command)} bytes")
            
            # Step 1: Reverse the string (undo `rev`)
            reversed_data = command[::-1]

            # Step 2: Base64 decode
            decoded_data = base64.b64decode(reversed_data)
            logger.trace(f"After base64 decode: {len(decoded_data)} bytes")

            # Step 3: Decode to UTF-8 string
            result = decoded_data.decode("utf-8", errors="replace").strip()
            logger.trace(f"✅ Decoded result: {len(result)} bytes")
            return result

        except Exception as e:
            logger.error(f"❌ De-obfuscation failed: {e}")
            return f"❌ Failed to decode hidden command: {e}"
