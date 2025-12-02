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
        if self._os_helper.shell_type == "powershell":
            ping_cmd = f"tnc {ip} -Count 1 -InformationLevel Quiet"
        else:
            ping_cmd = f"ping -n 1 -w 2000 {ip}"  # 2000ms timeout

        ping_result = self._executor.remote_execute(ping_cmd, timeout=5)
        if ping_result:
            if "True" in ping_result or "bytes=32" in ping_result:
                logger.success(f"✅ ICMP ping to {ip} succeeded.")
            else:
                logger.warning("❌ ICMP ping failed or no response.")

        # Step 2: DNS Resolution
        logger.info(f"🧠 Testing DNS resolution over: {hostname}")

        if self._os_helper.shell_type == "powershell":
            dns_cmd = (
                f"resolve-dnsname {hostname} -Type A -EA 0 | select -exp IPAddress"
            )
        else:
            # More reliable nslookup command for CMD with timeout and specific DNS server
            dns_cmd = f"nslookup -timeout=2 {hostname} 8.8.8.8"

        dns_result = self._executor.remote_execute(dns_cmd, timeout=10)
        if dns_result:
            if self._os_helper.shell_type == "powershell":
                success = len(dns_result.strip()) > 0
            else:
                success = "Name:" in dns_result or "Address:" in dns_result

            if success:
                logger.success("✅ DNS resolution succeeded.")
                logger.debug(f"🔎 DNS result:\n {dns_result.strip()}")
            else:
                logger.error("❌ DNS resolution failed")
        else:
            logger.error("❌ No response from DNS query")

        # Step 3: HTTP/HTTPS
        logger.info("📦 Checking outbound TCP HTTP(S) access")
        url = f"https://{hostname}"

        if self._os_helper.shell_type == "powershell":
            # Using Invoke-RestMethod with maximum timeout of 10 seconds
            web_cmd = f"$ProgressPreference = 'SilentlyContinue'; try {{ irm '{url}' -Method Head -TimeoutSec 10; 'Success' }} catch {{ $_.Exception.Message }}"
        else:
            # Using native PowerShell web client via cmd (stealthier approach)
            web_cmd = f"powershell -nop -c \"$ProgressPreference='SilentlyContinue'; try {{ $web=New-Object Net.WebClient; $web.DownloadString('{url}'); 'Success' }} catch {{ 'Failed' }}\""

        web_result = self._executor.remote_execute(web_cmd, timeout=15, retry=False)

        if web_result and "Success" in web_result:
            logger.success(f"✅ Successfully connected to {url}")
        else:
            logger.error(f"❌ Failed to connect to {url}")
