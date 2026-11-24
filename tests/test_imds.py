import json
import re

import pytest

from toboggan.core.actions.imds import common as imds
from toboggan.core.actions.imds import linux as imds_linux

TOKEN = "AQAEAFakeToken_-=="
CREDENTIALS = {
    "Code": "Success",
    "Type": "AWS-HMAC",
    "AccessKeyId": "ASIAEXAMPLE",
    "SecretAccessKey": "secret/key+value",
    "Token": "session-token",
    "Expiration": "2026-11-17T12:00:00Z",
}
TREE = {
    "meta-data/": "ami-id\niam/\npublic-keys/\n",
    "meta-data/ami-id": "ami-123",
    "meta-data/iam/": "info\nsecurity-credentials/",
    "meta-data/iam/info": json.dumps({"Code": "Success", "InstanceProfileArn": "arn:aws:iam::1:instance-profile/web"}),
    "meta-data/iam/security-credentials/": "web-role",
    "meta-data/iam/security-credentials/web-role": json.dumps(CREDENTIALS),
    "meta-data/public-keys/": "0=my-key",
    "meta-data/public-keys/0/": "openssh-key",
    "meta-data/public-keys/0/openssh-key": "ssh-rsa AAAA",
}


class FakeImds:
    """HTTP-level IMDS double: ``request(method, path, headers)``."""

    def __init__(self, tree=None, token_status=200, require_token=False, reachable=True):
        self.tree = TREE if tree is None else tree
        self.token_status = token_status
        self.require_token = require_token
        self.reachable = reachable
        self.calls = []

    def __call__(self, method, path, headers):
        self.calls.append((method, path, dict(headers)))
        if not self.reachable:
            return imds.ImdsResponse(None, error="IMDS unreachable (test).")
        if method == "PUT":
            if self.token_status != 200:
                return imds.ImdsResponse(self.token_status)
            return imds.ImdsResponse(200, TOKEN)
        if self.require_token and headers.get(imds.TOKEN_HEADER) != TOKEN:
            return imds.ImdsResponse(401)
        if path in self.tree:
            return imds.ImdsResponse(200, self.tree[path])
        return imds.ImdsResponse(404)


def curl_output(fake):
    """Turn a FakeImds into a fake target running the curl commands."""

    def execute(command, **kwargs):
        url = re.search(r"'?http://169\.254\.169\.254/latest/([^' ]*)'?", command).group(1)
        method = "PUT" if "-X PUT" in command else "GET"
        headers = dict(re.findall(r"-H '([^:]+): ([^']*)'", command))
        response = fake(method, url, headers)
        status = "000" if response.status is None else str(response.status)
        return f"{response.body}\n{imds.STATUS_MARKER}{status}"

    return execute


class StubHelper:
    def __init__(self, locations=None):
        self.locations = {"curl": "/usr/bin/curl"} if locations is None else locations
        self.lookups = []

    def get_command_location(self, command):
        self.lookups.append(command)
        return self.locations.get(command, "")


