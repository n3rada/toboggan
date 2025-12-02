# Buit-in imports
import subprocess
import shlex

# This will be set dynamically
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

    full_command = BASE_CMD.replace("||cmd||", shlex.quote(command))

    return subprocess.check_output(
        full_command, stderr=subprocess.STDOUT, shell=True, timeout=timeout
    ).decode("utf-8")
