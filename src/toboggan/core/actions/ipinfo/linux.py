# toboggan/src/actions/ipinfo/linux.py

# External library imports
from loguru import logger

# Local application/library specific imports
from toboggan.src.action import BaseAction


class IpInfoAction(BaseAction):
    DESCRIPTION = "Display network interfaces and IP addresses by reading /proc and /sys files (works without 'ip' command)."

    def run(self) -> str:
        """
        Retrieve network interface information by reading Linux system files directly.
        This mimics 'ip addr' output without requiring the ip command to be present.

        Returns:
            str: Formatted network interface information similar to 'ip addr' output.
        """
        logger.info("🌐 Gathering network interface information from system files")

        output_lines = []


        # Step 1: List all network interfaces
        logger.info("📋 Reading network interfaces from /sys/class/net")

        ls_command = self._os_helper.get_command_location("ls")
        ls_result = self._executor.remote_execute(f"{ls_command} -1 /sys/class/net", retry=False)

        if not ls_result:
            logger.error("❌ Could not list network interfaces")
            return "Error: Unable to read /sys/class/net"

        interfaces = [iface.strip() for iface in ls_result.strip().split('\n') if iface.strip()]
        logger.success(f"✅ Found {len(interfaces)} interface(s): {', '.join(interfaces)}")

        cat_command = self._os_helper.get_command_location("cat")

        # Step 2: Process each interface
        for iface_name in interfaces:
            logger.info(f"🔍 Analyzing interface: {iface_name}")

            # Read interface index
            idx_result = self._executor.remote_execute(f"{cat_command} /sys/class/net/{iface_name}/ifindex 2>/dev/null || echo '0'", retry=False)
            idx = idx_result.strip() if idx_result else "0"

            # Read interface state
            state_result = self._executor.remote_execute(f"{cat_command} /sys/class/net/{iface_name}/operstate 2>/dev/null || echo 'unknown'", retry=False)
            state = state_result.strip().lower() if state_result else "unknown"

            # Build flags
            flags = "<"
            if state == "up":
                flags += "UP,"
            else:
                flags += "DOWN,"
            flags += "BROADCAST,MULTICAST>"

            # Read MTU
            mtu_result = self._executor.remote_execute(f"{cat_command} /sys/class/net/{iface_name}/mtu 2>/dev/null || echo '1500'", retry=False)
            mtu = mtu_result.strip() if mtu_result else "1500"

            # Print interface header
            output_lines.append(f"{idx}: {iface_name}: {flags} mtu {mtu}")

            # Read MAC address
            mac_result = self._executor.remote_execute(f"{cat_command} /sys/class/net/{iface_name}/address", retry=False)
            if mac_result and mac_result.strip():
                mac = mac_result.strip()
                output_lines.append(f"    link/ether {mac} brd ff:ff:ff:ff:ff:ff")

            # Get IPv4 addresses - read from files only
            # Try to parse from /proc/net/fib_trie for this interface
            # Note: fib_trie doesn't directly map IPs to interfaces, so we'll show all non-loopback IPs

            # Alternative: Read /proc/net/route to find IPs associated with this interface
            route_data = self._executor.remote_execute("{cat_command} /proc/net/route", retry=False)
            if route_data:
                for route_line in route_data.strip().split('\n')[1:]:  # Skip header
                    parts = route_line.split()
                    if len(parts) >= 8 and parts[0] == iface_name:
                        # This interface has routes, try to get its IP from /proc/net/fib_trie
                        # For now, we'll note that the interface is configured
                        pass

            # Read all IPv4 addresses from ARP table as a hint (not perfect but file-based)
            # Better approach: check if we can infer from other /proc files
            # For now, skip IPv4 if we can't read from files reliably

            # Get IPv6 addresses from /proc/net/if_inet6
            ipv6_result = self._executor.remote_execute(f"grep '{iface_name}' /proc/net/if_inet6", retry=False)
            if ipv6_result:
                ipv6_count = 0
                for line in ipv6_result.strip().split('\n'):
                    if line.strip():
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            addr_hex = parts[0]
                            prefix_len = parts[2]
                            scope_hex = parts[3]

                            # Format IPv6 address with colons
                            addr_formatted = ':'.join([addr_hex[i:i+4] for i in range(0, len(addr_hex), 4)])

                            # Decode scope
                            scope_map = {'00': 'global', '20': 'link', '10': 'host'}
                            scope_text = scope_map.get(scope_hex, 'unknown')

                            output_lines.append(f"    inet6 {addr_formatted}/{prefix_len} scope {scope_text}")
                            ipv6_count += 1

            output_lines.append("")

        if not output_lines:
            logger.error("❌ No network interface information found")
            return "Error: No interfaces found"

        # Add routing table information
        logger.info("🗺️  Reading routing table from /proc/net/route")
        output_lines.append("="*70)
        output_lines.append("🗺️  ROUTING TABLE")
        output_lines.append("="*70 + "\n")

        # Read and parse /proc/net/route directly
        proc_route = self._executor.remote_execute(f"{cat_command} /proc/net/route", retry=False)
        if proc_route and proc_route.strip():
            # Parse routing table in Python
            routes = []
            lines = proc_route.strip().split('\n')

            for line in lines[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 8:
                    iface = parts[0]
                    dest_hex = parts[1]
                    gw_hex = parts[2]
                    flags_hex = parts[3]
                    metric = parts[6]
                    mask_hex = parts[7]

                    # Convert hex to IP address
                    def hex_to_ip(hex_str):
                        if len(hex_str) == 8:
                            # Reverse byte order (little-endian)
                            octets = [str(int(hex_str[i:i+2], 16)) for i in range(6, -1, -2)]
                            return '.'.join(octets)
                        return '0.0.0.0'

                    dest = hex_to_ip(dest_hex)
                    gw = hex_to_ip(gw_hex)
                    mask = hex_to_ip(mask_hex)

                    # Decode flags
                    flags = int(flags_hex, 16)
                    flag_str = ""
                    if flags & 0x0001: flag_str += "U"  # Up
                    if flags & 0x0002: flag_str += "G"  # Gateway
                    if flags & 0x0004: flag_str += "H"  # Host

                    routes.append({
                        'dest': dest,
                        'gateway': gw,
                        'mask': mask,
                        'flags': flag_str,
                        'metric': metric,
                        'iface': iface
                    })

            # Format and display routing table
            if routes:
                output_lines.append(f"{'Destination':<16} {'Gateway':<16} {'Genmask':<16} {'Flags':<6} {'Metric':<7} {'Iface'}")
                output_lines.append("-" * 80)
                for route in routes:
                    output_lines.append(
                        f"{route['dest']:<16} {route['gateway']:<16} {route['mask']:<16} "
                        f"{route['flags']:<6} {route['metric']:<7} {route['iface']}"
                    )
        else:
            logger.warning("⚠️ Could not read routing table")

        return '\n'.join(output_lines).strip()
