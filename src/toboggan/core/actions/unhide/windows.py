# toboggan/core/actions/unhide/windows.py

# Built-in imports
import base64

# Local application/library specific imports
from toboggan.core.action import BaseAction


class UnHideAction(BaseAction):
    """
    Reverse the HideAction obfuscation transformation for Windows.
    """

    DESCRIPTION = "Reverse the HideAction transformation (reverse → base64 decode)."

    def run(self, command: str) -> str:
        try:
            # Step 0: Clean the input - remove all whitespace, newlines, etc.
            cleaned = ''.join(command.split())
            
            if not cleaned:
                return ""
            
            # Step 1: Reverse the string (undo PowerShell string reversal)
            reversed_data = cleaned[::-1]

            # Step 2: Base64 decode
            decoded_data = base64.b64decode(reversed_data)

            # Step 3: Decode to UTF-8 string
            return decoded_data.decode("utf-8", errors="replace").strip()

        except Exception as e:
            return f"❌ Failed to decode hidden command: {e}"
