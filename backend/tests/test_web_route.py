"""Integration tests for web extraction API endpoint and error handling."""

from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from app.services.web import (
    ContentTooLargeError,
    FetchNetworkError,
    FetchTimeoutError,
    FetchedWebContent,
    SafeWebFetcher,
    UnsafeRedirectError,
    UnsupportedContentTypeError,
    get_safe_fetcher,
)

SAMPLE_HTML_PAYLOAD = """
<!DOCTYPE html>
<html>
<head><title>Test Article</title></head>
<body>
    <h1>Test Article Heading</h1>
    <p>This is a valid test paragraph containing enough characters to satisfy the minimum paragraph length rule.</p>
</body>
</html>
"""


def test_extract_endpoint_success_returns_200(app: FastAPI, client: TestClient):
    """Verify POST /api/v1/web/extract returns 200 and structured response on successful fetch."""
    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(
        return_value=FetchedWebContent(
            url="https://example.com/test",
            final_url="https://example.com/test",
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            html_content=SAMPLE_HTML_PAYLOAD,
            redirect_count=0,
        )
    )

    app.dependency_overrides[get_safe_fetcher] = lambda: mock_fetcher
    try:
        resp = client.post("/api/v1/web/extract", json={"url": "https://example.com/test"})
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        assert data["url"] == "https://example.com/test"
        assert data["final_url"] == "https://example.com/test"
        assert data["status_code"] == 200
        assert data["title"] == "Test Article"
        assert len(data["headings"]) == 1
        assert data["headings"][0]["text"] == "Test Article Heading"
        assert len(data["paragraphs"]) == 1
        assert "valid test paragraph" in data["paragraphs"][0]
        assert data["word_count"] > 10
        assert len(data["content_hash"]) == 64
    finally:
        app.dependency_overrides.pop(get_safe_fetcher, None)


def test_extract_endpoint_prohibited_ssrf_returns_400(client: TestClient):
    """Verify attempts to fetch internal/loopback/private URLs return HTTP 400 Bad Request."""
    # Loopback
    resp = client.post("/api/v1/web/extract", json={"url": "http://127.0.0.1/api/v1/health"})
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "prohibited" in resp.json()["detail"].lower()

    # Cloud Metadata
    resp_meta = client.post("/api/v1/web/extract", json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert resp_meta.status_code == status.HTTP_400_BAD_REQUEST
    assert "prohibited" in resp_meta.json()["detail"].lower()

    # Localhost
    resp_local = client.post("/api/v1/web/extract", json={"url": "http://localhost/admin"})
    assert resp_local.status_code == status.HTTP_400_BAD_REQUEST


def test_extract_endpoint_invalid_scheme_returns_400(client: TestClient):
    """Verify unsupported non-HTTP schemes return HTTP 400 Bad Request."""
    resp = client.post("/api/v1/web/extract", json={"url": "file:///etc/passwd"})
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "Only 'http://' and 'https://' are allowed" in resp.json()["detail"]


def test_extract_endpoint_unsupported_content_type_returns_422(app: FastAPI, client: TestClient):
    """Verify non-HTML content types return HTTP 422 Unprocessable Entity."""
    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(side_effect=UnsupportedContentTypeError("application/pdf"))

    app.dependency_overrides[get_safe_fetcher] = lambda: mock_fetcher
    try:
        resp = client.post("/api/v1/web/extract", json={"url": "https://example.com/doc.pdf"})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "Unsupported Content-Type" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_safe_fetcher, None)


def test_extract_endpoint_content_too_large_returns_413(app: FastAPI, client: TestClient):
    """Verify responses exceeding maximum size return HTTP 413 Payload Too Large."""
    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(side_effect=ContentTooLargeError("Exceeded 2 MB limit"))

    app.dependency_overrides[get_safe_fetcher] = lambda: mock_fetcher
    try:
        resp = client.post("/api/v1/web/extract", json={"url": "https://example.com/giant.html"})
        assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert "Exceeded 2 MB limit" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_safe_fetcher, None)


def test_extract_endpoint_timeout_returns_504(app: FastAPI, client: TestClient):
    """Verify connection or read timeouts return HTTP 504 Gateway Timeout."""
    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(side_effect=FetchTimeoutError("Connection timeout to 'slow.example.com'."))

    app.dependency_overrides[get_safe_fetcher] = lambda: mock_fetcher
    try:
        resp = client.post("/api/v1/web/extract", json={"url": "https://slow.example.com"})
        assert resp.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        assert "timeout" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_safe_fetcher, None)


def test_extract_endpoint_network_error_returns_502(app: FastAPI, client: TestClient):
    """Verify network or socket connection errors return HTTP 502 Bad Gateway."""
    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(side_effect=FetchNetworkError("Could not connect to remote host."))

    app.dependency_overrides[get_safe_fetcher] = lambda: mock_fetcher
    try:
        resp = client.post("/api/v1/web/extract", json={"url": "https://unreachable.example.com"})
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        assert "Could not connect" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_safe_fetcher, None)


def test_extract_endpoint_unsafe_redirect_returns_400(app: FastAPI, client: TestClient):
    """Verify redirect loops and insecure downgrades return HTTP 400 Bad Request."""
    mock_fetcher = MagicMock(spec=SafeWebFetcher)
    mock_fetcher.fetch = AsyncMock(
        side_effect=UnsafeRedirectError("Insecure redirect downgrade from HTTPS to HTTP is prohibited.")
    )

    app.dependency_overrides[get_safe_fetcher] = lambda: mock_fetcher
    try:
        resp = client.post("/api/v1/web/extract", json={"url": "https://downgrade.example.com"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "downgrade" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_safe_fetcher, None)


def test_openapi_schema_documents_web_extract_endpoint(client: TestClient):
    """Verify OpenAPI JSON schema includes /api/v1/web/extract documentation."""
    resp = client.get("/openapi.json")
    assert resp.status_code == status.HTTP_200_OK
    schema = resp.json()
    assert "/api/v1/web/extract" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/web/extract"]
