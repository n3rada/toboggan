from toboggan.core.action import BaseAction


class InternetCheckAction(BaseAction):
    DESCRIPTION = (
        "Check if the target has outbound internet access (ICMP, DNS, HTTP/HTTPS)."
    )

    def run(self) -> str:
        self._logger.info("🌐 Outbound Connectivity Check")

        # Step 1: ICMP Ping
        self._logger.info("📡 Testing ICMP (ping to 9.9.9.9)...")
        ping_cmd = None

        ping_path = self._executor.remote_execute("command -v ping")
        if ping_path:
            ping_cmd = f"{ping_path.strip()} -c 1 -W 2 9.9.9.9"
        elif (
            self._executor.os_helper.is_busybox_present
            and "ping" in self._executor.os_helper.busybox_commands
        ):
            ping_cmd = "/bin/busybox ping -c 1 -W 2 9.9.9.9"

        if ping_cmd:
            ping_result = self._executor.remote_execute(ping_cmd, timeout=5)
            if ping_result and "1 packets transmitted" in ping_result:
                self._logger.success("✅ ICMP ping to 9.9.9.9 succeeded.")
            else:
                self._logger.warning("❌ ICMP ping failed or no response.")
        else:
            self._logger.warning("⚠️ No usable ping binary found.")

        # Step 2: DNS Resolution
        hostname = "www.office.com"

        self._logger.info(f"🧠 Testing DNS resolution over: {hostname}")
        dns_cmd = None

        getent_path = self._executor.remote_execute("command -v getent")

        if getent_path:
            dns_cmd = f"{getent_path.strip()} hosts {hostname}"
        else:
            nslookup_path = self._executor.remote_execute("command -v nslookup")
            if nslookup_path:
                dns_cmd = f"{nslookup_path.strip()} {hostname}"
            else:
                host_path = self._executor.remote_execute("command -v host")
                if host_path:
                    dns_cmd = f"{host_path.strip()} {hostname}"

        if dns_cmd:
            self._logger.info(f"📦 Performing DNS resolution: {dns_cmd}")

            dns_result = self._executor.remote_execute(dns_cmd, timeout=10)

            self._logger.debug(f"🔎 DNS result: {dns_result.strip()}")

            if dns_result and any(
                keyword in dns_result.lower()
                for keyword in [hostname.lower(), "canonical name", "has address"]
            ):
                self._logger.success("✅ DNS resolution succeeded.")
            else:
                self._logger.error("❌ DNS resolution failed or no response.")
        else:
            self._logger.warning("⚠️ No usable DNS utility found.")

        # Step 3: HTTP/HTTPS
        self._logger.info("📦 Checking outbound TCP HTTP/HTTPS access")

        tool = None
        use_flags = ""

        curl_path = self._executor.remote_execute("command -v curl")
        wget_path = self._executor.remote_execute("command -v wget")

        if curl_path:
            tool = curl_path.strip()
            use_flags = "-s -o /dev/null --max-time 5"
        elif wget_path:
            tool = wget_path.strip()
            use_flags = "--timeout=5 -q -O /dev/null"
        elif (
            self._executor.os_helper.is_busybox_present
            and "wget" in self._executor.os_helper.busybox_commands
        ):
            tool = "/bin/busybox wget"
            use_flags = "--timeout=5 -q -O /dev/null"

        if not tool:
            self._logger.error("❌ No suitable HTTP tool found (curl/wget).")
        else:
            self._logger.info(f"🚀 Using {tool} for HTTP(S) connectivity tests.")
            cmd = f"{tool} {use_flags} {hostname}"
            result = self._executor.remote_execute(cmd, timeout=10)
            if (
                not result
                or "timed out" in result
                or "not resolve" in result.lower()
                or "not found" in result.lower()
            ):
                self._logger.error(f"❌ Could not reach {hostname}")
            else:
                self._logger.success(f"✅ Reached {hostname}")
