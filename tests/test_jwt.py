# tests/test_jwt.py

import base64
import json
import time

import pytest
from toboggan.core.utils.jwt import parse_jwt, TokenReader


def _build_jwt(header: dict, payload: dict, signature: bytes = b"sig") -> str:
    """Build a fake JWT from parts."""

    def b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    return ".".join(
        [
            b64url_encode(json.dumps(header).encode()),
            b64url_encode(json.dumps(payload).encode()),
            b64url_encode(signature),
        ]
    )


class TestParseJwt:
    def test_valid_token(self):
        token = _build_jwt({"alg": "RS256"}, {"sub": "user1", "exp": 9999999999})
        header, body, sig = parse_jwt(token)
        assert header["alg"] == "RS256"
        assert body["sub"] == "user1"

    def test_invalid_format_no_dots(self):
        with pytest.raises(ValueError, match="Invalid JWT format"):
            parse_jwt("notajwt")

    def test_invalid_format_two_parts(self):
        with pytest.raises(ValueError, match="Invalid JWT format"):
            parse_jwt("part1.part2")


class TestTokenReader:
    def _make_token(self, exp_offset: int = 3600, **extra_claims) -> str:
        """Create a token expiring exp_offset seconds from now."""
        now = int(time.time())
        payload = {"sub": "user1", "exp": now + exp_offset, "iss": "test-issuer"}
        payload.update(extra_claims)
        return _build_jwt({"alg": "RS256", "typ": "JWT"}, payload)

    def test_basic_properties(self):
        token_str = self._make_token(aud="https://graph.microsoft.com", scp="User.Read")
        reader = TokenReader(token_str)
        assert reader.audience == "https://graph.microsoft.com"
        assert reader.scope == "User.Read"
        assert reader.sub == "user1"
        assert reader.iss == "test-issuer"
        assert reader.access_token == token_str
        assert str(reader) == token_str

    def test_not_expired(self):
        reader = TokenReader(self._make_token(exp_offset=3600))
        assert reader.is_expired is False
        assert reader.expires_in() > 0

    def test_expired(self):
        reader = TokenReader(self._make_token(exp_offset=-3600))
        assert reader.is_expired is True
        assert reader.expires_in() == 0

    def test_expiration_datetime(self):
        reader = TokenReader(self._make_token(exp_offset=3600))
        dt = reader.expiration_datetime
        assert dt.tzinfo is not None  # Should be timezone-aware

    def test_invalid_token_raises(self):
        with pytest.raises(Exception):
            TokenReader("not.a.jwt")
