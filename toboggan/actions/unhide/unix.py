# Built-in imports
import base64
import gzip

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core import utils


class UnHideAction(BaseAction):
    def run(self, command: str) -> str:
        # Decode the base64 string
        decoded_result = base64.b64decode(command[::-1])

        # Ungzip the reversed data
        unzipped_result = gzip.decompress(decoded_result)

        # Convert the unzipped data to a string
        output = unzipped_result.decode("utf-8", errors="replace")
        return output
