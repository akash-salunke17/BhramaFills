"""Tests for CORS (Cross-Origin Resource Sharing) middleware behavior."""

from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_cors_allowed_localhost_origin(client: TestClient, test_settings: Settings) -> None:
    """Verify requests with allowed localhost:5173 origin receive CORS allow headers."""
    target_origin = "http://localhost:5173"
    response = client.get(
        f"{test_settings.API_V1_PREFIX}/health",
        headers={"Origin": target_origin},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == target_origin
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_allowed_loopback_ip_origin(client: TestClient, test_settings: Settings) -> None:
    """Verify requests with allowed 127.0.0.1:5173 origin receive CORS allow headers."""
    target_origin = "http://127.0.0.1:5173"
    response = client.get(
        f"{test_settings.API_V1_PREFIX}/health",
        headers={"Origin": target_origin},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == target_origin


def test_cors_disallowed_origin_rejected(client: TestClient, test_settings: Settings) -> None:
    """Verify requests from unauthorized origins do not receive access-control-allow-origin header."""
    disallowed_origin = "http://malicious-external-site.com"
    response = client.get(
        f"{test_settings.API_V1_PREFIX}/health",
        headers={"Origin": disallowed_origin},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_options_request(client: TestClient, test_settings: Settings) -> None:
    """Verify preflight OPTIONS request returns 200 and allowed CORS methods."""
    target_origin = "http://localhost:5173"
    response = client.options(
        f"{test_settings.API_V1_PREFIX}/health",
        headers={
            "Origin": target_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == target_origin
    assert "GET" in response.headers.get("access-control-allow-methods", "")


def test_cors_custom_origin_configuration() -> None:
    """Verify custom origins passed via Settings are respected."""
    custom_origin = "https://bharmafills-custom.internal"
    custom_settings = Settings(
        ENVIRONMENT="test",
        PROJECT_NAME="Bharmafills API (CORS Test)",
        CORS_ORIGINS=[custom_origin],
    )
    custom_app = create_app(settings=custom_settings)
    with TestClient(custom_app) as custom_client:
        response = custom_client.get(
            f"{custom_settings.API_V1_PREFIX}/health",
            headers={"Origin": custom_origin},
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == custom_origin


def test_cors_origins_do_not_default_to_wildcard() -> None:
    """Verify default CORS configuration does not allow insecure wildcard with credentials."""
    default_settings = Settings()
    assert "*" not in default_settings.CORS_ORIGINS
    assert all(origin.startswith(("http://", "https://")) for origin in default_settings.CORS_ORIGINS)
