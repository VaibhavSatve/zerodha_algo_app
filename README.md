# Kite Workspace

A React + Vite frontend and Python FastAPI backend for a single user's local Zerodha Kite Connect workspace. The dark dashboard has **User** and **Session** tabs. The User tab fetches the name, user ID, products, and exchanges from Kite through FastAPI.

Source repository: [VaibhavSatve/zerodha_algo_app](https://github.com/VaibhavSatve/zerodha_algo_app).

To get the code:

```bash
git clone https://github.com/VaibhavSatve/zerodha_algo_app.git
cd zerodha_algo_app
```

The repository root is the `kite-workspace` directory referred to below.

## Requirements

- Node.js **22.12+** (or 24 LTS) and pnpm **11**. If needed, install pnpm with `npm install -g pnpm@11`.
- Python **3.11+**.
- A Zerodha account and a Kite Connect app with an API key and API secret from the [Kite developer console](https://developers.kite.trade/).

No OpenAI key, database server, or frontend environment variables are required.

## 1. Start the backend

Open a terminal in this `kite-workspace` directory.

**Windows PowerShell:**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --no-access-log
```

Using the virtual environment's Python directly avoids PowerShell activation-policy issues.

**macOS / Linux:**

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --no-access-log
```

For the exact dependency versions used during verification, use `requirements-lock.txt` instead of `requirements.txt` (the lock includes the test dependencies).

## 2. Start the frontend

Open a **second terminal** in `kite-workspace` and run:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open **[http://127.0.0.1:5173](http://127.0.0.1:5173)**. Leave both terminals running. Vite forwards `/api` requests to FastAPI on port 8000; browser requests stay on the same origin.

Use the supplied pnpm lockfile for reproducible frontend installs. The project uses React 19 and Vite 8.

## 3. Get a request token and log in

1. In the [Kite developer console](https://developers.kite.trade/), create or select your app and set its redirect URL to **`http://127.0.0.1:5173/login`**.
2. In the workspace login form, enter your **API Key** and **API Secret**. These are your app credentials, not your Zerodha password.
3. Click **Get request token**. This opens Kite's official login in another tab using your API key.
4. Complete Kite's login. In the redirected address, copy only the value after `request_token=` and before the next `&`, if present. Return to the original form and paste it into **Request Token**.
5. Click **Login to workspace** promptly. Request tokens are single-use and expire in a few minutes. The fields are cleared after submission.
6. FastAPI calls `KiteConnect.generate_session(request_token, api_secret=...)`, saves the generated access token on the backend, and returns only authentication status and a timestamp. The browser navigates to `/dashboard`; the **User** tab calls `/api/profile`.

If your Kite app uses a different registered redirect URL, copy the request token from that redirect instead. The app does not automatically capture request tokens or store credentials in browser storage.

## How session reuse works

FastAPI atomically saves `api_key`, `access_token`, a hash of a separate random browser session ID, and `saved_at` in **`backend/.data/session.json`**. Its absolute location is based on the Python module, so changing the launch directory does not change the session location.

- The browser receives a **separate random HttpOnly, SameSite=Strict cookie**, never the Kite access token. JavaScript cannot read this cookie.
- On page load, `/api/session` checks the cookie and validates the saved Kite token by calling Kite's profile API. A valid session opens the dashboard automatically.
- Frontend hot reloads, full page reloads, and backend restarts reuse the file and cookie. Use the same browser and the same hostname (`127.0.0.1` throughout); clearing cookies requires logging in again.
- Temporary upstream failures preserve the saved token. An expired or revoked token is deleted and the user reconnects.
- Disconnecting revokes the Kite API session and removes the saved file and browser cookie. It does not log you out of Kite's official web or mobile apps.
- The API secret and request token are never saved to disk. Public response models allowlist safe fields; validation and SDK errors do not echo submitted credentials.

**Kite tokens expire at 6 AM the next day** and can be invalidated earlier. Code reloads do not require a new login, but actual expiry does. This app does not bypass Zerodha's expiry or assume a refresh token is available. See [Kite authentication and session documentation](https://kite.trade/docs/connect/v3/user/) and the [official Python SDK](https://github.com/zerodha/pykiteconnect).

## Local security model

This starter is for **one trusted user on one machine**, with one Uvicorn worker. Both servers bind to loopback. Host/origin checks and a required custom header protect local API mutations; no permissive CORS is enabled.

The backend session file contains the real token in plaintext. It is excluded from Git and source packages, written atomically, and uses owner-only permissions on POSIX. Windows uses the current directory's inherited user ACL. Keep the project in a private user directory. Local software running as your OS user can still read this file.

The API secret must briefly exist in the browser because you type it into the requested form; it is sent only in a POST body to the local backend, never embedded in the JavaScript bundle or persisted to browser storage. The **generated access token never goes to the browser**, including response bodies, headers, cookies, or URLs. Avoid adding request-body logging or SDK debug logging.

Do not expose these development servers to a network or use the global session file for multiple users. A hosted version needs HTTPS, Secure cookies, per-user authentication, a proper encrypted secret store, and deployment-specific origin controls.

## Customize the UI

- **Theme:** edit the variables at the top of `frontend/src/styles.css` for backgrounds, text, orange accent, borders, corner radius, and sidebar width.
- **Pages and components:** `frontend/src/App.tsx` contains `Login`, `UserTab`, `SessionTab`, and the shared layout. There are no fabricated account details or live-trading widgets.
- **Backend API client and types:** `frontend/src/api.ts`.
- **Backend routes:** `backend/app/main.py`.
- **Persistence:** `backend/app/store.py`.

The layout adapts to narrow screens. Inputs have accessible labels, tabs support arrow keys/Home/End, and focus indicators and reduced-motion preferences are supported. Product/exchange names have optional human-friendly labels; unknown codes are still displayed.

## Verify and build

**Frontend:**

```bash
cd frontend
pnpm build
pnpm preview
```

`pnpm build` runs TypeScript checks and writes the production assets to `frontend/dist`. The local production preview is at `http://127.0.0.1:4173` and still needs FastAPI running. Use the development URL for the initial Kite redirect flow.

**Backend tests, from `backend` (Windows):**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

On macOS/Linux, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

Tests use a mocked Kite SDK and temporary stores. They verify session reuse after app recreation, secret redaction, authorization, token expiry, temporary failures, logout, corrupt files, and write failures. Live account authentication requires your own valid credentials; no real account or credentials are included.

## API reference

| Route | Purpose | Public response |
| --- | --- | --- |
| `GET /api/health` | Local backend health | `status` |
| `POST /api/login` | Exchange app credentials and request token | `authenticated`, `saved_at` |
| `GET /api/session` | Validate and restore a saved session | `authenticated`, `saved_at` |
| `GET /api/profile` | Retrieve profile with the backend token | `user_name`, `user_id`, `products`, `exchanges` |
| `POST /api/logout` | Revoke and remove the current session | `authenticated`, `saved_at` |

POST requests require `X-Kite-Client: local-web`. Profile/logout require the opaque session cookie. Session responses never include a Kite access token. Interactive API docs are disabled to avoid encouraging credentials to be retained in a separate browser surface.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| Cannot reach backend | Start FastAPI on port 8000 and refresh the workspace. |
| Login rejected | Check the app key/secret and obtain a new request token. Do not reuse one that has already been exchanged. |
| Works until the next morning | Kite expired the session; reconnect with a fresh request token. |
| Asks for login after restart | Use the same browser and hostname. Ensure `backend/.data/session.json` exists and cookies were not cleared. |
| Kite temporarily unavailable | Keep the saved session file and choose **Retry saved session** or **Refresh profile** when Kite is reachable. |
| Backend cannot save session | Check write permissions to `backend/.data`; then obtain a new request token. |
| Port in use | Stop the previous instance. If changing ports, update the Vite proxy and backend origin allowlist together. |

Stop either development server with **Ctrl+C** in its terminal. Restarting does not delete the saved session.

## Keeping development synced to GitHub

This public repository is the maintained source of truth. Completed development tasks in this workspace should be checked, reviewed for secrets, committed, and pushed to `origin/main`. `AGENTS.md` records this instruction for future work. Changes made outside an active development task are not uploaded by a background watcher.

Before starting, fetch remote changes and integrate them without discarding local work. Before each push, review `git status` and `git diff --cached`; stage only intended source paths. `.gitignore` excludes local sessions, credentials, dependencies, virtual environments, builds, logs, and archives. It does not remove secrets that were already tracked.

Never paste real credentials into source files, tests, issues, or commit messages. The test suite contains intentionally fake credentials. Keep live credentials in the login form and backend session store only, as described above.
