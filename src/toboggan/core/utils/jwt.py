# toboggan/utils/jwt.py

# Built-in imports
import base64
import json
from datetime import UTC, datetime

# External library imports
from loguru import logger


def parse_jwt(token: str) -> tuple[dict, dict, bytes]:
    """Decode JWT and return (header, body, signature)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    def b64url_decode(data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + padding)

    header = json.loads(b64url_decode(parts[0]))
    body = json.loads(b64url_decode(parts[1]))
    signature = b64url_decode(parts[2])
    return header, body, signature


class TokenReader:
    """Decode and expose the claims of a JWT access token."""

    def __init__(self, access_token: str):
        self._access_token = access_token

        try:
            self._header, self._payload, self._signature = parse_jwt(access_token)
        except Exception as e:
            logger.error(f"Failed to parse JWT: {e}")
            raise

        self._expires_on = self._payload.get("exp")

        self._iss = self._payload.get("iss")

        exp_datetime = self.expiration_datetime
        human_date = exp_datetime.strftime("%A %d %b %Y, %H:%M:%S %Z")
        logger.info(f"JWT initialized, expires at {human_date}.")

    @property
    def audience(self) -> str:
        """Return the token audience claim."""
        return self._payload.get("aud", "")

    @property
    def scope(self) -> str:
        """Return the token scope claim."""
        return self._payload.get("scp", "")

    @property
    def sub(self) -> str:
        """Return the token subject claim."""
        return self._payload.get("sub", "")

    @property
    def access_token(self) -> str:
        """Return the raw access token string."""
        return self._access_token

    @property
    def iss(self) -> str:
        """Return the token issuer claim."""
        return self._iss

    @property
    def payload(self) -> dict:
        """Return the full decoded JWT payload."""
        return self._payload

    @property
    def expiration_datetime(self) -> datetime:
        """Return the token expiration as a timezone-aware datetime."""
        return datetime.fromtimestamp(self._expires_on, tz=UTC)

    @property
    def is_expired(self) -> bool:
        """Return True if the token has expired."""
        return datetime.now(UTC).timestamp() > self._expires_on

    def expires_in(self) -> int:
        """Return the number of seconds until the token expires."""
        return max(0, int(self._expires_on - datetime.now(UTC).timestamp()))

    def __str__(self) -> str:
        return self._access_token
