"""Shared validation and response handling for file downloads."""

import re
from collections.abc import Callable
from typing import BinaryIO

from loguru import logger


def validate_chunk_size(size: int | str) -> int:
    # The interactive terminal passes action arguments as strings.
    if isinstance(size, str) and re.fullmatch(r"[0-9]+", size):
        size = int(size)
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("Download chunk size must be a positive integer.")
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
