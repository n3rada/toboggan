# toboggan/core/actions/unhide/windows.py

# Built-in imports
import base64

# Local application/library specific imports
from toboggan.core.action import BaseAction


class UnHideAction(BaseAction):
    """
    Reverse the HideAction obfuscation transformation for Windows.

    **IMPORTANT**: This action performs local Python-based decoding and does NOT
    execute any commands on the remote system. It only uses pure Python operations
    (string reversal and base64 decoding) to decode command output.

    Requirements:
        - None (all operations are performed locally in Python)
    """

    DESCRIPTION = "Reverse the HideAction transformation (reverse → base64 decode)."

    def run(self, command: str) -> str:
        try:
            # Step 1: Reverse the string (undo PowerShell string reversal)
            reversed_data = command[::-1]

            # Step 2: Base64 decode
            decoded_data = base64.b64decode(reversed_data)

            # Step 3: Decode to UTF-8 string
            return decoded_data.decode("utf-8", errors="replace").strip()

        except Exception as e:
            return f"❌ Failed to decode hidden command: {e}"
