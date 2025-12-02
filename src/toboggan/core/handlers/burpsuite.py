# Built-in imports
import base64
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

# Third-party library
import httpx


class BurpRequest:
    """Handles Burp Suite saved request files and allows execution."""

    def __init__(self, request_path: str):
        """Initialize Burp request parsing."""
        self.__request_path = Path(request_path)
        if not self.__request_path.exists():
            raise FileNotFoundError(f"❌ File not found: {self.__request_path}")

        self.__request_content = self.__request_path.read_text(encoding="utf-8", errors="ignore")
        self.__parsed_request = self.__parse_request()

    def __parse_request(self) -> dict:
        """Parses the XML file and extracts the first request."""
        tree = ET.parse(self.__request_path)
        root = tree.getroot()
        item = root.find("item")  # Only take the first request

        if item is None:
            raise ValueError("❌ No valid request found in the Burp Suite file.")

        method = item.findtext("method")
        url = item.findtext("url")
        host = item.findtext("host")
        port = item.findtext("port")
        protocol = item.findtext("protocol")
        request_raw = item.findtext("request")

        # Check if request is base64-encoded
        is_base64 = item.find("request").get("base64", "false") == "true"

        # Decode request
        request_decoded = base64.b64decode(request_raw).decode("utf-8", errors="ignore") if is_base64 else request_raw

        # Extract headers and body
        headers, body = self.__split_headers_body(request_decoded)

        return {
            "method": method,
            "url": url,
            "host": host,
            "port": port,
            "protocol": protocol,
            "headers": headers,
            "body": body,
        }

    def __split_headers_body(self, raw_request):
        """Splits raw HTTP request into headers and body."""
        parts = raw_request.split("\r\n\r\n", 1)
        headers = parts[0].split("\r\n") if len(parts) > 0 else []
        body = parts[1] if len(parts) > 1 else ""
        return headers, body

    def replace_command(self, command: str) -> None:
        """Replaces ||cmd|| in the request URL, headers, and body with a URL-encoded command."""
        encoded_command = quote(command)
        modified_request = self.__parsed_request.copy()

        # Replace in URL
        if "||cmd||" in modified_request["url"]:
            modified_request["url"] = modified_request["url"].replace("||cmd||", encoded_command)

        # Replace in headers
        modified_headers = []
        for header in modified_request["headers"]:
            modified_headers.append(header.replace("||cmd||", encoded_command))
        modified_request["headers"] = modified_headers

        # Replace in body
        if "||cmd||" in modified_request["body"]:
            modified_request["body"] = modified_request["body"].replace("||cmd||", encoded_command)

        return modified_request

    # Properties
    @property
    def request_content(self) -> dict:
        return self.__request_content


# Global instance that will be set dynamically
BURP_REQUEST_OBJECT = None


def execute(command: str, timeout: float = None) -> str:
    """Executes a Burp request by injecting the command."""
    if BURP_REQUEST_OBJECT is None:
        raise ValueError("❌ BURP_REQUEST_OBJECT is not set.")
    # Extract request details
    parsed_request = BURP_REQUEST_OBJECT.replace_command(command)

    headers = {
        line.split(": ", 1)[0]: line.split(": ", 1)[1]
        for line in parsed_request["headers"] if ": " in line
    }

    # Ensure Content-Length is correctly set
    body = parsed_request["body"]
    if body:
        headers["Content-Length"] = str(len(body.encode("utf-8")))  # Ensure it's a valid length

    response = httpx.request(
        parsed_request["method"].upper(),
        parsed_request["url"],
        headers=headers,
        data=body.encode("utf-8") if body else None,  # Ensure body is sent as bytes
        follow_redirects=True,
        verify=False,
        timeout=timeout,
    )

    return response.text

