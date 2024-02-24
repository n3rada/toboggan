"""
webshell.py
------------------------

Module containing utilities to interact with basic webshells.

This module currently provides a single function that sends commands to a specific webshell URL and
parses the outputs to sanitize common unwanted escape sequences. It uses the httpx library to make HTTP requests
and the built-in 're' library for regular expressions.

Functions:
    - execute(command: str, timeout: float = None) -> str
"""

# Buit-in imports
import re

# Third party library imports
import httpx


def execute(command: str, timeout: float = None) -> str:
    response = httpx.get(
        url="||URL||",
        params={
            # ||PARAM_PASSWORD||
            "||PARAM_CMD||": command,
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

    # Add a new line at the end
    output += "\n"

    return output
