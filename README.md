# Kite Workspace

A React + Vite frontend and Python FastAPI backend for a single user's local Zerodha Kite Connect workspace. The dark dashboard has **User**, **Signals**, and **Session** tabs. The User tab shows your profile; Signals scans Nifty 100 equities for intraday EMA crossovers using your saved Kite session.

Source repository: [VaibhavSatve/zerodha_algo_app](https://github.com/VaibhavSatve/zerodha_algo_app).

To get the code:

```bash
git clone https://github.com/VaibhavSatve/zerodha_algo_app.git
cd zerodha_algo_app
```

The repository root is the `kite-workspace` directory referred to below.

## Dashboard Signals tab

### Install or update, then run (Windows PowerShell)

From your local checkout, install the backend packages (including pandas) once:

```powershell
cd "D:\Personal\Trading\Algo Trading App"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
pnpm --dir frontend install --frozen-lockfile
```

Skip the `venv` command when `.venv` already exists. For a fresh clone in another location, use that checkout's path. Install Python 3.11+ and Node.js 22.12+ (or 24 LTS); install pnpm with `npm install -g pnpm@11` if needed.

**Terminal 1 — backend:**

```powershell
cd "D:\Personal\Trading\Algo Trading App"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload --reload-dir backend/app --no-access-log
```

**Terminal 2 — frontend:**

```powershell
cd "D:\Personal\Trading\Algo Trading App"
pnpm --dir frontend dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173), connect with the existing login form if needed, and select **Signals**. A valid saved dashboard session is reused automatically. Stop an older server using the same port before starting these commands.

### Generate and read signals

1. Choose **Short EMA** (default 6), **Long EMA** (21), **Timeframe** (5 Minute), **Lookback Days** (30), and **Max Stocks** (100).
2. Click **Generate Signals**. Inputs and the button are disabled while scanning. You can switch dashboard tabs and return without losing the scan. Keep the page open; a full scan takes several minutes, especially for 4 Hour or longer lookbacks.
3. Read the newest crossover first. Each row includes its **Timeframe**, returned by the backend, and separate Crossover Date and Crossover Time (IST) columns. Green ↑ means Bullish; red ↓ means Bearish. Search by ticker/company and filter All/Bullish/Bearish. Filtering preserves the original ranks from the full scan.
4. Changing parameters clears the old results to avoid relabeling old values. EMA column headings follow your chosen periods. Generate again to calculate the new values.

Whole-number limits: `1 <= Short EMA < Long EMA <= 100`, Lookback Days **1–90**, Max Stocks **1–100**. Max Stocks selects the first N official constituents in ticker order; it does not truncate the newest N signals after scanning. Missing mappings are skipped. Stocks Scanned counts mapped stocks attempted; the table footer counts stocks with sufficient valid data. The summary includes signals, bullish/bearish totals, selected timeframe, and last generation time.

### Candle and crossover rules

- The backend downloads the current [official Nifty 100 CSV](https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv), matches exact symbols to Kite's NSE cash `EQ` instruments, and fetches historical candles with the saved backend token.
- Native intervals are `5minute`, `15minute`, and `60minute`. **4 Hour** reuses `60minute` data and pandas OHLCV resampling, anchored at 09:15 IST per trading day. It produces 09:15–13:15 and the shorter 13:15–15:30 closing session bar, never joining overnight data. All expected hourly source candles must be present. See the [Kite historical API](https://kite.trade/docs/connect/v3/historical/) for supported native intervals.
- One scan-start timestamp determines completion for every stock. A 14:55 five-minute candle is eligible at 15:00. The last hourly candle starts at 15:15 and ends at 15:30. Normal NSE cash hours are modeled; special sessions outside 09:15–15:30 are excluded.
- Lookback Days is a rolling calendar-day window ending at scan start. Extra history is fetched **before** that window to initialize EMAs (approximately five long-EMA periods plus a calendar buffer). That older history is used only for calculation; its crossovers cannot appear in results. Requests are chunked into at most 60 days.
- EMA uses pandas `ewm(span=period, adjust=False).mean()`. A bullish crossover requires previous short EMA ≤ long EMA and current short EMA > long EMA; bearish reverses those inequalities. Both candles must be completed and adjacent. Missing intraday candles are not bridged. The previous session's final candle and next session's opening candle can be consecutive.
- Each stock returns its latest actual crossover within the window. Merely being above/below the long EMA does not create a signal. Full timestamps are sorted descending, with ticker ordering for ties. Prices/EMAs are rounded only for output, so very small genuine crosses can display equal rounded EMA values.
- **Crossover Date / Time label the crossover candle's start in IST.** Close and EMA values belong to that candle. They are not current quotes. EMA values may differ from a chart initialized with a different history.

### Sessions, failures, and API

All Kite calls, EMA calculations, resampling, and ranking run in FastAPI. The Signals browser request contains only scanner parameters plus the existing opaque HttpOnly session cookie. No API key, API secret, request token, or access token is returned by the scanner API or stored in its frontend state.

`GET /api/signals/ema?short_ema=6&long_ema=21&timeframe=5minute&lookback_days=30&max_stocks=100`

The request requires the existing session cookie and `X-Kite-Client: local-web`. The response includes the applied parameters, scan cutoff, lookback start, generation time, summary counts, per-stock warnings, and ranked public signal fields. `401` asks you to reconnect, `409` means another scan is running, `422` means invalid parameters, and `503` means the official list or Kite is temporarily unavailable. Run one Uvicorn worker: a backend lock prevents overlapping scans across browser tabs. Reloading the page does not cancel an in-progress server scan; wait for it to finish before trying again.

Historical calls wait 0.55 seconds between requests. Rate-limit (429), network, and server failures retry at most twice with 2- and 4-second backoffs, within [Kite's historical API rate limit](https://kite.trade/docs/connect/v3/exceptions/). An individual stock failure adds a warning and other stocks continue. Empty data, insufficient history, and missing mappings are shown in expandable details. No crossovers is a valid empty result. If no stocks could be analyzed, check that your Kite app has historical-data access.

If source candles are missing, incomplete 4-hour buckets are excluded. For example, without the 15:15 hourly candle, the 13:15–15:30 closing bar cannot be completed. The scanner does not fill that gap or compare across the missing bar. When the selected lookback contains no valid consecutive completed pair, the stock receives a data-availability warning instead of being reported as a successful scan with no crossover.

Expired/revoked sessions stop the scan and return you to login; temporary outages preserve the saved session. Disconnecting or replacing the login during a scan stops further requests for that old session. Browser requests allow up to 20 minutes for a large scan; a network interruption can leave the backend finishing the current scan, and duplicate requests remain blocked until it exits. Scans are read-only and place no orders.

Backend checks: from the project root, `cd backend` and run `..\.venv\Scripts\python.exe -m pytest -q`. Frontend check from the project root: `pnpm --dir frontend build`. Tests use synthetic candles and mocked Kite responses, with no live credentials.

## Standalone Nifty 100 EMA scanner

The single file `nifty100_ema_scanner.py` scans **EMA 6 / EMA 21** across **Daily, 5 Minute, 15 Minute, 1 Hour, and 4 Hour** candles. It runs independently of the React/FastAPI dashboard. You do not need to start either web server for this scanner.

### Install once (Windows PowerShell)

Open PowerShell in your existing project folder:

```powershell
cd "D:\Personal\Trading\Algo Trading App"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install kiteconnect pandas requests
```

For a fresh clone elsewhere, replace the `cd` path with that clone's directory. Python 3.11+ is required. The script directly imports only `kiteconnect`, `pandas`, `requests`, and standard-library modules; no technical-analysis packages are used. pandas installs its own normal dependencies automatically.

### Credentials and login

Keep your existing `credentials.txt` in the same directory as the script, using these labels and your real values locally:

```text
API Key = your_api_key
API Secret = your_api_secret
```

A colon instead of `=`, underscores, and a `Kite` prefix on the labels are also accepted. Do not commit this file or paste real values into Python source. Both credential text files currently used in this folder are excluded by `.gitignore`.

### Run again tomorrow

```powershell
cd "D:\Personal\Trading\Algo Trading App"
.\.venv\Scripts\python.exe .\nifty100_ema_scanner.py
```

The script opens Kite's official login in your browser. Complete the login, copy the `request_token` value from your app's registered redirect address, then paste it at the **hidden terminal prompt**. If your redirect points to the local dashboard and the web server is stopped, the address still contains the request token even when the redirect page cannot load. Copy only the token value, ending before the next `&`.

Use a **fresh** request token for each run: Kite request tokens are single-use and expire quickly. Authentication calls `KiteConnect.generate_session()`. The access token stays in process memory; this standalone script does not persist it or reuse the dashboard's session file. The API secret, request token, and access token are never printed or placed in the CSV. Private automation can pass a request token through `KITE_REQUEST_TOKEN`; do not put it in command history or source code.

### What the scan does

1. Downloads the current [official Nifty 100 constituents CSV](https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv). There is no hardcoded stock list.
2. Downloads Kite's NSE instrument master once and matches exact constituent symbols to `exchange=NSE`, `segment=NSE`, `instrument_type=EQ`. Only official equity members are selected. Missing or ambiguous mappings are skipped with a warning.
3. Fetches four native histories per stock: `day` (365 calendar days), `5minute` (30 days), `15minute` (60 days), and `60minute` (180 days). Hourly data is reused for 4 Hour analysis, so there is no duplicate hourly API call.
4. Uses one IST snapshot captured at scan start. A candle is eligible only once its end is at or before that snapshot. Today's Daily candle is excluded until 15:30 IST. Intraday processing covers the normal NSE cash session, 09:15–15:30 IST; special sessions outside these hours are not modeled.
5. Calculates `close.ewm(span=6, adjust=False).mean()` and `close.ewm(span=21, adjust=False).mean()`. At least 22 completed observations are required; the first 21 observations are warm-up, and crossovers require both the previous and current EMA values. Longer downloaded histories reduce initialization effects, though values can differ from a chart using a different starting history.
6. Finds the most recent **actual** bullish or bearish crossover for each stock/timeframe, including older crossovers inside the fetched history. Above/below state alone never qualifies. Missing intraday candle gaps are not treated as adjacent comparisons.
7. Sorts all results by the full crossover timestamp descending, then by Symbol and Timeframe for deterministic ties. Rounding to two decimal places happens only after detection and sorting.

### 4 Hour candle convention

Kite has no native 4-hour historical interval. The script uses pandas OHLCV resampling, anchored to **09:15 IST separately for every trading day**:

- **09:15–13:15:** four complete hourly source candles.
- **13:15–15:30:** the shorter closing session bar. Its final hourly source candle starts at 15:15 and completes at 15:30.

The closing bar is a completed session bar, not a full four hours of trading. Neither bar is emitted before its session-adjusted closing time, and all expected source candles must be present. Bars never span the overnight closure. This convention is explicit because platforms can use different 4-hour session alignment.

### Output and failures

The complete ranked table is printed in the terminal and saved to **`nifty100_ema_signals.csv` beside the script**, overwriting the previous results after a scan. Columns are:

`Rank, Symbol, Company, Timeframe, Signal Type, Crossover Date, Close, EMA 6, EMA 21`

**Crossover Date includes both date and time in IST and labels the candle start**, as Kite does. Daily labels are the daily candle's original timestamp. Each row's Close/EMA values belong to its crossover candle, not the latest quote. Rank 1 is the newest crossover timestamp among all returned rows.

The summary lists symbols loaded/mapped, stock/timeframe combinations attempted, combinations with sufficient data, bullish/bearish counts, and the CSV path. No signals produces a header-only CSV. Generated CSVs and credentials are ignored by Git.

Historical calls are spaced by 0.55 seconds, below [Kite's historical limit of 3 requests per second](https://kite.trade/docs/connect/v3/exceptions/). Rate limits, network failures, and upstream server errors get at most two retries with 2- and 4-second waits. A full 100-stock scan takes several minutes. Each failed stock/timeframe is skipped; authentication expiry stops further API calls and saves partial results. Ctrl+C during scanning also saves already collected results. Setup/login failures preserve the previous CSV and clearly report that no new scan started.

If all histories fail, check that your Kite app has **historical-data access** enabled. Close the CSV in Excel before rerunning if Windows reports a file-write error.

See [Kite historical-candle documentation](https://kite.trade/docs/connect/v3/historical/) for native intervals and data fields.

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
| `GET /api/signals/ema` | Scan Nifty 100 intraday EMA crossovers | Applied parameters, counts, warnings, ranked signals |
| `POST /api/logout` | Revoke and remove the current session | `authenticated`, `saved_at` |

POST requests and the Signals GET request require `X-Kite-Client: local-web`. Profile, signals, and logout require the opaque session cookie. Session responses never include a Kite access token. Interactive API docs are disabled to avoid encouraging credentials to be retained in a separate browser surface.

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

Never paste real credentials into source files, tests, issues, or commit messages. The test suite contains intentionally fake credentials. Keep live credentials in the local login form/backend session store or the scanner's ignored credentials.txt file, as described above.


### Troubleshooting login

Use the API key and API secret from the **same Kite developer app**. Your Zerodha user ID is not the API key. Enter that key before choosing **Get request token**, and submit promptly after login. You can paste either the token value or the complete redirect URL. Do not reuse old tokens.

The form retains the key and secret only in current component memory after an unsuccessful attempt, with the secret masked; it clears the request token. Reloading clears the form. No credentials are saved to browser storage.

Checksum errors require checking the matching key, secret, and token; generating tokens alone will not correct a mismatched secret. Network errors require checking connectivity from the backend process. Restart a backend launched in a restricted environment from a normal local terminal. The app distinguishes these errors without displaying raw Kite error payloads.
