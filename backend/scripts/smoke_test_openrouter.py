"""OpenRouter live smoke test for Bharmafills.

Usage (manual execution only):
    .\\backend\\venv\\Scripts\\python.exe backend\\scripts\\smoke_test_openrouter.py

IMPORTANT:
  - This script is NEVER auto-executed by pytest, application startup, or CI.
  - Run it only when you explicitly want to verify live connectivity to OpenRouter.
  - It sends ONLY a fixed harmless test message to the API.
  - It NEVER prints, logs, or exposes the API key or Authorization header.
  - It NEVER transmits real project data, scraped content, or uploaded documents.

Requires:
  - OPENROUTER_API_KEY to be set in backend/.env or in the current environment.
  - The backend virtual environment to be active, OR invoke via the full venv path above.
"""

import asyncio
import sys
from pathlib import Path

# Ensure the backend package root is on the path when invoked from workspace root.
_repo_root = Path(__file__).resolve().parents[2]
_backend_root = _repo_root / "backend"
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

import httpx

from app.core.config import Settings

# The only message ever sent by this script — a fixed harmless test string.
_SMOKE_TEST_MESSAGE = "Reply with the single word OK."

# Maximum wall-clock timeout for the live call (capped at 30 s regardless of config).
_MAX_TIMEOUT_SECONDS = 30.0


async def run_smoke_test() -> int:
    """Run a single live connectivity check against OpenRouter.

    Returns:
        0 on success, 1 on any failure.
    """
    print("=" * 60)
    print("Bharmafills — OpenRouter Live Smoke Test")
    print("=" * 60)

    # Load configuration from environment / backend/.env
    try:
        settings = Settings()
    except Exception as exc:
        print(f"[ERROR] Failed to load application settings: {exc}")
        return 1

    if not settings.is_ai_configured:
        print(
            "[ABORT] OPENROUTER_API_KEY is not configured.\n"
            "        Add it to backend/.env and retry."
        )
        return 1

    model = settings.OPENROUTER_MODEL
    base_url = settings.OPENROUTER_BASE_URL
    timeout_seconds = min(settings.OPENROUTER_TIMEOUT_SECONDS, _MAX_TIMEOUT_SECONDS)
    endpoint = f"{base_url}/chat/completions"

    print(f"Model    : {model}")
    print(f"Endpoint : {endpoint}")
    print(f"Timeout  : {timeout_seconds}s")
    print(f"Message  : \"{_SMOKE_TEST_MESSAGE}\"")
    print("-" * 60)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": _SMOKE_TEST_MESSAGE}],
        "max_tokens": 16,
    }

    # Authorization header is built inline and NEVER printed.
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://bharmafills.hackathon",
        "X-Title": "Bharmafills",
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=timeout_seconds, write=timeout_seconds, pool=timeout_seconds)
        ) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
    except httpx.TimeoutException:
        print("[FAILURE] Request timed out — network or upstream latency issue.")
        return 1
    except (httpx.NetworkError, httpx.ConnectError) as exc:
        print(f"[FAILURE] Network error: {type(exc).__name__}")
        return 1
    except Exception as exc:
        print(f"[FAILURE] Unexpected error: {type(exc).__name__}")
        return 1

    status_code = response.status_code
    print(f"HTTP Status : {status_code}")

    if status_code == 200:
        try:
            data = response.json()
            choices = data.get("choices", [])
            if choices and choices[0].get("message", {}).get("content"):
                preview = choices[0]["message"]["content"][:80].strip()
                print(f"Response    : {preview!r}")
            else:
                print("[WARNING] Response parsed but no content in choices.")
            print("[SUCCESS] OpenRouter connection verified.")
            return 0
        except Exception as exc:
            print(f"[FAILURE] Could not parse response JSON: {type(exc).__name__}")
            return 1

    if status_code in (401, 403):
        print("[FAILURE] Authentication rejected (HTTP 401/403). Check OPENROUTER_API_KEY.")
        return 1

    if status_code == 402:
        print("[FAILURE] Quota or credits exhausted (HTTP 402).")
        return 1

    if status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        print(f"[FAILURE] Rate limited (HTTP 429). Retry-After: {retry_after}s")
        return 1

    if status_code in (500, 502, 503, 504):
        print(f"[FAILURE] Upstream server error (HTTP {status_code}). Retry later.")
        return 1

    print(f"[FAILURE] Unexpected HTTP status {status_code}.")
    return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_smoke_test())
    sys.exit(exit_code)

