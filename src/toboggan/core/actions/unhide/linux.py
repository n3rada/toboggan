# toboggan/src/actions/unhide/linux.py

import base64

from toboggan.src.action import BaseAction


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
            # Step 1: Reverse the string (undo `rev`)
            reversed_data = command[::-1]

            # Step 2: Base64 decode
            decoded_data = base64.b64decode(reversed_data)

            # Step 4: Decode to UTF-8 string
            return decoded_data.decode("utf-8", errors="replace").strip()

        except Exception as e:
            return f"❌ Failed to decode hidden command: {e}"
