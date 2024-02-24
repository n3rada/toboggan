"""
snippet.py
------------------------

Module containing utilities to interact with system code.

Functions:
    - execute(command: str, timeout: float = None) -> str
"""

# Buit-in imports
import subprocess

# This will be set dynamically based on the user input
BASE_CMD = None


def execute(command: str, timeout: float = None) -> str:
    """
    Executes a system command embedded in the BASE_CMD command.

    Args:
        command (str): The command to be embedded and executed.
        timeout (float, optional): Maximum time in seconds before the command times out. Defaults to None.

    Returns:
        str: Output of the command.
    """

    full_cmd = BASE_CMD.replace("||cmd||", command)

    try:
        # Execute the composed command and wait for it to complete or time out.
        output = subprocess.check_output(
            full_cmd, stderr=subprocess.STDOUT, shell=True, timeout=timeout
        ).decode("utf-8")
    except subprocess.TimeoutExpired:
        return "Error: Command execution timed out."
    except subprocess.CalledProcessError as error:
        return f"Error executing command: {error.output.decode('utf-8')}"

    return output
