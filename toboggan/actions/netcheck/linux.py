# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.action import BaseAction


class InternetCheckAction(BaseAction):
    DESCRIPTION = (
        "Check if the target has outbound internet access (ICMP, DNS, HTTP/HTTPS)."
    )

    def run(self, ip: str = "9.9.9.9", hostname: str = "www.office.com") -> str:
        logger.info("🌐 Outbound Connectivity Check")

        # Step 1: ICMP Ping
        logger.info(f"📡 Testing ICMP (ping to {ip})")
        ping_cmd = None

        ping_path = self._executor.remote_execute("command -v ping")
        if ping_path:
            ping_cmd = f"{ping_path.strip()} -c 1 -W 2 {ip}"
        elif (
            self._executor.os_helper.is_busybox_present
            and "ping" in self._executor.os_helper.busybox_commands
        ):
            ping_cmd = f"/bin/busybox ping -c 1 -W 2 {ip}"

        if ping_cmd:
            ping_result = self._executor.remote_execute(ping_cmd, timeout=5)
            if ping_result and "1 packets transmitted" in ping_result:
                logger.success(f"✅ ICMP ping to {ip} succeeded.")
            else:
                logger.warning("❌ ICMP ping failed or no response.")
        else:
            logger.warning("⚠️ No usable ping binary found.")

        # Step 2: DNS Resolution
        logger.info(f"🧠 Testing DNS resolution over: {hostname}")

        tool = None
        use_flags = ""

        if getent_path := self._executor.remote_execute("command -v getent"):
            tool = getent_path.strip()
            use_flags = "hosts"

        elif nslookup_path := self._executor.remote_execute("command -v nslookup"):
            tool = nslookup_path.strip()
        elif host_path := self._executor.remote_execute("command -v host"):
            tool = host_path.strip()
        else:
            logger.warning("⚠️ No usable DNS utility found.")

        if tool:
            logger.info(f"⚙️ Using {tool}")
            dns_result = self._executor.remote_execute(
                f"{tool} {use_flags} {hostname}", timeout=10
            )

            logger.debug(f"🔎 DNS result: {dns_result.strip()}")

            if dns_result and any(
                keyword in dns_result.lower()
                for keyword in [hostname.lower(), "canonical name", "has address"]
            ):
                logger.success("✅ DNS resolution succeeded.")
            else:
                logger.error("❌ DNS resolution failed or no response.")

        # Step 3: HTTP/HTTPS
        logger.info("📦 Checking outbound TCP HTTP(S) access")

        tool = None
        use_flags = ""

        if curl_path := self._executor.remote_execute("command -v curl"):
            tool = curl_path.strip()
            use_flags = "-Ik"
        elif wget_path := self._executor.remote_execute("command -v wget"):
            tool = wget_path.strip()
            use_flags = "--spider"
        elif (
            self._executor.os_helper.is_busybox_present
            and "wget" in self._executor.os_helper.busybox_commands
        ):
            tool = "/bin/busybox wget"
            use_flags = "--spider"

        if not tool:
            logger.error("❌ No suitable HTTP tool found (curl/wget).")
        else:
            logger.info(f"⚙️ Using {tool}")
            cmd = f"{tool} {use_flags} {hostname}"
            result = self._executor.remote_execute(cmd, timeout=10, retry=False)
            if (
                not result
                or "timed out" in result
                or "not resolve" in result.lower()
                or "not found" in result.lower()
            ):
                logger.error(f"❌ Could not reach {hostname}")
            else:
                logger.success(f"✅ Reached {hostname}")
