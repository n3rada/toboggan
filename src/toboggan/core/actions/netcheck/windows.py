# toboggan/core/actions/netcheck/windows.py

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.core.action import BaseAction
from toboggan.core.utils import common


class InternetCheckAction(BaseAction):
    DESCRIPTION = (
        "Check if the target has outbound internet access (ICMP, DNS, HTTP/HTTPS)."
    )

    def run(self, ip: str = "9.9.9.9", hostname: str = "www.office.com") -> str:
        logger.info("🌐 Outbound Connectivity Check")

        # Step 1: ICMP Ping
        logger.info(f"📡 Testing ICMP (ping to {ip})")
        
        if self._os_helper.shell_type == "powershell":
            # Try Test-NetConnection first (more modern and reliable)
            ping_cmd = f"$ProgressPreference='SilentlyContinue'; (tnc {ip} -IL Quiet -WA 0).ToString()"
            ping_result = self._executor.remote_execute(ping_cmd, timeout=10, retry=False)
            
            if ping_result and "True" in ping_result:
                logger.success(f"✅ ICMP ping to {ip} succeeded.")
            else:
                # Fallback to Test-Connection
                logger.info("⚙️ Falling back to Test-Connection")
                ping_cmd = f"(Test-Connection {ip} -Count 1 -Quiet -EA 0).ToString()"
                ping_result = self._executor.remote_execute(ping_cmd, timeout=10, retry=False)
                
                if ping_result and "True" in ping_result:
                    logger.success(f"✅ ICMP ping to {ip} succeeded.")
                else:
                    logger.warning("❌ ICMP ping failed or no response.")
        else:
            # CMD - use standard ping command
            ping_cmd = f"ping -n 1 -w 2000 {ip}"
            ping_result = self._executor.remote_execute(ping_cmd, timeout=5, retry=False)
            
            if ping_result and ("bytes=32" in ping_result or "TTL=" in ping_result):
                logger.success(f"✅ ICMP ping to {ip} succeeded.")
            else:
                logger.warning("❌ ICMP ping failed or no response.")

        # Step 2: DNS Resolution
        logger.info(f"🧠 Testing DNS resolution over: {hostname}")

        if self._os_helper.shell_type == "powershell":
            # Try Resolve-DnsName first (most reliable)
            # Filter for A records only and get IP4Address property (works for all record types)
            dns_cmd = f"$ProgressPreference='SilentlyContinue'; (Resolve-DnsName {hostname} -Type A -EA 0 | ? {{$_.Type -eq 'A'}} | select -First 1 -exp IP4Address)"
            dns_result = self._executor.remote_execute(dns_cmd, timeout=10, retry=False)
            
            if dns_result and dns_result.strip() and "error" not in dns_result.lower() and "cannot be found" not in dns_result.lower():
                logger.success("✅ DNS resolution succeeded.")
                logger.debug(f"🔎 DNS result: {dns_result.strip()}")
            else:
                # Fallback to nslookup
                logger.info("⚙️ Falling back to nslookup")
                dns_cmd = f"nslookup -timeout=2 {hostname}"
                dns_result = self._executor.remote_execute(dns_cmd, timeout=10, retry=False)
                
                if dns_result and ("Address:" in dns_result or "Addresses:" in dns_result):
                    logger.success("✅ DNS resolution succeeded.")
                    logger.debug(f"🔎 DNS result: {dns_result.strip()}")
                else:
                    logger.error("❌ DNS resolution failed")
        else:
            # CMD - use nslookup with DNS server
            dns_cmd = f"nslookup -timeout=2 {hostname} 8.8.8.8"
            dns_result = self._executor.remote_execute(dns_cmd, timeout=10, retry=False)
            
            if dns_result and ("Name:" in dns_result or "Address:" in dns_result):
                logger.success("✅ DNS resolution succeeded.")
                logger.debug(f"🔎 DNS result: {dns_result.strip()}")
            else:
                logger.error("❌ DNS resolution failed or no response.")

        # Step 3: HTTP/HTTPS
        logger.info("📦 Checking outbound TCP HTTP(S) access")
        url = f"https://{hostname}"

        if self._os_helper.shell_type == "powershell":
            # Try Invoke-RestMethod first (most reliable)
            logger.info("⚙️ Using Invoke-RestMethod")
            web_cmd = f"$ProgressPreference='SilentlyContinue'; try {{ irm '{url}' -TimeoutSec 10 -EA Stop }} catch {{ 'FAILED' }}"
            web_result = self._executor.remote_execute(web_cmd, timeout=15, retry=False)
            
            if web_result and web_result.strip() and "FAILED" not in web_result:
                # Analyze response for captive portal or blocks
                if common.analyze_response(web_result):
                    logger.success(f"✅ Successfully connected to {url}")
                else:
                    logger.error("❌ Blocked, proxied or captive portal detected")
            else:
                # Fallback to WebClient
                logger.info("⚙️ Falling back to WebClient")
                web_cmd = f"$ProgressPreference='SilentlyContinue'; try {{ [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $w = New-Object Net.WebClient; $w.DownloadString('{url}') }} catch {{ 'FAILED' }}"
                web_result = self._executor.remote_execute(web_cmd, timeout=15, retry=False)
                
                if web_result and web_result.strip() and "FAILED" not in web_result:
                    if common.analyze_response(web_result):
                        logger.success(f"✅ Successfully connected to {url}")
                    else:
                        logger.error("❌ Blocked, proxied or captive portal detected")
                else:
                    logger.error(f"❌ Failed to connect to {url}")
        else:
            # CMD - invoke PowerShell command
            logger.info("⚙️ Using PowerShell WebClient via CMD")
            web_cmd = f"powershell -nop -c \"$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try {{ $w = New-Object Net.WebClient; $w.DownloadString('{url}') }} catch {{ 'FAILED' }}\""
            web_result = self._executor.remote_execute(web_cmd, timeout=15, retry=False)
            
            if web_result and web_result.strip() and "FAILED" not in web_result:
                if common.analyze_response(web_result):
                    logger.success(f"✅ Successfully connected to {url}")
                else:
                    logger.error("❌ Blocked, proxied or captive portal detected")
            else:
                logger.error(f"❌ Failed to connect to {url}")
