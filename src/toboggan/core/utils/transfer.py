"""Shared validation and chunk handling for file transfers."""

import re
from collections.abc import Callable
from typing import BinaryIO

from loguru import logger


def validate_chunk_size(size: int | str) -> int:
    # The interactive terminal passes action arguments as strings.
    if isinstance(size, str) and re.fullmatch(r"[0-9]+", size):
        size = int(size)
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("Transfer size must be a positive integer.")
    return size


def receive_chunks(
    read_chunk: Callable[[int, int], str],
    destination: BinaryIO,
    total_size: int,
    chunk_size: int,
    progress: Callable[[int], None],
) -> None:
    """Receive exact Base64 slices, retrying failures without advancing the offset."""
    validate_chunk_size(chunk_size)
    if total_size <= 0:
        raise ValueError("Encoded file size must be positive.")

    offset = 0
    failures = 0
    while offset < total_size:
        expected = min(chunk_size, total_size - offset)
        try:
            chunk = read_chunk(offset, expected).strip()
        except Exception as exc:  # user-defined execution backends
            chunk = ""
            reason = type(exc).__name__
        else:
            reason = f"received {len(chunk)} of {expected} bytes"

        valid = bool(re.fullmatch(r"[A-Za-z0-9+/=]+", chunk))
        if valid and len(chunk) == expected:
            data = chunk.encode("ascii")
            if destination.write(data) != len(data):
                raise OSError("Could not write the complete download chunk.")
            offset += len(data)
            failures = 0
            progress(len(data))
        elif valid and len(chunk) < expected:
            chunk_size = len(chunk)
            failures = 0
            logger.warning(
                f"Short download response at offset {offset}; "
                f"retrying with {chunk_size}-byte chunks."
            )
        else:
            failures += 1
            if failures >= 3:
                raise OSError(f"Download failed at offset {offset}: {reason}.")
            logger.warning(
                f"Download response at offset {offset}: {reason}; "
                f"retrying ({failures}/3)."
            )


def send_chunks(
    execute: Callable[[str], str],
    make_command: Callable[[int, str], str],
    data: str,
    command_size: int,
    progress: Callable[[int], None],
) -> None:
    """Write at explicit offsets and require the staged length as acknowledgement.

    make_command must truncate the staged file at the supplied offset before
    writing, so retries also replace bytes from a previously unacknowledged write.
    The size limit applies to the complete command before executor transformations.
    """
    command_size = validate_chunk_size(command_size)
    offset = 0
    chunk_limit = command_size
    failures = 0
    while offset < len(data) or not data:
        # Include paths, offsets, and any platform wrapper in the size budget.
        low, high = 0, min(chunk_limit, len(data) - offset)
        while low < high:
            middle = (low + high + 1) // 2
            command = make_command(offset, data[offset:offset + middle])
            if len(command.encode("utf-8")) <= command_size:
                low = middle
            else:
                high = middle - 1
        chunk = data[offset:offset + low]
        command = make_command(offset, chunk)
        if (data and not chunk) or len(command.encode("utf-8")) > command_size:
            raise ValueError("Command size is too small for the upload command overhead.")

        expected = offset + len(chunk)
        try:
            response = execute(command).strip()
        except Exception as exc:  # user-defined execution backends
            response = ""
            reason = type(exc).__name__
        else:
            reason = "missing or invalid staged-length acknowledgement"
        length = int(response) if re.fullmatch(r"[0-9]+", response) else None
        if length == expected:
            progress(len(chunk))
            if not data:
                return
            offset = expected
            failures = 0
        elif length is not None and offset < length < expected:
            chunk_limit = length - offset
            failures = 0
            logger.warning(
                f"Short upload at offset {offset}; "
                f"retrying with {chunk_limit}-byte chunks."
            )
        else:
            failures += 1
            if failures >= 3:
                raise OSError(f"Upload failed at offset {offset}: {reason}.")
            logger.warning(
                f"Upload response at offset {offset}: {reason}; "
                f"retrying ({failures}/3)."
            )
