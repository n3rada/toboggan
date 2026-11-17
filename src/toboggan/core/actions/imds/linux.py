# toboggan/core/actions/imds/linux.py

# Built-in imports
import re
import shlex

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.actions.imds.common import (
    CONNECT_TIMEOUT,
    EXECUTION_TIMEOUT,
    REQUEST_TIMEOUT,
    STATUS_MARKER,
    ImdsBase,
    ImdsResponse,
    imds_url,
    split_marker,
)

EXIT_MARKER = "TBG_IMDS_EXIT:"
_UNREACHABLE = (
    f"IMDS unreachable (no HTTP response within {CONNECT_TIMEOUT}s; "
    "not an EC2 instance, or IMDS is blocked)."
)


class ImdsAction(ImdsBase):
    """Linux IMDS requests through curl, or wget when curl is missing."""

    def _prepare(self) -> bool:
        for name in ("curl", "wget"):
            if location := self._os_helper.get_command_location(name):
                self._client_name, self._client_path = name, location.strip()
                logger.debug(f"IMDS requests use {self._client_path}")
                return True
        logger.error("IMDS browsing requires curl or wget on the target.")
        return False

    def _command(self, method: str, path: str, headers: dict[str, str]) -> str:
        url = shlex.quote(imds_url(path))
        if self._client_name == "curl":
            parts = [
                self._client_path, "-s", "--noproxy", "'*'",
                "--connect-timeout", str(CONNECT_TIMEOUT),
                "--max-time", str(REQUEST_TIMEOUT),
            ]
            if method != "GET":
                parts += ["-X", method]
            for name, value in headers.items():
                parts += ["-H", shlex.quote(f"{name}: {value}")]
            # curl expands \n in -w itself; no raw newline crosses the transport.
            parts += ["-w", shlex.quote(f"\\n{STATUS_MARKER}%{{http_code}}"), url]
            return " ".join(parts)

        parts = [self._client_path, "-q", "-O-", "-T", str(CONNECT_TIMEOUT), "-t", "1"]
        if method != "GET":
            parts.append(f"--method={method}")
        for name, value in headers.items():
            parts.append("--header=" + shlex.quote(f"{name}: {value}"))
        parts.append(url)
        return f'{" ".join(parts)} 2>&1; tbg_rc=$?; echo; echo "{EXIT_MARKER}$tbg_rc"'

    def _request(self, method: str, path: str, headers: dict[str, str]) -> ImdsResponse:
        try:
            raw = self._executor.remote_execute(
                self._command(method, path, headers),
                timeout=EXECUTION_TIMEOUT, retry=False,
                raise_on_failure=True, debug=False,
            )
        except Exception as exc:  # user-defined execution backends
            return ImdsResponse(None, error=f"Remote execution failed ({type(exc).__name__}).")
        if self._client_name == "curl":
            return self._parse_curl(raw)
        return self._parse_wget(raw, method)

    @staticmethod
    def _parse_curl(raw: str) -> ImdsResponse:
        parsed = split_marker(raw, STATUS_MARKER)
        if not parsed:
            return ImdsResponse(None, error="curl produced no status; output unusable.")
        body, status = parsed
        if status == "000":
            return ImdsResponse(None, error=_UNREACHABLE)
        return ImdsResponse(int(status), body)

    @staticmethod
    def _parse_wget(raw: str, method: str) -> ImdsResponse:
        parsed = split_marker(raw, EXIT_MARKER)
        if not parsed:
            return ImdsResponse(None, error="wget produced no exit status; output unusable.")
        body, code = parsed
        if code == "0":
            return ImdsResponse(200, body)
        # BusyBox reports "server returned error: HTTP/1.1 401 Unauthorized".
        if status := re.search(r"HTTP/\d(?:\.\d)? (\d{3})", body):
            return ImdsResponse(int(status.group(1)), error=body.strip())
        lowered = body.lower()
        if code == "4" or any(
            hint in lowered
            for hint in ("timed out", "can't connect", "unreachable", "no route", "refused")
        ):
            return ImdsResponse(None, error=_UNREACHABLE)
        if code == "8":  # GNU wget: server error response, status not reported
            return ImdsResponse(0)
        if method != "GET":
            return ImdsResponse(
                None,
                error=f"wget failed (exit {code}); BusyBox wget does not support "
                f"--method={method}.",
            )
        return ImdsResponse(None, error=f"wget failed (exit {code}).")
