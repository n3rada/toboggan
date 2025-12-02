# toboggan/utils/jwt.py

# Built-in imports
import json
import base64
from datetime import datetime, timezone

# External library imports
from loguru import logger


def parse_jwt(token: str) -> tuple[dict, dict, bytes]:
    """Decode JWT and return (header, body, signature)"""
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
    def __init__(self, access_token: str):
        self._access_token = access_token

        try:
            self._header, self._payload, self._signature = parse_jwt(access_token)
        except Exception as e:
            logger.error(f"❌ Failed to parse JWT: {e}")
            raise

        self._expires_on = self._payload.get("exp")

        self._iss = self._payload.get("iss")

        exp_datetime = self.expiration_datetime
        human_date = exp_datetime.strftime("%A %d %b %Y, %H:%M:%S %Z")
        logger.info(f"🔐 JWT initialized, expires at {human_date}.")

    @property
    def audience(self) -> str:
        return self._payload.get("aud", "")

    @property
    def scope(self) -> str:
        return self._payload.get("scp", "")

    @property
    def sub(self) -> str:
        return self._payload.get("sub", "")

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def iss(self) -> str:
        return self._iss

    @property
    def payload(self) -> dict:
        return self._payload

    @property
    def expiration_datetime(self) -> datetime:
        return datetime.fromtimestamp(self._expires_on, tz=timezone.utc)

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc).timestamp() > self._expires_on

    def expires_in(self) -> int:
        return max(0, int(self._expires_on - datetime.now(timezone.utc).timestamp()))

    def __str__(self) -> str:
        return self._access_token
