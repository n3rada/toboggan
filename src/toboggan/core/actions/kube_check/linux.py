# Built-in imports
import ipaddress
import json
import re
import shlex
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils.jwt import parse_jwt

JsonObject = dict[str, Any]
PermissionGroup = tuple[tuple[str, ...], list[str], tuple[str, ...], tuple[str, ...]]


class KubeCheckAction(BaseAction):
    DESCRIPTION = "Enumerate Kubernetes identity, permissions, and pod configuration."
    SERVICE_ACCOUNT_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
    POD_PAGE_SIZE = 50
    MAX_POD_PAGES = 3

    def run(self) -> None:
        logger.info("Kubernetes pod enumeration")
        self._cat = self._os_helper.get_command_location("cat")
        if not self._cat:
            logger.warning("No usable cat command found.")
            return
        token = self._read_file("token")
        if not token or token.startswith("cat:"):
            logger.warning("No Kubernetes service account token found.")
            return
        try:
            _, claims, _ = parse_jwt(token)
            if not isinstance(claims, dict):
                raise TypeError("JWT payload is not an object")
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning(f"Could not decode token claims: {exc}")
            claims = {}
        self._summarize_token(claims)

        namespace = self._namespace(claims)
        if not namespace or not self._prepare_api():
            return
        logger.info(f"Namespace: {namespace}; API: {self._api}")
        self._review_identity(claims.get("sub"))

        # SelfSubjectRulesReview reports the authenticated caller's allowed API
        # operations without trying each one individually.
        # https://kubernetes.io/docs/reference/access-authn-authz/authorization/#checking-api-access
        rules = self._request(
            "/apis/authorization.k8s.io/v1/selfsubjectrulesreviews",
            "Permission review",
            {
                "apiVersion": "authorization.k8s.io/v1",
                "kind": "SelfSubjectRulesReview",
                "spec": {"namespace": namespace},
            },
            kind="SelfSubjectRulesReview",
        )
        if rules is not None:
            self._summarize_rules(rules)

        # Bound tokens record the Pod identity under this Kubernetes claim.
        # https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/#bound-service-account-token-volume-mechanism
        kube_claims = self._mapping(claims.get("kubernetes.io"))
        pod_claim = self._mapping(kube_claims.get("pod"))
        pod = self._find_pod(namespace, pod_claim.get("name"), pod_claim.get("uid"))
        if pod:
            self._summarize_pod(pod)
        else:
            logger.warning("Current Pod configuration unavailable.")

    def _namespace(self, claims: JsonObject) -> str | None:
        kube_claims = self._mapping(claims.get("kubernetes.io"))
        claimed = kube_claims.get("namespace") or claims.get(
            "kubernetes.io/serviceaccount/namespace"
        )
        namespace = self._read_file("namespace")
        if self._valid_namespace(namespace):
            if claimed and claimed != namespace:
                logger.warning("Namespace file differs from the token claim.")
            return namespace
        if self._valid_namespace(claimed):
            logger.warning("Namespace file unavailable; using the token claim.")
            return claimed
        logger.warning("No valid namespace found; not assuming default.")
        return None

    def _prepare_api(self) -> bool:
        printf = self._os_helper.get_command_location("printf")
        curl = self._os_helper.get_command_location("curl")
        if not printf or not curl:
            logger.warning("Kubernetes API checks require printf and curl.")
            return False
        try:
            environment = self._executor.remote_execute(
                f'{printf} "%s\\n%s" "$KUBERNETES_SERVICE_HOST" '
                '"${KUBERNETES_SERVICE_PORT_HTTPS:-${KUBERNETES_SERVICE_PORT:-443}}"',
                retry=False, raise_on_failure=True, debug=False,
            ).strip().splitlines()
        except Exception as exc:  # user-defined execution backends
            logger.warning(
                f"Cannot read Kubernetes API environment: {type(exc).__name__}."
            )
            return False
        self._api = self._api_server(*environment) if len(environment) == 2 else None
        if not self._api:
            logger.warning("Kubernetes API address unavailable or invalid.")
            return False
        # https://kubernetes.io/docs/tasks/run-application/access-api-from-pod/
        self._curl = (
            f"{curl} -sS --connect-timeout 3 --max-time 10 "
            f"--cacert {shlex.quote(self.SERVICE_ACCOUNT_DIR + '/ca.crt')} "
            '-H "Authorization: Bearer '
            f'$({self._cat} {shlex.quote(self.SERVICE_ACCOUNT_DIR + "/token")})"'
        )
        return True

    @staticmethod
    def _mapping(value: Any) -> JsonObject:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _text(value: Any) -> str:
        """Keep remote values on one line."""
        encoded = json.dumps(value, sort_keys=True)
        if isinstance(value, str) and value and value == value.strip():
            return encoded[1:-1]
        return encoded

    def _read_file(self, name: str) -> str:
        try:
            return self._executor.remote_execute(
                f"{self._cat} {shlex.quote(self.SERVICE_ACCOUNT_DIR + '/' + name)}",
                retry=False, raise_on_failure=True, debug=False,
            ).strip()
        except Exception as exc:  # user-defined execution backends
            logger.warning(f"Cannot read service account {name}: {type(exc).__name__}.")
            return ""

    @staticmethod
    def _valid_namespace(value: Any) -> bool:
        return isinstance(value, str) and bool(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value)
        )

    @staticmethod
    def _api_server(host: str, port: str) -> str | None:
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return None
        if ":" in host:
            try:
                host = f"[{ipaddress.IPv6Address(host.strip('[]'))}]"
            except ValueError:
                return None
        elif not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            return None
        return f"https://{host}:{port}"

    def _request(
        self, path: str, label: str, payload: JsonObject | None = None, *, kind: str
    ) -> JsonObject | None:
        """One remote call per request; distinguish HTTP and transport failures."""
        method = "POST" if payload is not None else "GET"
        url = self._api + path
        command = self._curl
        if payload is not None:
            command += (
                " -H 'Content-Type: application/json' -X POST"
                f" -d {shlex.quote(json.dumps(payload))}"
            )
        command += f" {shlex.quote(url)}"
        logger.info(f"API command (raw JSON): {command}")
        try:
            raw = self._executor.remote_execute(
                command + " -w '\\n%{http_code}'",
                timeout=15, retry=False, raise_on_failure=True, debug=False,
            )
        except Exception as exc:  # user-defined execution backends
            logger.warning(f"{label}: request failed ({type(exc).__name__}).")
            return None
        body, separator, status = raw.rstrip("\r\n").rpartition("\n")
        if not separator or not re.fullmatch(r"\d{3}", status):
            logger.warning(f"{label}: HTTP status unavailable.")
            return None
        if status == "000":
            logger.warning(f"{label}: transport failure before an HTTP response.")
            return None
        try:
            response = json.loads(body)
        except ValueError:
            response = None
        if not 200 <= int(status) < 300:
            reason = self._mapping(response).get("reason")
            detail = f" ({self._text(reason)})" if reason else ""
            logger.warning(f"{label}: HTTP {status}{detail}.")
            return None
        if not isinstance(response, dict):
            logger.warning(f"{label}: expected a JSON object.")
            return None
        if response.get("kind") != kind:
            logger.warning(
                f"{label}: expected {kind}, got {self._text(response.get('kind'))}."
            )
            return None
        logger.success(f"{label}: {method} {url} - HTTP {status}.")
        return response

    def _summarize_token(self, claims: JsonObject) -> None:
        if not claims:
            return
        logger.info(
            "Token subject (decoded, unverified): "
            f"{self._text(claims.get('sub', 'unavailable'))}"
        )
        details = [
            f"{label}: {self._text(claims[key])}"
            for key, label in (("iss", "issuer"), ("aud", "audience"))
            if key in claims
        ]
        if details:
            logger.info(f"Token claims: {'; '.join(details)}")
        expiry = claims.get("exp")
        if expiry is None:
            return
        try:
            if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
                raise TypeError("not a numeric timestamp")
            expires = datetime.fromtimestamp(expiry, UTC)
        except (TypeError, ValueError, OverflowError, OSError):
            logger.warning("Token expiry is invalid.")
            return
        if expires <= datetime.now(UTC):
            logger.warning(f"Token expired at {expires:%Y-%m-%d %H:%M:%S} UTC.")
        else:
            logger.info(f"Token expires at {expires:%Y-%m-%d %H:%M:%S} UTC.")

    def _review_identity(self, subject: Any) -> None:
        response = self._request(
            "/apis/authentication.k8s.io/v1/selfsubjectreviews",
            "Identity review",
            {"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview"},
            kind="SelfSubjectReview",
        )
        if response is None:
            return
        status = self._mapping(response.get("status"))
        user = self._mapping(status.get("userInfo"))
        if not user.get("username"):
            logger.warning(
                "Identity review returned no username; API identity unconfirmed."
            )
            return
        logger.info(f"API identity: {self._text(user['username'])}")
        if subject and subject != user["username"]:
            logger.warning("API identity differs from the token subject.")

    @staticmethod
    def _group_rules(rules: list[JsonObject]) -> list[PermissionGroup]:
        """Merge identical grants without broadening group or name restrictions."""
        grants = {}
        for rule in rules:
            groups = tuple(sorted(set(rule.get("apiGroups", []))))
            names = tuple(sorted(set(rule.get("resourceNames", []))))
            for resource in rule.get("resources", []):
                grants.setdefault((groups, resource, names), set()).update(
                    rule.get("verbs", [])
                )
        grouped = {}
        for (groups, resource, names), verbs in sorted(grants.items()):
            grouped.setdefault((groups, tuple(sorted(verbs)), names), []).append(
                resource
            )
        return [
            (groups, resources, verbs, names)
            for (groups, verbs, names), resources in grouped.items()
        ]

    @staticmethod
    def _batches(items: Iterable[str]) -> Iterator[str]:
        batch = []
        for item in items:
            if batch and len(", ".join(batch + [item])) > 100:
                yield ", ".join(batch)
                batch = []
            batch.append(item)
        if batch:
            yield ", ".join(batch)

    def _summarize_rules(self, review: JsonObject) -> None:
        status = self._mapping(review.get("status"))
        if status.get("incomplete") is not False:
            logger.warning(
                "Permission review is incomplete or completeness is unknown."
            )
        if status.get("evaluationError"):
            logger.warning(
                f"Permission review error: {self._text(status['evaluationError'])}"
            )
        grouped = self._group_rules(status.get("resourceRules", []))
        if not grouped:
            logger.info("No resource permissions reported.")
        for groups, resources, verbs, names in grouped:
            label = ", ".join(group or "core" for group in groups) or "unknown group"
            restriction = f"; names: {', '.join(names)}" if names else ""
            for batch in self._batches(resources):
                logger.info(
                    f"Permission [{label}]: {batch} - {', '.join(verbs)}{restriction}"
                )
        for rule in status.get("nonResourceRules", []):
            verbs = ", ".join(rule.get("verbs", []))
            for batch in self._batches(rule.get("nonResourceURLs", [])):
                logger.info(f"Permission [non-resource URLs]: {batch} - {verbs}")

    def _find_pod(self, namespace: str, name: Any, uid: Any) -> JsonObject | None:
        path = f"/api/v1/namespaces/{quote(namespace, safe='')}/pods"
        if isinstance(name, str) and name:
            pod = self._request(
                f"{path}/{quote(name, safe='')}", "Current Pod", kind="Pod"
            )
            if pod is not None:
                metadata = pod.get("metadata", {})
                if metadata.get("name") == name and (
                    not uid or metadata.get("uid") == uid
                ):
                    return pod
                logger.warning("Pod name/UID does not match token claim.")
                return None
        continuation = ""
        for _ in range(self.MAX_POD_PAGES):
            query = {"limit": self.POD_PAGE_SIZE}
            # All resources support metadata.name; filter when a bound token gave us
            # the Pod name so a bounded fallback cannot miss it in a busy namespace.
            # https://kubernetes.io/docs/concepts/overview/working-with-objects/field-selectors/
            if isinstance(name, str) and name:
                query["fieldSelector"] = f"metadata.name={name}"
            if continuation:
                query["continue"] = continuation
            page = self._request(
                f"{path}?{urlencode(query)}", "Namespace pod list", kind="PodList"
            )
            if page is None:
                return None
            current = None
            for pod in page.get("items", []):
                metadata = pod.get("metadata", {})
                matches = (
                    (name or uid)
                    and (not name or metadata.get("name") == name)
                    and (not uid or metadata.get("uid") == uid)
                )
                if matches:
                    current = pod
                else:
                    logger.info(
                        f"Pod: {self._text(metadata.get('name'))} "
                        f"({self._text(pod.get('status', {}).get('phase', 'unknown'))})"
                    )
            if current:
                return current
            continuation = page.get("metadata", {}).get("continue", "")
            if not continuation:
                return None
        logger.warning("Pod listing reached the page limit; results are partial.")
        return None

    def _summarize_pod(self, pod: JsonObject) -> None:
        metadata, spec, status = (
            pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {}),
        )
        logger.info(
            f"Pod: {self._text(metadata.get('name'))} "
            f"({self._text(status.get('phase', 'unknown'))})"
        )
        context = [
            f"service account {self._text(spec.get('serviceAccountName', 'default'))}"
        ]
        context.extend(
            f"owner {self._text(owner.get('kind'))}/{self._text(owner.get('name'))}"
            for owner in metadata.get("ownerReferences", [])
        )
        scc = self._mapping(metadata.get("annotations")).get("openshift.io/scc")
        if scc:
            context.append(f"SCC {self._text(scc)}")
        logger.info("; ".join(context))
        logger.info(
            f"Node: {self._text(spec.get('nodeName', 'unknown'))} "
            f"({self._text(status.get('hostIP', 'unknown'))}); "
            f"pod IP: {self._text(status.get('podIP', 'unknown'))}"
        )
        shared = [
            key
            for key in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace")
            if spec.get(key)
        ]
        if shared:
            logger.warning(f"Shared namespaces: {', '.join(shared)}")
        volumes = {item.get("name"): item for item in spec.get("volumes", [])}
        pod_security = self._mapping(spec.get("securityContext"))
        for kind, status_key, label in (
            ("containers", "containerStatuses", "Container"),
            ("initContainers", "initContainerStatuses", "Init container"),
            (
                "ephemeralContainers", "ephemeralContainerStatuses",
                "Ephemeral container",
            ),
        ):
            runtime = {item.get("name"): item for item in status.get(status_key, [])}
            for container in spec.get(kind, []):
                self._summarize_container(
                    label, container, runtime.get(container.get("name"), {}),
                    pod_security, volumes,
                )

    def _summarize_container(
        self, label: str, container: JsonObject, runtime: JsonObject,
        pod_security: JsonObject, volumes: dict[str, JsonObject],
    ) -> None:
        name = self._text(container.get("name", "unknown"))
        state = self._mapping(runtime.get("state"))
        security = self._mapping(container.get("securityContext"))
        run_as_user = security.get("runAsUser", pod_security.get("runAsUser"))
        phase = next(iter(state), "state unavailable")
        uid = f"; configured UID {run_as_user}" if run_as_user is not None else ""
        logger.info(
            f"{label} {name}: {self._text(container.get('image', 'unknown image'))} "
            f"({phase}{uid})"
        )
        waiting = self._mapping(state.get("waiting"))
        terminated = self._mapping(state.get("terminated"))
        if waiting.get("reason"):
            starting = waiting["reason"] in ("ContainerCreating", "PodInitializing")
            log = logger.info if starting else logger.warning
            log(f"{name}: {self._text(waiting['reason'])}")
        elif terminated.get("exitCode", 0) != 0:
            logger.warning(
                f"{name}: exited with code {self._text(terminated['exitCode'])}"
            )
        risks = []
        if security.get("privileged"):
            risks.append("privileged")
        if run_as_user == 0:
            risks.append("configured to run as root")
        # The API default is true; report it unless the Pod explicitly disables it.
        # https://kubernetes.io/docs/tasks/configure-pod-container/security-context/
        if security.get("allowPrivilegeEscalation") is not False:
            risks.append("privilege escalation not disabled")
        if security.get("procMount") == "Unmasked":
            risks.append("unmasked proc filesystem")
        added = self._mapping(security.get("capabilities")).get("add")
        if added:
            risks.append(f"added capabilities {self._text(added)}")
        if risks:
            logger.warning(f"{name}: {'; '.join(risks)}")
        for mount in container.get("volumeMounts", []):
            volume = volumes.get(mount.get("name"), {})
            kind = next((key for key in volume if key != "name"), "unknown")
            config = self._mapping(volume.get(kind))
            # VolumeMount.readOnly defaults to false (read-write).
            # https://kubernetes.io/docs/reference/kubernetes-api/core/pod-v1/#VolumeMount
            read_only = (
                mount.get("readOnly") is True or config.get("readOnly") is True
                or kind in ("secret", "configMap", "projected", "downwardAPI")
            )
            access = "read-only" if read_only else "read-write"
            propagation = mount.get("mountPropagation")
            if propagation:
                access += f"; {propagation} propagation"
            log = (
                logger.warning
                if kind == "hostPath" or propagation == "Bidirectional"
                else logger.info
            )
            log(
                f"{name} mount {self._text(mount.get('mountPath'))}: "
                f"{self._volume_source(kind, config)} ({access})"
            )

    def _volume_source(self, kind: str, config: JsonObject) -> str:
        references = {
            "secret": ("Secret", "secretName"),
            "configMap": ("ConfigMap", "name"),
            "persistentVolumeClaim": ("PVC", "claimName"),
            "hostPath": ("host path", "path"),
            "csi": ("CSI driver", "driver"),
        }
        if kind in references:
            label, key = references[kind]
            return f"{label} {self._text(config.get(key, 'unknown'))}"
        if kind == "projected":
            sources = []
            for source in config.get("sources", []):
                if "serviceAccountToken" in source:
                    sources.append("service account token")
                elif "secret" in source or "configMap" in source:
                    key = "secret" if "secret" in source else "configMap"
                    sources.append(f"{key} {self._text(source[key].get('name'))}")
                elif "downwardAPI" in source:
                    sources.append("pod metadata")
                else:
                    sources.append(self._text(source))
            return "projected: " + ", ".join(sources)
        return kind
