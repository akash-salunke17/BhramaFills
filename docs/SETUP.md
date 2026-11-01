# Bharmafills — Setup & Installation Guide

> **Document Status**: Active
> **Target Environment**: Windows 10 / 11 with PowerShell 5.1 / 7+
> **Workspace Location**: `D:\Users\Vikas Salunke\Downloads\Shinchan`
> **Frontend Location**: `frontend/`
> **Backend Location**: `backend/` (Step 5A Implemented)

---

## 1. Prerequisites

Ensure your development environment meets the following specifications before beginning:

| Dependency | Minimum Version | Recommended Version | Verification Command |
| :--- | :--- | :--- | :--- |
| **Node.js** | `v20.0.0` | `v22.x LTS` | `node -v` |
| **npm** | `v10.0.0` | Latest with Node | `npm.cmd -v` |
| **Git** | `2.40+` | Latest | `git --version` |
| **Python** | `3.11+` | `3.15.0` (Active) | `python --version` |
| **PowerShell** | `5.1` | `7.x Core` | `$PSVersionTable.PSVersion` |

---

## 2. Frontend Setup (Current Phase 2 Active)

### 2.1 Navigate and Install
Open PowerShell in the workspace root and navigate to the frontend directory:

```powershell
# Navigate to frontend package root
cd "D:\Users\Vikas Salunke\Downloads\Shinchan\frontend"

# Clean install node dependencies
npm.cmd install
```

### 2.2 Configure Local Environment
Copy the example environment template from the repository root:

```powershell
# From workspace root:
Copy-Item "..\.env.example" -Destination ".env"
```

*Note: In Phase 2, the frontend runs standalone in the browser using client-side localStorage. No external cloud credentials are required to run Phase 1 and Phase 2 features.*

### 2.3 Start the Development Server
```powershell
npm.cmd run dev
```

Output should confirm the server is running:
```text
  VITE v8.x.x  ready in 250 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
  ➜  press h + enter to show help
```

Open `http://localhost:5173` in your browser.

### 2.4 Run Verification Tests
Verify that all 52 unit tests execute and pass cleanly:

```powershell
npm.cmd test
```

Verify that code quality standards pass without linting errors:

```powershell
npm.cmd run lint
```

Verify that the production build bundles successfully:

```powershell
npm.cmd run build
```

---

## 3. Backend Setup (Step 5A Implemented & Active)

The FastAPI application foundation, configuration layer, and health probe are implemented and verified.

### 3.1 Python Virtual Environment
The virtual environment is established inside `backend/venv`:

```powershell
# Navigate to backend directory
cd "D:\Users\Vikas Salunke\Downloads\Shinchan\backend"

# Activate virtual environment in PowerShell
.\venv\Scripts\Activate.ps1
```

> **PowerShell Execution Policy**: If script execution is disabled on your system, enable it for the current user:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### 3.2 Install / Verify Backend Dependencies
```powershell
pip install -r requirements.txt
```

> **Mandatory Dependency Policy**: Never execute `pip freeze` or `pip freeze > requirements.txt`. All backend dependencies are deliberately selected and manually curated in `requirements.txt` to keep the dependency graph reproducible and free of uncurated transitive noise.

Active baseline dependencies:
- `fastapi` (0.162.0)
- `uvicorn[standard]` (0.54.0)
- `pydantic` (2.14.2)
- `pydantic-settings` (2.16.2)
- `httpx` (0.28.1)
- `asyncpg` (0.32.0)
- `pytest` (8.4.2) & `pytest-asyncio` (0.26.0)

### 3.3 Running FastAPI Locally
```powershell
# Start ASGI server with live reload
python -m uvicorn app.main:app --reload --port 8000
```

Verify in another PowerShell tab:
```powershell
# Probe the process health endpoint
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health
```
Output:
```json
{
  "status": "ok",
  "service": "Bharmafills API",
  "version": "0.1.0"
}
```

Verify database connectivity:
```powershell
# Probe the database health endpoint
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health/database
```
Output (when configured and connected):
```json
{
  "status": "ok",
  "database": "connected"
}
```
Output (when not configured):
```json
{
  "status": "not_configured",
  "database": "not_configured"
}
```

Swagger UI documentation is accessible at: `http://localhost:8000/docs`

