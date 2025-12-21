# toboggan/core/handlers/burpsuite.py

# Built-in imports
import base64
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

# Third-party library
import httpx
from loguru import logger


class BurpRequest:
    """Handles Burp Suite saved request files and allows execution."""

    def __init__(self, request_path: str):
        """Initialize Burp request parsing."""
        self.__request_path = Path(request_path)
        
        # Validate file exists
        if not self.__request_path.exists():
            raise FileNotFoundError(f"❌ File not found: {self.__request_path}")
        
        # Validate it's a file
        if not self.__request_path.is_file():
            raise ValueError(f"❌ Path is not a file: {self.__request_path}")
        
        # Validate file is readable and not empty
        try:
            self.__request_content = self.__request_path.read_text(encoding="utf-8", errors="ignore")
            if not self.__request_content.strip():
                raise ValueError(f"❌ File is empty: {self.__request_path}")
        except Exception as e:
            raise ValueError(f"❌ Cannot read file {self.__request_path}: {e}")
        
        # Parse and validate request
        self.__parsed_request = self.__parse_request()
        
        # Validate ||cmd|| placeholder exists
        if not self.__has_placeholder():
            raise ValueError(
                f"❌ Request does not contain '||cmd||' placeholder. "
                "Add ||cmd|| in URL, headers, or body where command should be injected."
            )

    def __parse_request(self) -> dict:
        """Parses the XML file and extracts the first request."""
        try:
            tree = ET.parse(self.__request_path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"❌ Invalid XML format in Burp Suite file: {e}")
        except Exception as e:
            raise ValueError(f"❌ Failed to parse XML: {e}")
        
        item = root.find("item")  # Only take the first request

        if item is None:
            raise ValueError(
                "❌ No valid <item> found in Burp Suite file. "
                "Ensure you saved a request from Burp Suite (right-click → Save item)."
            )

        # Extract required fields with validation
        method = item.findtext("method")
        url = item.findtext("url")
        host = item.findtext("host")
        port = item.findtext("port")
        protocol = item.findtext("protocol")
        
        # Validate required fields
        if not method:
            raise ValueError("❌ Missing HTTP method in Burp request")
        if not url:
            raise ValueError("❌ Missing URL in Burp request")
        
        request_element = item.find("request")
        if request_element is None or request_element.text is None:
            raise ValueError("❌ Missing request data in Burp Suite file")
        
        request_raw = request_element.text.strip()
        if not request_raw:
            raise ValueError("❌ Empty request data in Burp Suite file")

        # Check if request is base64-encoded
        is_base64 = request_element.get("base64", "false") == "true"

        # Decode request
        try:
            if is_base64:
                request_decoded = base64.b64decode(request_raw).decode("utf-8", errors="replace")
            else:
                request_decoded = request_raw
        except Exception as e:
            raise ValueError(f"❌ Failed to decode request data: {e}")

        # Extract headers and body
        headers, body = self.__split_headers_body(request_decoded)

        return {
            "method": method.upper(),  # Normalize to uppercase
            "url": url,
            "host": host or "",
            "port": port or "",
            "protocol": protocol or "https",
            "headers": headers,
            "body": body,
        }

    def __split_headers_body(self, raw_request):
        """Splits raw HTTP request into headers and body."""
        # Try different line ending formats (CRLF, LF)
        if "\r\n\r\n" in raw_request:
            parts = raw_request.split("\r\n\r\n", 1)
            line_sep = "\r\n"
        elif "\n\n" in raw_request:
            parts = raw_request.split("\n\n", 1)
            line_sep = "\n"
        else:
            # No body separator found
            parts = [raw_request]
            line_sep = "\r\n" if "\r\n" in raw_request else "\n"
        
        headers = parts[0].split(line_sep) if len(parts) > 0 else []
        # Filter out request line (first line) and empty lines
        headers = [h for h in headers[1:] if h.strip()]  # Skip first line (GET /path HTTP/1.1)
        
        body = parts[1] if len(parts) > 1 else ""
        return headers, body
    
    def __has_placeholder(self) -> bool:
        """Check if ||cmd|| placeholder exists in request."""
        placeholder = "||cmd||"
        
        # Check in URL
        if placeholder in self.__parsed_request["url"]:
            return True
        
        # Check in headers
        for header in self.__parsed_request["headers"]:
            if placeholder in header:
                return True
        
        # Check in body
        if placeholder in self.__parsed_request["body"]:
            return True
        
        return False

    def replace_command(self, command: str, url_encode: bool = True) -> dict:
        """Replaces ||cmd|| in the request URL, headers, and body with the command.
        
        Args:
            command: The command to inject
            url_encode: Whether to URL-encode the command (default: True)
        
        Returns:
            Modified request dictionary
        """
        if not command:
            raise ValueError("❌ Command cannot be empty")
        
        # Optionally URL-encode the command (useful for URL/query params)
        processed_command = quote(command, safe='') if url_encode else command
        
        modified_request = self.__parsed_request.copy()
        modified_request["headers"] = self.__parsed_request["headers"].copy()

        # Replace in URL
        if "||cmd||" in modified_request["url"]:
            modified_request["url"] = modified_request["url"].replace("||cmd||", processed_command)
            logger.debug(f"Injected command into URL: {modified_request['url']}")

        # Replace in headers (don't URL-encode in headers)
        modified_headers = []
        for header in modified_request["headers"]:
            if "||cmd||" in header:
                # Don't URL-encode in headers, use raw command
                modified_headers.append(header.replace("||cmd||", command))
                logger.debug(f"Injected command into header: {header}")
            else:
                modified_headers.append(header)
        modified_request["headers"] = modified_headers

        # Replace in body (don't URL-encode in body unless it's form data)
        if "||cmd||" in modified_request["body"]:
            # Check if it's form data (application/x-www-form-urlencoded)
            is_form_data = any("application/x-www-form-urlencoded" in h.lower() 
                             for h in modified_request["headers"])
            
            if is_form_data:
                modified_request["body"] = modified_request["body"].replace("||cmd||", processed_command)
            else:
                modified_request["body"] = modified_request["body"].replace("||cmd||", command)
            
            logger.debug(f"Injected command into body (form_data={is_form_data})")

        return modified_request

    # Properties
    @property
    def request_content(self) -> dict:
        return self.__request_content


