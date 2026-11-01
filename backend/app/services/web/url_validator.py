"""Secure URL validation and comprehensive SSRF defense engine."""

import ipaddress
import logging
import socket
import urllib.parse

import idna

from app.services.web.exceptions import InvalidURLError, SSRFBlockedError

logger = logging.getLogger("bharmafills.web.validator")

# Supported web schemes
ALLOWED_SCHEMES = frozenset(["http", "https"])

# Supported standard web ports
ALLOWED_PORTS = frozenset([80, 443, 8080, 8443])

# Additional non-global or sensitive network networks that must never be accessed
PROHIBITED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),          # Current network (only valid as source)
    ipaddress.ip_network("10.0.0.0/8"),          # RFC 1918 Private IPv4
    ipaddress.ip_network("100.64.0.0/10"),       # RFC 6598 Carrier Grade NAT
    ipaddress.ip_network("127.0.0.0/8"),        # RFC 1122 Loopback
    ipaddress.ip_network("169.254.0.0/16"),      # RFC 3927 Link-Local / Cloud Metadata
    ipaddress.ip_network("172.16.0.0/12"),       # RFC 1918 Private IPv4
    ipaddress.ip_network("192.0.0.0/24"),        # RFC 6890 IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),        # RFC 5737 TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),      # RFC 1918 Private IPv4
    ipaddress.ip_network("198.18.0.0/15"),       # RFC 2544 Network Interconnect Benchmark
    ipaddress.ip_network("198.51.100.0/24"),     # RFC 5737 TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),      # RFC 5737 TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # RFC 5771 Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # RFC 1112 Reserved
    ipaddress.ip_network("255.255.255.255/32"),  # RFC 919 Limited Broadcast
    # IPv6 prohibited ranges
    ipaddress.ip_network("::1/128"),             # Loopback
    ipaddress.ip_network("::/128"),              # Unspecified
    ipaddress.ip_network("64:ff9b:1::/48"),      # Local-Use IPv4/IPv6 Translation
    ipaddress.ip_network("100::/64"),            # Discard-Only Address Block
    ipaddress.ip_network("2001:db8::/32"),       # Documentation IPv6
    ipaddress.ip_network("fc00::/7"),            # Unique Local Unicast (ULA)
    ipaddress.ip_network("fe80::/10"),           # Link-Local Unicast
    ipaddress.ip_network("ff00::/8"),            # Multicast
]

# Prohibited hostnames that are strictly rejected without needing DNS lookup
PROHIBITED_HOSTNAMES = frozenset([
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "instance-data",
])


