import hashlib

import pytest

from toboggan.core.utils.transfer import verify_md5


def test_verify_md5_accepts_matching_data():
    data = b"transferred data"

    assert verify_md5(data, hashlib.md5(data).hexdigest().upper()) is None


def test_verify_md5_accepts_unavailable_checksum():
    assert verify_md5(b"transferred data", "") is None


def test_verify_md5_accepts_invalid_checksum():
    assert verify_md5(b"transferred data", "not-a-checksum") is None


def test_verify_md5_rejects_mismatched_data():
    expected = hashlib.md5(b"expected data").hexdigest()

    with pytest.raises(ValueError, match="transferred data may be corrupted"):
        verify_md5(b"different data", expected)
