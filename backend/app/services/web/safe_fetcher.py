"""Safe asynchronous HTTP fetcher featuring DNS pinning, streaming limits, and manual redirect validation."""

from dataclasses import dataclass
import logging
from typing import Any
import urllib.parse

import httpcore
import httpx

from app.core.config import Settings, get_settings
from app.services.web.exceptions import (
    ContentTooLargeError,
    FetchNetworkError,
    FetchTimeoutError,
    InvalidURLError,
    SSRFBlockedError,
    UnsafeRedirectError,
    UnsupportedContentTypeError,
)
from app.services.web.url_validator import URLValidator

logger = logging.getLogger("bharmafills.web.fetcher")

# Permitted response media types
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


@dataclass(frozen=True)
class FetchedWebContent:
    """Raw fetched HTML content with provenance and redirect tracking."""

    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    html_content: str
    redirect_count: int


class PinnedIPBackend(httpcore.AnyIOBackend):
    """Custom network backend that diverts TCP connect calls to a pre-validated IP address.

    Preserves original hostnames for TLS SNI extension, HTTP Host header,
    and server certificate verification, while eliminating TOCTOU DNS rebinding gaps.
    """

    def __init__(self, pinned_ip: str) -> None:
        self.pinned_ip = pinned_ip

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        logger.debug(
            "PinnedIPBackend: Diverting TCP connect for host '%s:%d' to validated IP '%s'.",
            host,
            port,
            self.pinned_ip,
        )
        return await super().connect_tcp(
            self.pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class PinnedIPTransport(httpx.AsyncHTTPTransport):
    """HTTPX Async Transport utilizing PinnedIPBackend for bulletproof SSRF protection."""

    def __init__(self, pinned_ip: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Reinitialize connection pool with our pinned backend
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=self._pool._ssl_context,
            max_connections=self._pool._max_connections,
            max_keepalive_connections=self._pool._max_keepalive_connections,
            keepalive_expiry=self._pool._keepalive_expiry,
            http1=self._pool._http1,
            http2=self._pool._http2,
            retries=self._pool._retries,
            local_address=self._pool._local_address,
            uds=self._pool._uds,
            network_backend=PinnedIPBackend(pinned_ip),
            socket_options=self._pool._socket_options,
        )


class SafeWebFetcher:
    """Performs validated HTTP fetches with manual redirect checks and streaming size limits."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def fetch(self, initial_url: str) -> FetchedWebContent:
        """Fetch URL safely following redirects manually with independent DNS validation at each hop."""
        current_url = initial_url
        visited_urls: set[str] = {current_url}
        redirect_count = 0

        max_redirects = getattr(self._settings, "WEB_FETCH_MAX_REDIRECTS", 5)
        max_bytes = getattr(self._settings, "WEB_FETCH_MAX_RESPONSE_BYTES", 2 * 1024 * 1024)
        connect_timeout = getattr(self._settings, "WEB_FETCH_TIMEOUT_CONNECT_SECONDS", 5.0)
        read_timeout = getattr(self._settings, "WEB_FETCH_TIMEOUT_READ_SECONDS", 10.0)
        user_agent = getattr(
            self._settings,
            "WEB_FETCH_USER_AGENT",
            "Bharmafills-Extractor/1.0 (+https://bharmafills.hackathon)",
        )

        while True:
            # 1. Validate URL syntax and structure
            parsed = URLValidator.validate_url(current_url)
            hostname = parsed.hostname
            if not hostname:
                raise InvalidURLError("URL is missing a valid hostname.")

            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            # 2. Resolve all DNS records and verify none are in prohibited ranges
            validated_ips = URLValidator.resolve_and_validate_all_ips(hostname, port)
            pinned_ip = validated_ips[0]

            # 3. Create pinned transport and execute request without automatic redirect following
            transport = PinnedIPTransport(pinned_ip=pinned_ip, trust_env=False)
            timeout = httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=5.0,
                pool=5.0,
            )

            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "close",
            }

            try:
                async with httpx.AsyncClient(
                    transport=transport,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    request = client.build_request("GET", current_url, headers=headers)
                    response = await client.send(request, stream=True)

                    # 4. Check for Redirects (301, 302, 303, 307, 308)
                    if response.is_redirect:
                        location = response.headers.get("Location")
                        if not location:
                            raise UnsafeRedirectError("Redirect response is missing Location header.")

                        # Close stream before following redirect
                        await response.aclose()

                        redirect_count += 1
                        if redirect_count > max_redirects:
                            raise UnsafeRedirectError(f"Exceeded maximum allowed redirects of {max_redirects}.")

                        # Resolve relative redirect locations
                        next_url = urllib.parse.urljoin(current_url, location)

                        # Detect redirect loops
                        if next_url in visited_urls:
                            raise UnsafeRedirectError(f"Redirect loop detected: '{next_url}' was already visited.")

                        # Prohibit HTTPS to HTTP downgrade
                        if current_url.startswith("https://") and next_url.startswith("http://"):
                            raise UnsafeRedirectError(
                                "Insecure redirect downgrade from HTTPS to HTTP is prohibited."
                            )

                        visited_urls.add(next_url)
                        logger.info("Following safe redirect %d: %s -> %s", redirect_count, current_url, next_url)
                        current_url = next_url
                        continue

                    # 5. Non-redirect: Validate Content-Type
                    content_type = response.headers.get("Content-Type", "").lower()
                    if not any(allowed in content_type for allowed in ALLOWED_CONTENT_TYPES):
                        await response.aclose()
                        raise UnsupportedContentTypeError(content_type or "unknown")

                    # 6. Validate Content-Length if reported
                    content_length = response.headers.get("Content-Length")
                    if content_length and content_length.isdigit():
                        if int(content_length) > max_bytes:
                            await response.aclose()
                            raise ContentTooLargeError(
                                f"Declared Content-Length of {content_length} bytes exceeds maximum {max_bytes} bytes."
                            )

                    # 7. Stream response body up to max_bytes
                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            await response.aclose()
                            raise ContentTooLargeError(
                                f"Response body exceeded maximum allowed size of {max_bytes} bytes."
                            )
                        chunks.append(chunk)

                    await response.aclose()

                    # 8. Decode HTML safely with encoding detection or utf-8 fallback
                    raw_bytes = b"".join(chunks)
                    charset = response.encoding or "utf-8"
                    try:
                        html_text = raw_bytes.decode(charset, errors="replace")
                    except Exception:
                        html_text = raw_bytes.decode("utf-8", errors="replace")

                    return FetchedWebContent(
                        url=initial_url,
                        final_url=current_url,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        html_content=html_text,
                        redirect_count=redirect_count,
                    )

            except httpx.ConnectTimeout as exc:
                raise FetchTimeoutError(f"Connection timeout to '{hostname}'.") from exc
            except httpx.ReadTimeout as exc:
                raise FetchTimeoutError(f"Read timeout while downloading from '{hostname}'.") from exc
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                logger.warning("Network connection failed for %s: %s", hostname, exc)
                raise FetchNetworkError(f"Could not connect to remote host '{hostname}'.") from exc


def get_safe_fetcher() -> SafeWebFetcher:
    """Return singleton instance of SafeWebFetcher."""
    return SafeWebFetcher()

