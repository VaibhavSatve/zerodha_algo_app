# Development and GitHub synchronization

This is a public, local-development React + Vite and FastAPI project.

## Repository

- Canonical repository: https://github.com/VaibhavSatve/zerodha_algo_app
- Remote: `origin`; primary branch: `main`.
- The owner has authorized syncing completed development changes to this repository. After each requested development change, run the relevant checks, review the exact staged diff for sensitive data, commit the intended source changes, and push them. Do not stop at local edits when the change is ready to sync.
- Fetch the remote before starting repository changes. Preserve remote history and other people's changes. Never force-push, discard local changes, or overwrite unrelated remote work.
- If local Git authentication is unavailable, use the connected GitHub tools to publish reviewed source changes, then fetch and reconcile the local branch with the resulting remote commit without discarding work. If both methods are unavailable, report that sync is blocked; do not claim synchronization succeeded.
- Verify the resulting GitHub commit and local branch status before reporting completion. No background file watcher is implied; sync when a requested development task is complete.

## Public repository boundaries

- Never commit live API keys, API secrets, request tokens, access tokens, browser cookies, real account profile data, or credential-bearing URLs.
- Never commit `.env`, `.data`, `backend/.data/session.json`, local environments, dependency directories, build output, logs, archives, or editor caches. Keep `.gitignore` up to date.
- Review staged content, not only `.gitignore`: ignore rules do not protect already tracked files. Stage only intended paths. Test fixtures contain clearly named fake credentials; never replace them with live values.
- Keep the generated Kite access token on the backend. Do not add it to response bodies, headers, browser storage, frontend variables, cookies, or URLs. The browser may hold only the separate opaque HttpOnly session cookie.
- Do not persist API secrets or request tokens. Keep SDK debug logging off and avoid logging request bodies or raw exceptions.
- Keep local servers bound to loopback and keep Vite's filesystem allowlist restricted to the frontend. Backend session files must never become static assets.

## Project and verification

- `frontend/`: React, TypeScript, Vite. Theme variables are in `frontend/src/styles.css`.
- `backend/`: FastAPI, the official Kite SDK, and atomic local session persistence.
- Frontend check: `pnpm build` from `frontend/`.
- Backend check: virtual-environment Python with `-m pytest -q` from `backend/`.
- Run checks relevant to the change. Never use live credentials for automated tests.
- Update the README for any changes to setup, authentication, or session behavior. Preserve the supplied dependency lockfiles.