class StubExecutor:
    def __init__(self, execute=None, **helper):
        self.os_helper = StubHelper(**helper)
        self.execute = execute or (lambda command, **kwargs: "")
        self.calls = []

    def remote_execute(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.execute(command, **kwargs)


def linux_action(fake=None, **helper):
    fake = fake or FakeImds()
    return imds_linux.ImdsAction(StubExecutor(curl_output(fake), **helper)), fake


@pytest.fixture
def logs(monkeypatch):
    records = {"info": [], "warning": [], "error": [], "success": []}
    for level, messages in records.items():
        monkeypatch.setattr(imds.logger, level, messages.append)
    return records


@pytest.fixture
def non_interactive(monkeypatch):
    monkeypatch.setattr(imds, "interactive_terminal", lambda: False)


# Argument and path rules


def test_parse_options_defaults():
    assert imds.parse_options(()) == imds.ImdsOptions()


def test_parse_options_flags_and_path():
    options = imds.parse_options(("-V2", "-r", "iam/"))
    assert options == imds.ImdsOptions("v2", "iam/", True, False)


def test_parse_options_rejects_both_versions():
    with pytest.raises(ValueError, match="mutually exclusive"):
        imds.parse_options(("-v1", "-v2"))


def test_parse_options_recovers_tokens_swallowed_by_double_dash_flags():
    # "!imds --recursive iam/" and "!imds --creds -v1" as the terminal delivers them.
    assert imds.parse_options((), recursive="iam/") == imds.ImdsOptions(None, "iam/", True)
    assert imds.parse_options((), creds="-v1") == imds.ImdsOptions("v1", None, False, True)


@pytest.mark.parametrize(
    "args, kwargs",
    [(("--bogus",), {}), (("a", "b"), {}), (("iam/",), {"creds": True}), (("-r",), {"creds": True})],
)
def test_parse_options_rejects_invalid_combinations(args, kwargs):
    with pytest.raises(ValueError):
        imds.parse_options(args, **kwargs)


@pytest.mark.parametrize(
    "path, expected",
    [
        (None, "meta-data/"),
        ("iam/info", "meta-data/iam/info"),
        ("tags/instance/Name", "meta-data/tags/instance/Name"),
        ("/latest/user-data", "user-data"),
        ("/latest/dynamic/instance-identity/document", "dynamic/instance-identity/document"),
    ],
)
def test_resolve_path(path, expected):
    assert imds.resolve_path(path) == expected


@pytest.mark.parametrize("path", ["/etc/passwd", "iam/'; id", "$(id)", "a b", "../../x", "iam/`id`", "a\nb"])
def test_resolve_path_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        imds.resolve_path(path)


def test_unsafe_path_never_reaches_target(logs):
    action, _fake = linux_action()
    action.run("$(id)")
    assert action._executor.calls == []
    assert "Unsafe IMDS path" in logs["error"][0]


def test_child_entries_marks_directories_and_maps_public_keys():
    entries, skipped = imds.child_entries("meta-data/", "ami-id\niam/\n0=my-key\nbad'name\n")
    assert [(e.path, e.is_dir) for e in entries] == [
        ("meta-data/ami-id", False),
        ("meta-data/iam/", True),
        ("meta-data/0/", True),
    ]
    assert skipped == 1


# Linux command construction and version negotiation


def test_v1_get_command(capsys, non_interactive, logs):
    action, _fake = linux_action()
    action.run("-v1", "ami-id")

    assert len(action._executor.calls) == 1
    command, options = action._executor.calls[0]
    assert command.startswith("/usr/bin/curl -s --noproxy '*' --connect-timeout 2 --max-time 5")
    assert "-X PUT" not in command and "X-aws-ec2-metadata-token" not in command
    assert command.endswith("-w '\\nTBG_IMDS_STATUS:%{http_code}' http://169.254.169.254/latest/meta-data/ami-id")
    assert options["retry"] is False and options["raise_on_failure"] is True
    assert capsys.readouterr().out == "ami-123\n"


def test_v2_fetches_token_then_sends_header(capsys, non_interactive, logs):
    action, _fake = linux_action(FakeImds(require_token=True))
    action.run("-v2", "ami-id")

    put, get = [command for command, _ in action._executor.calls]
    assert "-X PUT" in put and "'X-aws-ec2-metadata-token-ttl-seconds: 21600'" in put
    assert put.endswith(" http://169.254.169.254/latest/api/token")
    assert f"-H 'X-aws-ec2-metadata-token: {TOKEN}'" in get
    assert capsys.readouterr().out == "ami-123\n"


def test_v2_token_is_reused_for_a_whole_walk(capsys, logs):
    action, fake = linux_action(FakeImds(require_token=True))
    action.run("-v2", "-r")

    methods = [method for method, _, _ in fake.calls]
    assert methods.count("PUT") == 1 and methods.count("GET") > 3
    assert "public-keys/0/openssh-key: ssh-rsa AAAA" in capsys.readouterr().out


def test_v2_token_refreshed_once_on_401():
    fake = FakeImds()
    client = imds.ImdsClient(fake, "v2")
    assert client.connect()
    client._token = "stale"
    fake.require_token = True

    assert client.get("meta-data/ami-id").body == "ami-123"
    assert [method for method, _, _ in fake.calls] == ["PUT", "GET", "PUT", "GET"]


def test_default_prefers_v2():
    fake = FakeImds()
    client = imds.ImdsClient(fake)
    assert client.connect() and client.version == "v2"


def test_default_falls_back_to_v1_with_warning(capsys, non_interactive, logs):
    action, fake = linux_action(FakeImds(token_status=403))
    action.run("ami-id")

    assert "falling back to IMDSv1" in logs["warning"][0]
    assert fake.calls[-1] == ("GET", "meta-data/ami-id", {})
    assert capsys.readouterr().out == "ami-123\n"


def test_forced_v2_does_not_fall_back(logs):
    action, fake = linux_action(FakeImds(token_status=403))
    action.run("-v2", "ami-id")

    assert [method for method, _, _ in fake.calls] == ["PUT"]
    assert "IMDSv2 token request failed" in logs["error"][0]


def test_malformed_token_is_rejected():
    client = imds.ImdsClient(lambda m, p, h: imds.ImdsResponse(200, "bad token'; id"), "v2")
    assert client.connect() is False


def test_401_is_reported_as_token_problem(non_interactive, logs):
    action, _fake = linux_action(FakeImds(require_token=True))
    action.run("-v1", "ami-id")
    assert "401" in logs["error"][0] and "-v2" in logs["error"][0]


def test_unreachable_imds_fails_fast(non_interactive, logs):
    action, _fake = linux_action(FakeImds(reachable=False))
    action.run("-v1")
    assert len(action._executor.calls) == 1
    assert "IMDS unreachable" in logs["error"][0]


def test_curl_status_000_means_unreachable():
    response = imds_linux.ImdsAction._parse_curl(f"\n{imds.STATUS_MARKER}000")
    assert response.status is None and "unreachable" in response.error


def test_curl_output_without_marker_is_rejected():
    assert imds_linux.ImdsAction._parse_curl("").status is None


def test_backend_exception_is_reported(non_interactive, logs):
    def fail(command, **kwargs):
        raise RuntimeError("down")

    action = imds_linux.ImdsAction(StubExecutor(fail))
    action.run("-v1")
    assert "RuntimeError" in logs["error"][0]


def test_requires_curl_or_wget(logs):
    action = imds_linux.ImdsAction(StubExecutor(locations={}))
    action.run("-v1")
    assert action._os_helper.lookups == ["curl", "wget"]
    assert action._executor.calls == []
    assert "curl or wget" in logs["error"][0]


def test_wget_command_construction():
    action = imds_linux.ImdsAction(StubExecutor(locations={"wget": "/bin/wget"}))
    assert action._prepare()
    command = action._command("PUT", "api/token", {imds.TOKEN_TTL_HEADER: "21600"})
    assert command.startswith("/bin/wget -q -O- -T 2 -t 1 --method=PUT ")
    assert "--header='X-aws-ec2-metadata-token-ttl-seconds: 21600'" in command
    assert command.endswith(
        'http://169.254.169.254/latest/api/token 2>&1; tbg_rc=$?; echo; echo "TBG_IMDS_EXIT:$tbg_rc"'
    )


@pytest.mark.parametrize(
    "raw, method, status, error",
    [
        ("ami-123\n\nTBG_IMDS_EXIT:0", "GET", 200, ""),
        ("wget: server returned error: HTTP/1.1 401 Unauthorized\n\nTBG_IMDS_EXIT:1", "GET", 401, "401"),
        ("\nTBG_IMDS_EXIT:4", "GET", None, "unreachable"),
        ("wget: can't connect to remote host: Connection timed out\n\nTBG_IMDS_EXIT:1", "GET", None, "unreachable"),
        ("\nTBG_IMDS_EXIT:8", "GET", 0, ""),
        ("wget: unrecognized option '--method=PUT'\n\nTBG_IMDS_EXIT:1", "PUT", None, "BusyBox"),
    ],
)
def test_wget_output_parsing(raw, method, status, error):
    response = imds_linux.ImdsAction._parse_wget(raw, method)
    assert response.status == status
    assert error in response.error
    if status == 200:
        assert response.body == "ami-123\n"


# Recursive walk and interactive dump


def test_recursive_walk_prints_leaves(capsys, logs):
    action, _fake = linux_action()
    action.run("-v1", "-r", "iam/")

    out = capsys.readouterr().out
    assert out.startswith("meta-data/iam/info: {")
    assert "meta-data/iam/security-credentials/web-role: {" in out
    assert "meta-data/ami-id" not in out


def test_walk_depth_cap():
    deep = {"meta-data/": "a/", "meta-data/a/": "b/", "meta-data/a/b/": "c", "meta-data/a/b/c": "x"}
    fake = FakeImds(deep)
    events = list(imds.walk(lambda path: fake("GET", path, {}), "meta-data/", max_depth=1))
    assert ("limit", "meta-data/a/", "depth limit (1) reached; not descending.") in events
    assert not any(kind == "value" for kind, _, _ in events)


def test_walk_entry_cap():
    def get(path):
        return FakeImds()("GET", path, {})

    events = list(imds.walk(get, "meta-data/", max_entries=3))
    assert events[-1][0] == "limit"
    assert sum(1 for kind, _, _ in events if kind in ("dir", "value")) == 3


def test_no_path_on_tty_browses_lazily(monkeypatch, logs):
    captured = {}
    monkeypatch.setattr(imds, "interactive_terminal", lambda: True)

    def fake_browse(path, loader, root_entries, title):
        captured.update(path=path, loader=loader, entries=root_entries, title=title)

    monkeypatch.setattr(imds, "browse_tree", fake_browse)
    action, fake = linux_action()
    action.run()

    assert captured["path"] == "meta-data/"
    assert captured["title"] == "IMDSv2 /latest/"
    assert ("ami-id", "meta-data/ami-id", False) in captured["entries"]
    assert ("iam", "meta-data/iam/", True) in captured["entries"]

    # Browsing is lazy: the browser was handed only the root listing, and
    # descending fetches exactly one node per call through the loader.
    loader = captured["loader"]
    before = len(fake.calls)
    children = loader.list("meta-data/iam/")
    assert ("info", "meta-data/iam/info", False) in children
    assert len(fake.calls) == before + 1
    web = loader.read("meta-data/iam/security-credentials/web-role")
    assert json.loads(web) == CREDENTIALS


def test_no_path_without_tty_prints_root_listing(capsys, non_interactive, logs):
    action, _fake = linux_action()
    action.run()
    assert capsys.readouterr().out == "ami-id\niam/\npublic-keys/\n"


def test_interactive_browse_unreachable_does_not_open(monkeypatch, logs):
    monkeypatch.setattr(imds, "interactive_terminal", lambda: True)
    monkeypatch.setattr(imds, "browse_tree", lambda *a, **k: pytest.fail("browser opened"))
    action, _fake = linux_action(FakeImds(reachable=False))
    action.run("-v1")
    assert "unreachable" in logs["error"][0]


# Credentials


def test_creds_prints_pure_json(capsys, logs):
    action, _fake = linux_action()
    action.run(creds=True)

    assert json.loads(capsys.readouterr().out) == CREDENTIALS
    assert "web-role" in logs["success"][0] and "2026-11-17T12:00:00Z" in logs["success"][0]
    assert "arn:aws:iam::1:instance-profile/web" in logs["info"][-1]


def test_creds_without_role(capsys, logs):
    tree = {k: v for k, v in TREE.items() if "security-credentials" not in k}
    action, _fake = linux_action(FakeImds(tree))
    action.run("--creds")
    assert capsys.readouterr().out == ""
    assert "No IAM role attached" in logs["warning"][0]


def test_creds_rejects_non_json_document(capsys, logs):
    tree = dict(TREE)
    tree["meta-data/iam/security-credentials/web-role"] = "<html>"
    action, _fake = linux_action(FakeImds(tree))
    action.run(creds=True)
    assert capsys.readouterr().out == ""
    assert "unexpected credentials document" in logs["error"][0]


def test_creds_profile_block_uses_role_name(capsys, logs):
    action, _fake = linux_action()
    action.run(creds=True, profile=True)

    out = capsys.readouterr().out
    assert "[web-role]" in out
    assert "aws_access_key_id = ASIAEXAMPLE" in out
    assert "aws_secret_access_key = secret/key+value" in out
    assert "aws_session_token = session-token" in out
    assert "AccessKeyId" not in out  # ini block, not JSON


def test_creds_profile_accepts_override_name(capsys, logs):
    action, _fake = linux_action()
    action.run(creds=True, profile="target")
    assert capsys.readouterr().out.startswith("[target]\n")


def test_profile_flag_implies_creds_and_parses_name():
    assert imds.parse_options((), profile=True).creds is True
    assert imds.parse_options((), profile="p") == imds.ImdsOptions(None, None, False, True, True, "p")
    with pytest.raises(ValueError, match="Invalid profile name"):
        imds.parse_options((), profile="bad name")
