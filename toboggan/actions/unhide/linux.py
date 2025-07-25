import base64
import gzip

from toboggan.core.action import BaseAction


class UnHideAction(BaseAction):
    DESCRIPTION = (
        "Reverse the HideAction transformation (rev → base64 → gzip decompress)."
    )

    def run(self, command: str) -> str:
        try:
            # Step 1: Reverse the string (undo `rev`)
            reversed_data = command[::-1]

            # Step 2: Base64 decode
            decoded_data = base64.b64decode(reversed_data)

            # Step 3: Gzip decompress
            unzipped_data = gzip.decompress(decoded_data)

            # Step 4: Decode to UTF-8 string
            return unzipped_data.decode("utf-8", errors="replace").strip()

        except Exception as e:
            return f"❌ Failed to decode hidden command: {e}"
