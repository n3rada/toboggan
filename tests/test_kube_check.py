import pytest

from toboggan.core.actions.kube_check import linux as kube_check


class StubHelper:
    def __init__(self, locations=None):
        self.locations = (
            locations
            if locations is not None
            else {
                "cat": "/usr/bin/cat",
                "curl": "/usr/bin/curl",
                "printf": "/usr/bin/printf",
            }
        )
        self.lookups = []

    def get_command_location(self, command):
        self.lookups.append(command)
        return self.locations.get(command, "")


class StubExecutor:
    def __init__(self, execute=None, locations=None):
        self.os_helper = StubHelper(locations)
        self.execute = execute or (lambda command, **kwargs: "")
        self.calls = []

    def remote_execute(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.execute(command, **kwargs)


def action(execute=None, locations=None):
    return kube_check.KubeCheckAction(StubExecutor(execute, locations))


def test_prepare_api_uses_resolved_linux_commands():
    target = action(lambda command, **kwargs: "10.96.0.1\n443")
    target._cat = target._os_helper.get_command_location("cat")

    assert target._prepare_api() is True
    command, options = target._executor.calls[-1]
    assert command.startswith('/usr/bin/printf "%s\\n%s"')
    assert "$(/usr/bin/cat /var/run/secrets/kubernetes.io/serviceaccount/token)" in target._curl
    assert target._os_helper.lookups == ["cat", "printf", "curl"]
    assert options["retry"] is False
    assert options["raise_on_failure"] is True


def test_read_file_uses_discovered_cat_and_propagates_backend_failures():
    target = action(lambda command, **kwargs: "namespace-a")
    target._cat = target._os_helper.get_command_location("cat")

    assert target._read_file("namespace") == "namespace-a"
    command, options = target._executor.calls[-1]
    assert command.startswith("/usr/bin/cat ")
    assert options["retry"] is False
    assert options["raise_on_failure"] is True


def test_run_stops_when_cat_is_unavailable():
    def unexpected_execute(command, **kwargs):
        raise AssertionError("target should not be called without cat")

    target = action(unexpected_execute, locations={})

    assert target.run() is None
    assert target._os_helper.lookups == ["cat"]


def test_request_propagates_backend_failures_for_classification(monkeypatch):
    def fail(command, **kwargs):
        raise RuntimeError("transport failed")

    target = action(fail)
    target._api = "https://10.96.0.1:443"
    target._curl = "/usr/bin/curl"
    warnings = []
    monkeypatch.setattr(kube_check.logger, "warning", warnings.append)

    assert target._request("/api/v1/pods", "Pods", kind="PodList") is None
    assert "request failed (RuntimeError)" in warnings[-1]
    assert target._executor.calls[-1][1]["raise_on_failure"] is True


def test_known_pod_fallback_filters_by_name(monkeypatch):
    target = action()

    def request(path, label, payload=None, *, kind):
        if kind == "Pod":
            return None
        assert "fieldSelector=metadata.name%3Dpod-a" in path
        return {
            "kind": "PodList",
            "metadata": {},
            "items": [{"metadata": {"name": "pod-a", "uid": "uid-a"}}],
        }

    monkeypatch.setattr(target, "_request", request)
    pod = target._find_pod("namespace-a", "pod-a", "uid-a")

    assert pod["metadata"]["uid"] == "uid-a"


def test_permission_grouping_preserves_api_group_and_name_restrictions():
    groups = kube_check.KubeCheckAction._group_rules(
        [
            {
                "apiGroups": [""],
                "resources": ["secrets"],
                "resourceNames": ["named-secret"],
                "verbs": ["get"],
            },
            {
                "apiGroups": [""],
                "resources": ["secrets"],
                "verbs": ["list"],
            },
            {
                "apiGroups": ["apps"],
                "resources": ["deployments"],
                "verbs": ["get"],
            },
        ]
    )

    assert len(groups) == 3
    assert any(group == ("",) and names == ("named-secret",) for group, _, _, names in groups)
    assert any(group == ("apps",) for group, _, _, _ in groups)


def test_host_path_without_read_only_is_reported_as_read_write(monkeypatch):
    target = action()
    warnings = []
    monkeypatch.setattr(kube_check.logger, "warning", warnings.append)

    target._summarize_container(
        "Container",
        {
            "name": "worker",
            "image": "image",
            "securityContext": {"allowPrivilegeEscalation": False},
            "volumeMounts": [{"name": "host", "mountPath": "/host"}],
        },
        {},
        {},
        {"host": {"name": "host", "hostPath": {"path": "/"}}},
    )

    assert any("host path / (read-write)" in message for message in warnings)


def test_unspecified_allow_privilege_escalation_is_reported(monkeypatch):
    target = action()
    warnings = []
    monkeypatch.setattr(kube_check.logger, "warning", warnings.append)

    target._summarize_container(
        "Container", {"name": "worker", "image": "image"}, {}, {}, {}
    )

    assert any("privilege escalation not disabled" in message for message in warnings)


@pytest.mark.parametrize(
    "host, port, expected",
    [
        ("10.96.0.1", "443", "https://10.96.0.1:443"),
        ("fd00::1", "443", "https://[fd00::1]:443"),
        ("api.internal", "6443", "https://api.internal:6443"),
        ("bad host", "443", None),
        ("10.96.0.1", "70000", None),
    ],
)
def test_api_server_validation(host, port, expected):
    assert kube_check.KubeCheckAction._api_server(host, port) == expected
