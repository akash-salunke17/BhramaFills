"""Unit tests for URL syntax validation and direct SSRF rejection."""

import pytest

from app.services.web.exceptions import InvalidURLError, SSRFBlockedError
from app.services.web.url_validator import URLValidator


def test_valid_http_and_https_urls_accepted():
    """Verify standard public HTTP and HTTPS URLs are accepted and parsed."""
    valid_urls = [
        "https://example.com",
        "http://example.org/path/to/page",
        "https://subdomain.example.co.uk/search?q=test&lang=en#section",
        "https://api.github.com:443/repos",
        "http://news.bbc.co.uk:80/world",
    ]
    for url in valid_urls:
        parsed = URLValidator.validate_url(url)
        assert parsed.scheme in ("http", "https")
        assert parsed.hostname is not None


def test_reject_unsupported_schemes():
    """Verify non-HTTP schemes are strictly rejected."""
    forbidden = [
        "file:///etc/passwd",
        "ftp://ftp.example.com/files",
        "gopher://gopher.example.com",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "javascript:alert(1)",
        "mailto:test@example.com",
        "ldap://localhost/dc=example,dc=com",
        "dict://dict.org",
    ]
    for url in forbidden:
        with pytest.raises(InvalidURLError) as exc_info:
            URLValidator.validate_url(url)
        assert "Only 'http://' and 'https://' are allowed" in str(exc_info.value)


def test_reject_empty_and_oversized_urls():
    """Verify empty strings, None, and over-2048 character URLs are rejected."""
    with pytest.raises(InvalidURLError):
        URLValidator.validate_url("")

    with pytest.raises(InvalidURLError):
        URLValidator.validate_url("   ")

    oversized = "https://example.com/" + ("a" * 2050)
    with pytest.raises(InvalidURLError) as exc_info:
        URLValidator.validate_url(oversized)
    assert "exceeds maximum length" in str(exc_info.value)


def test_reject_control_characters_in_url():
    """Verify newline and control character injection attempts are rejected."""
    bad_urls = [
        "https://example.com/path\r\nHeader: injected",
        "https://example.com/test\0evil",
        "https://example.com/tab\ttest",
    ]
    for url in bad_urls:
        with pytest.raises(InvalidURLError) as exc_info:
            URLValidator.validate_url(url)
        assert "control characters" in str(exc_info.value)


def test_reject_embedded_credentials():
    """Verify URLs with embedded username or password are rejected."""
    urls = [
        "https://user:password@example.com",
        "http://admin@example.org/dashboard",
        "https://:secret@example.com/path",
    ]
    for url in urls:
        with pytest.raises(InvalidURLError) as exc_info:
            URLValidator.validate_url(url)
        assert "userinfo credentials" in str(exc_info.value)


def test_reject_unsupported_ports():
    """Verify non-web ports like SSH, SMTP, and databases are rejected."""
    urls = [
        "http://example.com:22",
        "http://example.com:25",
        "http://example.com:3306",
        "http://example.com:5432",
        "https://example.com:6379",
        "http://example.com:9200",
    ]
    for url in urls:
        with pytest.raises(InvalidURLError) as exc_info:
            URLValidator.validate_url(url)
        assert "is not permitted" in str(exc_info.value)


def test_reject_prohibited_hostnames():
    """Verify localhost and cloud metadata hostnames are blocked immediately."""
    hostnames = [
        "http://localhost",
        "http://localhost:80",
        "http://localhost.localdomain",
        "http://ip6-localhost",
        "http://metadata.google.internal",
        "http://instance-data",
    ]
    for url in hostnames:
        with pytest.raises(SSRFBlockedError):
            URLValidator.validate_url(url)


def test_reject_single_label_local_hostnames():
    """Verify internal intranet single-label hostnames without dots are blocked."""
    internal = [
        "http://intranet",
        "http://router",
        "http://nas",
        "http://devserver",
    ]
    for url in internal:
        with pytest.raises(SSRFBlockedError) as exc_info:
            URLValidator.validate_url(url)
        assert "Single-label local network hostname" in str(exc_info.value)


def test_reject_private_and_loopback_ip_literals():
    """Verify direct IP literals targeting private, loopback, or metadata ranges are blocked."""
    prohibited_ips = [
        "http://127.0.0.1",
        "http://127.0.0.2:80",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0",
        "http://[::1]",
        "http://[fc00::1]",
        "http://[fe80::1]",
        "http://[::ffff:127.0.0.1]",
        "http://[::ffff:169.254.169.254]",
    ]
    for url in prohibited_ips:
        with pytest.raises(SSRFBlockedError):
            URLValidator.validate_url(url)


def test_reject_ipv6_zone_identifiers():
    """Verify IPv6 zone indices like %eth0 are strictly rejected."""
    with pytest.raises(InvalidURLError) as exc_info:
        URLValidator.validate_url("http://[fe80::1%eth0]/")
    assert "zone identifiers" in str(exc_info.value)


def test_accept_and_normalize_idn_domain():
    """Verify Internationalized Domain Names are properly Punycode-encoded."""
    url = "https://münchen.de/kultur"
    parsed = URLValidator.validate_url(url)
    assert parsed.hostname == "xn--mnchen-3ya.de" or parsed.hostname == "münchen.de"

