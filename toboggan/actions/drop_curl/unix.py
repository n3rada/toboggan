from toboggan.core.action import BaseAction
from toboggan.actions.drop_binary.unix import DropBinary
from toboggan.utils import binaries


class DropCurlAction(BaseAction):
    DESCRIPTION = (
        "Upload a statically built cURL binary to the target if not already present."
    )

    def run(self, dest_directory: str = "/bin") -> None:
        # Check if curl is available
        if curl_path := self._executor.remote_execute("command -v curl", debug=False):
            self._logger.success(
                f"✅ curl is already available on the target: {curl_path.strip()}"
            )
            return

        self._logger.info("🔎 Uploading static cURL")

        # Locate local curl binary
        curl_bin = binaries.BinaryManager(os="unix").get("curl")
        if curl_bin is None:
            self._logger.error("❌ Local curl binary not found in toboggan binaries.")
            return

        # Upload via parent method
        DropBinary(self._executor).run(
            local_path=str(curl_bin.path), remote_path=f"{dest_directory}/curl"
        )