### 3.4 Executing Backend Tests
```powershell
python -m pytest
```
Output should confirm 42 passing tests across configuration, CORS, health probes, and database connection lifecycle test suites.

---

## 4. Environment Variables Reference

Reference template located in `.env.example`:

| Variable Name | Required Stage | Default / Example Value | Description |
| :--- | :--- | :--- | :--- |
| `VITE_APP_TITLE` | Step 1+ | `Bharmafills` | Public application name rendered in UI |
| `VITE_API_BASE_URL` | Step 5+ | `http://localhost:8000/api/v1` | URL for backend extraction & AI APIs |
| `BACKEND_PORT` | Step 5+ | `8000` | Port for the FastAPI server |
| `SUPABASE_URL` | Step 6+ | `https://xyzcompany.supabase.co` | Supabase project instance endpoint |
| `SUPABASE_ANON_KEY` | Step 6+ | `eyJhbGci...` | Supabase public client anonymous token |
| `SUPABASE_SERVICE_ROLE_KEY` | Step 6+ | `eyJhbGci...` | Supabase private service key (backend only) |
| `SUPABASE_DB_URL` | Step 6A+ | `postgresql://placeholder:placeholder@placeholder:5432/postgres` | Supabase PostgreSQL Session Pooler connection URL (Backend only) |
| `GEMINI_API_KEY` | Step 9+ | `AIzaSy...` | Google Gemini API key for gap analysis |
| `GEMINI_MODEL` | Step 9+ | `gemini-2.5-flash` | Configurable model identifier |
| `OPENROUTER_API_KEY` | Step 9A+ | `sk-or-v1-...` | OpenRouter API key for LLM chat completions (NVIDIA Nemotron 3 Ultra) |
| `OPENROUTER_MODEL` | Step 9A+ | `nvidia/nemotron-3-ultra-550b-a55b:free` | Runtime-configurable OpenRouter model identifier |
| `OPENROUTER_BASE_URL` | Step 9A+ | `https://openrouter.ai/api/v1` | OpenRouter API base endpoint URL |
| `OPENROUTER_TIMEOUT_SECONDS` | Step 9A+ | `30.0` | Timeout in seconds for OpenRouter API requests |

---

### Optional: Verify Live OpenRouter Connectivity

After setting `OPENROUTER_API_KEY` in `backend/.env`, you can manually verify the connection with the provided smoke test script:

```powershell
# Run from workspace root — NEVER executed automatically
.\backend\venv\Scripts\python.exe backend\scripts\smoke_test_openrouter.py
```

> **Important**: This script is NEVER auto-run by pytest, CI, or application startup.
> It sends only the fixed harmless message `"Reply with the single word OK."` and never transmits real project data.
> It never prints or logs the API key or any credential-derived information.

---

## 5. Common Setup Troubleshooting

### Issue 1: `npm` is not recognized as an internal or external command
- **Cause**: Node.js is not added to the Windows system `PATH`, or PowerShell is evaluating an alias.
- **Fix**: Use `npm.cmd` explicitly in PowerShell, or verify your Node.js installation path in System Environment Variables.

### Issue 2: Port `5173` is already in use
- **Cause**: A previous Vite process is running in the background.
- **Fix**: Stop the process or run Vite on a specific port:
  ```powershell
  npm.cmd run dev -- --port 5174
  ```

### Issue 3: LocalStorage Quota Exceeded in Private Browsing
- **Cause**: Browsers in strict private mode impose strict quota limitations.
- **Behavior**: Bharmafills gracefully falls back to session memory and alerts the user with an inline notice rather than crashing.

### Issue 4: Supabase Connection String contains `[YOUR-PASSWORD]` or Special Characters
- **Cause**: Copying the Session Pooler connection string directly from the Supabase dashboard preserves the `[YOUR-PASSWORD]` template placeholder.
- **Fix**:
  1. Replace the entire `[YOUR-PASSWORD]` token (including the square brackets `[` and `]`) with your database password.
  2. If your password contains special characters like `@`, `:`, `#`, `%`, `&`, or `?`, URL-encode them (e.g., using Python `urllib.parse.quote_plus("your@pass")` -> `your%40pass`).
  3. Ensure the connection string uses port `5432` for Session Pooler mode with `statement_cache_size=0`.
