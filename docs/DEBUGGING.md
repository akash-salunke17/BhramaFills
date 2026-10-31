# Bharmafills — Troubleshooting & Debugging Runbook

> **Document Status**: Active / Operational Reference
> **Environment**: Windows 10 / 11 with PowerShell
> **Workspace Identifier**: `Shinchan`

---

## 1. Quick Diagnostic Checklist

When encountering unexpected behavior, check the following first:

```powershell
# 1. Verify Node and npm executables
node -v
npm.cmd -v

# 2. Check for port conflicts (Port 5173 or 8000)
Get-NetTCPConnection -LocalPort 5173, 8000 -ErrorAction SilentlyContinue

# 3. Verify clean git working tree
git status
```

---

## 2. Frontend & React Troubleshooting Recipes

### 2.1 Issue: Faint Headings or Washed-Out Text Contrast
- **Symptom**: Page headings, stat cards, or topbar titles appear light gray, faint, or unreadable on white backgrounds.
- **Root Cause**: Leftover Vite CSS default `@media (prefers-color-scheme: dark)` or Tailwind variables applying `--text-h: #f3f4f6` (light gray text) without dark mode background active.
- **Solution**:
  1. Inspect `frontend/src/index.css`.
  2. Enforce `color-scheme: light` in `:root`.
  3. Ensure headings apply high-contrast classes: `text-neutral-900` or `text-foreground font-semibold`.
  4. Never mix conflicting dark mode color definitions inside the light mode container.

---

### 2.2 Issue: Mobile View Squished by Sidebar
- **Symptom**: On mobile viewports (< 768px), the 256px sidebar takes up most of the screen, compressing main content to 100px.
- **Root Cause**: Sidebar has fixed desktop width (`w-64`) without responsive visibility hiding (`hidden md:flex`).
- **Solution**:
  1. Sidebar must use `hidden md:flex md:w-64 flex-col fixed inset-y-0 z-30`.
  2. Mobile navigation must be handled by an independent slide-over drawer: `fixed inset-y-0 left-0 z-50 transform transition-transform`.
  3. Ensure a backdrop overlay covers the content with an outside-click and `Escape` key listener.

---

### 2.3 Issue: ESLint Warning `react-hooks/set-state-in-effect`
- **Symptom**: ESLint flags synchronous state updates inside `useEffect` with: *"Calling setState synchronously inside useEffect leads to cascading re-renders."*
- **Root Cause**: Initializing component state from `localStorage` inside `useEffect` instead of during initial component construction.
- **Solution**:
  Use lazy state initialization in `useState`:
  ```javascript
  // ❌ Anti-pattern (causes cascading re-render)
  const [projects, setProjects] = useState([]);
  useEffect(() => {
    setProjects(researchService.getProjects());
  }, []);

  // ✅ Best practice (evaluated once on mount)
  const [projects, setProjects] = useState(() => researchService.getProjects());
  ```

---

### 2.4 Issue: Vitest Long Input Typing Timeout (`userEvent.type`)
- **Symptom**: Vitest fails tests with: *"Error: Timed out in 5000ms"* when filling out long textarea inputs.
- **Root Cause**: `userEvent.type()` dispatches dozens of individual DOM events per character (keydown, keypress, input, keyup), which in JSDOM accumulates seconds of synchronous delay for 500-character research questions.
- **Solution**:
  Use `fireEvent.change` for long input strings and bump test timeout:
  ```javascript
  // For long research inquiries:
  fireEvent.change(screen.getByLabelText(/research inquiry/i), {
    target: { value: 'A very detailed 500-character research question...' }
  });
  ```

---

### 2.5 Issue: Browser LocalStorage Quota Exceeded
- **Symptom**: `QuotaExceededError` thrown when saving large projects with multiple drafts.
- **Handling in Bharmafills**:
  `frontend/src/services/researchService.js` detects `QuotaExceededError`:
  - Gracefully switches to an in-memory fallback store so current session work is not lost.
  - Returns `{ success: false, error: 'STORAGE_QUOTA_EXCEEDED' }` to alert the user with a warning toast.
  - Suggests archiving or exporting completed research projects.

---

### 2.6 Issue: Corrupted LocalStorage Data
- **Symptom**: Malformed JSON in `localStorage` causes `JSON.parse` syntax errors, crashing the app on startup.
- **Handling in Bharmafills**:
  - The persistence adapter catches parsing errors.
  - Backs up the raw unparseable string to `bharmafills_research_corrupted_backup_<timestamp>`.
  - Resets the active key to `[]` and logs a non-fatal warning, protecting the user from an unrecoverable blank screen.

---

## 3. Windows & PowerShell Environment Recipes

### 3.1 Issue: PowerShell Script Execution Policy Disables `Activate.ps1`
- **Symptom**: Running `.\venv\Scripts\Activate.ps1` produces:
  `PSSecurityException: File ... cannot be loaded because running scripts is disabled on this system.`
- **Solution**:
  Run the following command in PowerShell to enable local scripts for your user account:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

---

### 3.2 Issue: Port `5173` or `8000` Already Bound (`EADDRINUSE`)
- **Symptom**: Vite or Uvicorn fails to start with port binding errors.
- **Solution**:
  Find and terminate the process holding the port in PowerShell:
  ```powershell
  # Find process ID holding port 5173
  $procId = (Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue).OwningProcess
  if ($procId) { Stop-Process -Id $procId -Force }
  ```

---

## 4. Backend & Extraction Debugging (Planned — Step 5+)

### 4.1 Issue: Web Scraper SSL Certificate Verification Failures
- **Symptom**: `httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED]` when scraping certain government or university portals.
- **Solution**:
  - Use certifi's updated CA bundle.
  - For sites with misconfigured intermediate certificates, inspect SSL errors and log clear warnings rather than unhandled 500 crashes.

### 4.2 Issue: Corrupt or Encrypted PDF Files
- **Symptom**: PyMuPDF throws `fitz.FileDataError: cannot open broken document` or `fitz.FileDataError: document is encrypted`.
- **Solution**:
  Catch specific `fitz` exceptions in `backend/app/services/extraction/pdf_service.py` and return user-friendly HTTP 422 responses:
  ```python
  try:
      doc = fitz.open(stream=file_bytes, filetype="pdf")
      if doc.is_encrypted:
          raise HTTPException(status_code=422, detail="Password-protected PDFs are not supported.")
  except fitz.FileDataError:
      raise HTTPException(status_code=422, detail="The uploaded PDF file is corrupt or unreadable.")
  ```

### 4.3 Issue: Google Gemini API Rate Limit (HTTP 429)
- **Symptom**: `google.genai.errors.ClientError: 429 Resource has been exhausted`.
- **Solution**:
  The backend Gemini wrapper will implement retry with exponential jittered backoff:
  - Base delay: 2.0s
  - Backoff factor: 2.0
  - Max retries: 3
  - If retries fail, return a structured error alerting the user to try again in a few moments.
