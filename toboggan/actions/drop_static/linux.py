from toboggan.core.action import BaseAction
from toboggan.actions.drop_bin.linux import DropBinary
from toboggan.utils.binaries import BinaryFetcher


class DropStaticBinary(BaseAction):
    DESCRIPTION = f"Drop a prebuilt static binary to the target within this list: {BinaryFetcher.list_available()}."

    def run(self, name: str = None, remote_path: str = None) -> None:
        if not name:
            self._logger.warning("⚠️ No binary name provided.")
            available = BinaryFetcher.list_available()
            print("📦 Available static binaries:")
            for b in available:
                print(f"  • {b}")
            return

        os = self._executor.target.os.lower()
        arch = self._executor.target.architecture or "x86_64"

        try:
            fetcher = BinaryFetcher(os=os, arch=arch)
            local_path = fetcher.get(name)
        except Exception as e:
            self._logger.error(f"❌ Failed to fetch binary: {e}")
            return

        if not local_path or not local_path.exists():
            self._logger.error("❌ Binary download failed or path invalid.")
            return

        DropBinary(self._executor).run(
            local_path=str(local_path),
            remote_path=remote_path,
        )
