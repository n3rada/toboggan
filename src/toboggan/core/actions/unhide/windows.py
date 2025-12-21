# toboggan/core/actions/unhide/windows.py

# Built-in imports
import base64

# Third-party imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.action import BaseAction


class UnHideAction(BaseAction):
    """
    Reverse the HideAction obfuscation transformation for Windows.
    """

    DESCRIPTION = "Reverse the HideAction transformation (reverse → base64 decode)."

    def run(self, command: str) -> str:
        try:
            logger.debug(f"🔓 De-obfuscating output: {len(command)} bytes")
            logger.trace(f"Raw: {command}")
            
            # Step 0: Clean the input - remove all whitespace, newlines, etc.
            cleaned = ''.join(command.split())
            logger.trace(f"After cleaning: {len(cleaned)} bytes")
            
            if not cleaned:
                logger.warning("⚠️  Empty output after cleaning")
                return ""
            
            # Step 1: Reverse the string (undo PowerShell string reversal)
            reversed_data = cleaned[::-1]
            logger.trace(f"After reverse: {reversed_data}")

            # Step 2: Base64 decode
            decoded_data = base64.b64decode(reversed_data)
            logger.trace(f"After base64 decode: {len(decoded_data)} bytes")

            # Step 3: Decode to UTF-8 string
            result = decoded_data.decode("utf-8", errors="replace").strip()
            logger.debug(f"✅ Decoded result: {len(result)} bytes")
            return result

        except Exception as e:
            logger.error(f"❌ De-obfuscation failed: {e}")
            logger.trace(f"Failed on: {command}")
            return f"❌ Failed to decode hidden command: {e}"