# Global instance that will be set dynamically
BURP_REQUEST_OBJECT = None


def execute(command: str, timeout: float = None) -> str:
    """Executes a Burp request by injecting the command.
    
    Args:
        command: The command to execute remotely
        timeout: Request timeout in seconds (default: 30.0)
    
    Returns:
        Response text from the server
    
    Raises:
        ValueError: If BURP_REQUEST_OBJECT is not set or command is invalid
        httpx.HTTPError: If request fails
    """
    if BURP_REQUEST_OBJECT is None:
        raise ValueError("❌ BURP_REQUEST_OBJECT is not set. This should not happen.")
    
    if not command:
        raise ValueError("❌ Command cannot be empty")
    
    # Set default timeout
    if timeout is None:
        timeout = 30.0
    
    try:
        # Extract request details and inject command
        parsed_request = BURP_REQUEST_OBJECT.replace_command(command)
    except Exception as e:
        raise ValueError(f"❌ Failed to prepare request: {e}")

    # Parse headers from list to dict
    headers = {}
    for line in parsed_request["headers"]:
        if ": " in line:
            key, value = line.split(": ", 1)
            headers[key.strip()] = value.strip()
        else:
            logger.warning(f"⚠️ Skipping malformed header: {line}")

    # Prepare body
    body = parsed_request["body"]
    body_bytes = body.encode("utf-8") if body else None
    
    # Update Content-Length if body exists
    if body_bytes:
        headers["Content-Length"] = str(len(body_bytes))
    elif "Content-Length" in headers:
        # Remove Content-Length if no body
        del headers["Content-Length"]

    try:
        # Execute request
        response = httpx.request(
            method=parsed_request["method"],
            url=parsed_request["url"],
            headers=headers,
            content=body_bytes,  # Use content instead of data for bytes
            follow_redirects=True,
            verify=False,  # Disable SSL verification (common for pentest)
            timeout=timeout,
        )
        
        # Raise for HTTP errors (4xx, 5xx)
        response.raise_for_status()
        
        return response.text
    
    except httpx.TimeoutException:
        raise TimeoutError(f"❌ Request timed out after {timeout}s")
    except httpx.HTTPStatusError as e:
        logger.warning(f"⚠️ HTTP error {e.response.status_code}: {e.response.reason_phrase}")
        # Return response text even on HTTP errors (command might have executed)
        return e.response.text
    except httpx.RequestError as e:
        raise ConnectionError(f"❌ Request failed: {e}")
    except Exception as e:
        raise RuntimeError(f"❌ Unexpected error during request: {e}")

