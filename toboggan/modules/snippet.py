"""
snippet.py
------------------------

Module containing utilities to interact with system code.

Functions:
    - execute(command: str, timeout: float = None) -> str
"""

# Buit-in imports
import subprocess
import os
from urllib.parse import quote

# This will be set dynamically based on the user input
BASE_CMD = None


def execute(command: str, timeout: float = None) -> str:
    """
    Executes a system command embedded in the BASE_CMD command, with elements of the command URL encoded.

    Args:
        command (str): The command to be embedded and executed, elements are URL encoded.
        timeout (float, optional): Maximum time in seconds before the command times out. Defaults to None.

    Returns:
        str: Output of the command.
    """

    env = os.environ.copy()

    if False:
        env["http_proxy"] = "http://127.0.0.1:8080"
        env["https_proxy"] = "http://127.0.0.1:8080"

    full_command = BASE_CMD.replace("||cmd||", quote(command))

    return subprocess.check_output(
        full_command, stderr=subprocess.STDOUT, shell=True, timeout=timeout, env=env
    ).decode("utf-8")
