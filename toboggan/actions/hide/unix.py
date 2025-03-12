# Built-in imports
import base64
import re

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core import utils


class HideAction(BaseAction):
    def run(self, command: str) -> str:
        # Verify if the user tries to control the redirection
        if re.search(r"(1?>>?|2?>>?|>>?|[0-9]+>&[0-9]+)", command) is None:
            command += " 2>&1"

        # Base64 the command
        base64_command = base64.b64encode(command.encode(encoding="utf-8")).decode(
            encoding="utf-8"
        )

        # Reverse the encoded string
        reversed_command = base64_command[::-1]

        # base64 encode the reversed string
        base64_reversed_command = base64.b64encode(
            reversed_command.encode(encoding="utf-8")
        ).decode(encoding="utf-8")

        # Take the reversed base64 command, decode it, reverse the decoded output,
        # decode it again, execute the result through the default shell, compress
        # the output, encode the compressed data in base64, reverse this encoded string,
        # and finally convert it to a hexadecimal string.
        obfuscated_command = f"echo '{base64_reversed_command}'|base64 -d|rev|base64 -d|$0|gzip|base64 -w0|rev"

        # base64 it
        obfuscated_command = base64.urlsafe_b64encode(
            obfuscated_command.encode(encoding="utf-8")
        ).decode(encoding="utf-8")

        obfuscated_command = f"echo '{obfuscated_command}'|base64 -d|$0"

        # Replacing all the spaces with ${IFS} value, to evade most of the spaces control.
        obfuscated_command = obfuscated_command.replace(" ", "${IFS}")

        # Our command is ready
        return obfuscated_command
