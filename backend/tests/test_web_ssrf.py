"""Unit tests for DNS SSRF defenses, IP range classification, and rebinding mitigations."""

from unittest.mock import patch
import pytest

from app.services.web.exceptions import SSRFBlockedError
from app.services.web.url_validator import URLValidator


def test_public_ip_passes_ssrf_checks():
    """Verify standard public Internet IP addresses pass validation."""
    public_ips = [
        "93.184.215.14",    # example.com
        "8.8.8.8",           # Google DNS
        "1.1.1.1",           # Cloudflare DNS
        "142.250.190.46",    # Google
        "2606:4700::6810:85e5",  # Cloudflare IPv6
        "2001:4860:4860::8888",  # Google Public DNS IPv6
    ]
    with patch("socket.getaddrinfo") as mock_dns:
        for ip in public_ips:
            family = 23 if ":" in ip else 2  # AF_INET6 or AF_INET
            mock_dns.return_value = [(family, 1, 6, "", (ip, 443))]
            validated = URLValidator.resolve_and_validate_all_ips("safe-site.org", 443)
            assert ip in validated


def test_reject_dns_resolving_to_private_ipv4():
    """Verify hostnames resolving to RFC 1918 private IPv4 ranges are blocked."""
    private_ips = [
        "10.0.0.5",
        "10.254.254.1",
        "172.16.0.100",
        "172.31.255.254",
        "192.168.0.1",
        "192.168.100.254",
    ]
    with patch("socket.getaddrinfo") as mock_dns:
        for ip in private_ips:
            mock_dns.return_value = [(2, 1, 6, "", (ip, 80))]
            with pytest.raises(SSRFBlockedError) as exc_info:
                URLValidator.resolve_and_validate_all_ips("private-site.internal", 80)
            assert "prohibited IP" in str(exc_info.value)


def test_reject_dns_resolving_to_loopback():
    """Verify hostnames resolving to 127.0.0.0/8 or ::1 are blocked."""
    loopback_ips = [
        "127.0.0.1",
        "127.0.0.50",
        "127.255.255.254",
        "::1",
    ]
    with patch("socket.getaddrinfo") as mock_dns:
        for ip in loopback_ips:
            family = 23 if ":" in ip else 2
            mock_dns.return_value = [(family, 1, 6, "", (ip, 80))]
            with pytest.raises(SSRFBlockedError) as exc_info:
                URLValidator.resolve_and_validate_all_ips("loopback-site.test", 80)
            assert "prohibited IP" in str(exc_info.value)


def test_reject_dns_resolving_to_cloud_metadata():
    """Verify hostnames resolving to cloud metadata endpoint (169.254.169.254) are blocked."""
    metadata_ips = [
        "169.254.169.254",  # AWS/GCP/Azure IMDS
        "169.254.170.2",    # AWS ECS Task Metadata
    ]
    with patch("socket.getaddrinfo") as mock_dns:
        for ip in metadata_ips:
            mock_dns.return_value = [(2, 1, 6, "", (ip, 80))]
            with pytest.raises(SSRFBlockedError) as exc_info:
                URLValidator.resolve_and_validate_all_ips("attacker-redirect.com", 80)
            assert "prohibited IP" in str(exc_info.value)


def test_reject_dns_resolving_to_cgnat_and_testnet():
    """Verify carrier-grade NAT (100.64.0.0/10) and TEST-NET IPs are blocked."""
    prohibited_ranges = [
        "100.64.0.1",       # CGNAT
        "100.127.255.254",  # CGNAT
        "192.0.2.1",        # TEST-NET-1
        "198.51.100.1",     # TEST-NET-2
        "203.0.113.1",      # TEST-NET-3
    ]
    with patch("socket.getaddrinfo") as mock_dns:
        for ip in prohibited_ranges:
            mock_dns.return_value = [(2, 1, 6, "", (ip, 80))]
            with pytest.raises(SSRFBlockedError) as exc_info:
                URLValidator.resolve_and_validate_all_ips("test-net.test", 80)
            assert "prohibited IP" in str(exc_info.value)


def test_reject_dns_rebinding_mixed_records():
    """Verify that if ANY returned DNS record is private, the entire request is blocked (rebinding defense)."""
    # Hostname returns one public IP and one internal loopback/metadata IP
    mixed_records = [
        (2, 1, 6, "", ("93.184.215.14", 443)),  # Public
        (2, 1, 6, "", ("127.0.0.1", 443)),      # Prohibited loopback
    ]
    with patch("socket.getaddrinfo", return_value=mixed_records):
        with pytest.raises(SSRFBlockedError) as exc_info:
            URLValidator.resolve_and_validate_all_ips("dns-rebind-exploit.com", 443)
        assert "prohibited IP '127.0.0.1'" in str(exc_info.value)


def test_reject_ipv4_mapped_ipv6_loopback_and_metadata():
    """Verify IPv4-mapped IPv6 representations of prohibited IPs are detected and blocked."""
    mapped_ips = [
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:192.168.1.1",
    ]
    with patch("socket.getaddrinfo") as mock_dns:
        for ip in mapped_ips:
            mock_dns.return_value = [(23, 1, 6, "", (ip, 80))]
            with pytest.raises(SSRFBlockedError):
                URLValidator.resolve_and_validate_all_ips("mapped-exploit.com", 80)