class URLValidator:
    """Validates URLs and performs strict SSRF IP range checks."""

    @classmethod
    def validate_url(cls, url: str) -> urllib.parse.ParseResult:
        """Parse and strictly validate URL syntax, scheme, credentials, and port."""
        if not url or not isinstance(url, str):
            raise InvalidURLError("URL must be a non-empty string.")

        cleaned_url = url.strip()
        if len(cleaned_url) > 2048:
            raise InvalidURLError("URL exceeds maximum length of 2048 characters.")

        # Reject control characters, newlines, and carriage returns
        if any(c in cleaned_url for c in ["\r", "\n", "\t", "\0"]):
            raise InvalidURLError("URL contains prohibited control characters.")

        try:
            parsed = urllib.parse.urlsplit(cleaned_url)
        except Exception as exc:
            raise InvalidURLError(f"Malformed URL: {exc}") from exc

        # 1. Scheme Validation
        scheme = parsed.scheme.lower()
        if not scheme:
            raise InvalidURLError("URL is missing scheme. Only 'http://' and 'https://' are allowed.")
        if scheme not in ALLOWED_SCHEMES:
            raise InvalidURLError(f"Unsupported scheme '{scheme}'. Only 'http://' and 'https://' are allowed.")

        # 2. Hostname Validation
        raw_host = parsed.hostname
        if not raw_host:
            raise InvalidURLError("URL is missing a valid hostname.")

        # Reject embedded credentials
        if parsed.username or parsed.password:
            raise InvalidURLError("URLs with embedded userinfo credentials are not permitted.")

        # Reject IPv6 zone identifiers (e.g. fe80::1%eth0)
        if "%" in raw_host:
            raise InvalidURLError("IPv6 zone identifiers are prohibited in URL hostnames.")

        # 3. Port Validation
        port = parsed.port
        if port is not None and port not in ALLOWED_PORTS:
            raise InvalidURLError(f"Port {port} is not permitted. Only standard web ports are allowed.")

        # 4. Direct IP Literal Check (if host is an IPv4 or IPv6 literal)
        is_ip = cls._check_direct_ip_literal(raw_host)

        # 5. Hostname Normalization & IDN Encoding (if not an IP literal)
        if not is_ip:
            cls._normalize_and_check_hostname(raw_host)

        return parsed

    @classmethod
    def _normalize_and_check_hostname(cls, raw_host: str) -> str:
        """Check for prohibited hostnames, single-label local names, and convert IDNs."""
        host_lower = raw_host.lower().strip(".")
        if not host_lower:
            raise InvalidURLError("URL hostname is empty or invalid.")

        if host_lower in PROHIBITED_HOSTNAMES:
            raise SSRFBlockedError(f"Access to prohibited hostname '{raw_host}' is blocked.")

        # Reject single-label local network names (e.g. 'intranet', 'router', 'corp')
        if "." not in host_lower:
            raise SSRFBlockedError(f"Single-label local network hostname '{raw_host}' is prohibited.")

        # Handle Internationalized Domain Names (IDN) via Punycode
        try:
            ascii_host = idna.encode(host_lower).decode("ascii")
            return ascii_host
        except Exception as exc:
            raise InvalidURLError(f"Invalid domain name encoding in '{raw_host}': {exc}") from exc

    @classmethod
    def _check_direct_ip_literal(cls, host: str) -> bool:
        """If hostname is an IP literal, immediately inspect against prohibited ranges.

        Returns True if host is a valid IP literal, False otherwise.
        Raises SSRFBlockedError if IP is in prohibited ranges.
        """
        # Strip brackets from IPv6 literal if present (e.g. [::1] -> ::1)
        cleaned_host = host.strip("[]")
        try:
            ip = ipaddress.ip_address(cleaned_host)
            if cls.is_ip_prohibited(ip):
                raise SSRFBlockedError(f"Access to prohibited IP address '{host}' is blocked by policy.")
            return True
        except ValueError:
            # Not an IP literal, proceed to hostname checks and DNS resolution
            return False

    @classmethod
    def is_ip_prohibited(cls, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """Determine whether an IP address is private, loopback, link-local, or prohibited."""
        # Check IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            return cls.is_ip_prohibited(ip.ipv4_mapped)

        # Standard Python ipaddress classification checks
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
            or not ip.is_global
        ):
            return True

        # Check against explicitly enumerated sensitive networks
        for network in PROHIBITED_NETWORKS:
            if ip in network:
                return True

        return False

    @classmethod
    def resolve_and_validate_all_ips(cls, hostname: str, port: int) -> list[str]:
        """Resolve all A and AAAA DNS records and reject if ANY returned address is prohibited.

        Returns list of validated public IP strings.
        Raises SSRFBlockedError if any returned IP address fails security checks.
        """
        try:
            # Query all IPv4 and IPv6 TCP addresses for target host
            addr_info = socket.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except socket.gaierror as exc:
            logger.warning("DNS resolution failed for hostname %s: %s", hostname, exc)
            raise InvalidURLError(f"Unable to resolve hostname '{hostname}'.") from exc

        if not addr_info:
            raise InvalidURLError(f"DNS resolution returned no addresses for '{hostname}'.")

        validated_ips: list[str] = []
        for info in addr_info:
            sockaddr = info[4]
            ip_str = sockaddr[0]

            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError as exc:
                raise SSRFBlockedError(f"DNS returned unparseable IP address '{ip_str}'.") from exc

            # If ANY resolved IP is prohibited, reject the entire destination!
            if cls.is_ip_prohibited(ip_obj):
                logger.warning(
                    "SSRF check triggered: Hostname '%s' resolved to prohibited IP '%s'.",
                    hostname,
                    ip_str,
                )
                raise SSRFBlockedError(
                    f"Destination hostname '{hostname}' resolved to prohibited IP '{ip_str}'."
                )

            if ip_str not in validated_ips:
                validated_ips.append(ip_str)

        return validated_ips
