# tests/test_common.py

import base64
import gzip
import uuid

import pytest
from toboggan.core.utils.common import (
    base64_for_powershell,
    compress_with_gzip,
    generate_variable_length_token,
    generate_fixed_length_token,
    generate_uuid,
    is_valid_directory_path,
    is_valid_file_path,
    normalize_html_text,
    extract_html_title,
    analyze_response,
)


class TestBase64ForPowershell:
    def test_basic_command(self):
        result = base64_for_powershell("whoami")
        decoded = base64.b64decode(result).decode("utf-16le")
        assert decoded == "whoami"

    def test_unicode_command(self):
        cmd = "Get-Process | Where-Object {$_.Name -eq 'notepad'}"
        result = base64_for_powershell(cmd)
        decoded = base64.b64decode(result).decode("utf-16le")
        assert decoded == cmd

    def test_empty_string(self):
        result = base64_for_powershell("")
        decoded = base64.b64decode(result).decode("utf-16le")
        assert decoded == ""


class TestCompressWithGzip:
    def test_roundtrip(self):
        original = "echo hello world"
        compressed = compress_with_gzip(original)
        decompressed = gzip.decompress(compressed).decode("utf-8")
        assert decompressed == original

    def test_returns_bytes(self):
        result = compress_with_gzip("test")
        assert isinstance(result, bytes)


class TestTokenGeneration:
    def test_variable_length_token_range(self):
        for _ in range(50):
            token = generate_variable_length_token(3, 6)
            assert 3 <= len(token) <= 6

    def test_fixed_length_token(self):
        for length in [4, 8, 16]:
            token = generate_fixed_length_token(length)
            assert len(token) == length

    def test_uuid_format(self):
        result = generate_uuid()
        # Should be a valid UUID
        parsed = uuid.UUID(result)
        assert str(parsed) == result


class TestPathValidation:
    # Directory paths
    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/tmp", True),
            ("/var/www/html", True),
            ("relative/path", False),
            ("", False),
            ("C:\\Windows\\Temp", True),
            ("C:\\Users\\Admin", True),
            ("Windows\\Temp", False),
        ],
    )
    def test_is_valid_directory_path(self, path, expected):
        assert is_valid_directory_path(path) == expected

    # File paths
    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/tmp/file.txt", True),
            ("/var/log/app.log", True),
            ("/tmp/", False),  # Ends with /
            ("relative/file.txt", False),
            ("C:\\Windows\\Temp\\file.txt", True),
            ("C:\\Windows\\", False),  # Ends with \
        ],
    )
    def test_is_valid_file_path(self, path, expected):
        assert is_valid_file_path(path) == expected


class TestHtmlProcessing:
    def test_normalize_strips_scripts(self):
        html = "<html><script>alert(1)</script><body>Hello World</body></html>"
        result = normalize_html_text(html)
        assert "alert" not in result
        assert "hello world" in result

    def test_normalize_strips_styles(self):
        html = "<html><style>body{color:red}</style><body>Content</body></html>"
        result = normalize_html_text(html)
        assert "color" not in result
        assert "content" in result

    def test_extract_title(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        assert extract_html_title(html) == "my page"

    def test_extract_title_missing(self):
        html = "<html><body>No title</body></html>"
        assert extract_html_title(html) is None

    def test_analyze_response_blocked(self):
        assert analyze_response("Access Denied - Forbidden") is False
        assert analyze_response("Request blocked by Zscaler") is False

    def test_analyze_response_clean(self):
        assert analyze_response("<html><body>uid=33(www-data)</body></html>") is True

    def test_analyze_response_empty(self):
        assert analyze_response("") is False
        assert analyze_response(None) is False
