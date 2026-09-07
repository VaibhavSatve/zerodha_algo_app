"""Kite authentication for one trusted user on a loopback-only local server.

The SDK response is never returned directly. API responses use explicit public
models; the API secret and request token are used once and are never persisted.
"""

import hashlib
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Callable
from urllib.parse import urlsplit, parse_qs

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from kiteconnect import KiteConnect
from kiteconnect.exceptions import InputException, KiteException, PermissionException, TokenException
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from requests.exceptions import RequestException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .store import SavedSession, SessionStore
from .signals import ScanDataError, ScanParameters, ScanResult, ScanSessionChanged, scan

COOKIE_NAME = "kite_local_session"
ALLOWED_ORIGINS = {
    f"http://{host}:{port}"
    for host in ("127.0.0.1", "localhost")
    for port in (5173, 4173, 8000)
}
DEFAULT_STORE = Path(__file__).resolve().parents[1] / ".data" / "session.json"


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr
    api_secret: SecretStr
    request_token: SecretStr

    @field_validator("request_token", mode="before")
    @classmethod
    def extract_request_token(cls, value):
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            tokens = parse_qs(urlsplit(value.strip()).query).get("request_token", [])
            if len(tokens) != 1:
                raise ValueError("Paste a redirect URL containing exactly one request token.")
            return tokens[0]
        return value

    @field_validator("api_key", "api_secret", "request_token")
    @classmethod
    def valid_credential(cls, value: SecretStr) -> SecretStr:
        cleaned = value.get_secret_value().strip()
        if not cleaned or len(cleaned) > 512 or any(character.isspace() for character in cleaned):
            raise ValueError("Enter a valid credential without whitespace.")
        return SecretStr(cleaned)


class SessionStatus(BaseModel):
    authenticated: bool
    saved_at: str | None = None


class UserProfile(BaseModel):
    user_name: str
    user_id: str
    products: list[str]
    exchanges: list[str]


def create_app(store_path: Path = DEFAULT_STORE, kite_factory: Callable = KiteConnect) -> FastAPI:
    app = FastAPI(title="Kite Workspace API", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    store = SessionStore(store_path)
    # Serialize login, profile validation, and logout for the one local account.
    # Run one Uvicorn worker; the SDK runs in FastAPI's worker thread pool.
    lock = threading.RLock()
    scan_lock = threading.Lock()  # One scan across all browser tabs (one worker).

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            response = JSONResponse({"detail": "This local API only accepts requests from the workspace."}, status_code=403)
        elif request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-kite-client") != "local-web":
            response = JSONResponse({"detail": "The workspace request header is required."}, status_code=403)
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Never reflect SDK exception text, validation inputs, or secrets.
                response = JSONResponse({"detail": "The backend could not complete the request. Please try again."}, status_code=500)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        # FastAPI's default 422 can include submitted input. Omit it entirely.
        if _request.url.path == "/api/signals/ema":
            return JSONResponse({"detail": "Use whole numbers: 1 <= Short EMA < Long EMA <= 100, Lookback Days 1–90, Max Stocks 1–100, and a supported timeframe."}, status_code=422)
        return JSONResponse({"detail": "Enter a valid API key, API secret, and request token."}, status_code=422)

    def authorized_session(request: Request) -> SavedSession:
        saved = store.read()
        if not saved or not saved.matches(request.cookies.get(COOKIE_NAME)):
            raise HTTPException(status_code=401, detail="Connect your Kite account to continue.")
        return saved

    def client_for(saved: SavedSession):
        kite = kite_factory(api_key=saved.api_key, timeout=10, debug=False)
        kite.set_access_token(saved.access_token)
        return kite

    def public_profile(saved: SavedSession) -> UserProfile:
        try:
            data = client_for(saved).profile()
            # Explicit allowlist prevents credentials in SDK data from leaking.
            return UserProfile(user_name=data["user_name"], user_id=data["user_id"],
                               products=data.get("products", []), exchanges=data.get("exchanges", []))
        except TokenException:
            store.clear()
            raise HTTPException(status_code=401, detail="Your Kite session has expired or was revoked. Connect again with a fresh request token.") from None
        except (KiteException, RequestException):
            # A temporary outage must not discard a reusable token.
            raise HTTPException(status_code=503, detail="Kite is temporarily unavailable. Your saved session is unchanged; please try again.") from None

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/login", response_model=SessionStatus)
    def login(body: LoginBody, response: Response):
        with lock:
            try:
                kite = kite_factory(api_key=body.api_key.get_secret_value(), timeout=10, debug=False)
                data = kite.generate_session(body.request_token.get_secret_value(), api_secret=body.api_secret.get_secret_value())
            except (TokenException, InputException, PermissionException) as error:
                # Classify upstream messages without returning or logging their contents.
                message = str(error).lower()
                if "checksum" in message:
                    detail = "Kite rejected the login checksum. Use the API key and API secret from the same Kite developer app that generated this request token. A new token alone will not fix mismatched credentials."
                elif "api_key" in message or "api key" in message:
                    detail = "Kite rejected the API key. Copy the API key from your Kite developer app (not your Zerodha user ID), then generate a token using that same key."
                elif "request_token" in message or "request token" in message:
                    detail = "Kite rejected the request token. It may be expired, already used, or issued for another API key. Generate it using Get request token in this form and submit promptly."
                elif isinstance(error, PermissionException):
                    detail = "Kite denied access to this app. Check its status and permissions in the Kite developer console."
                else:
                    detail = "Kite rejected this login. Verify that the API key and secret belong to the same developer app used to generate the token; then generate and submit a new token."
                raise HTTPException(status_code=401, detail=detail) from None
            except (KiteException, RequestException):
                raise HTTPException(status_code=503, detail="The backend could not reach Kite or Kite is temporarily unavailable. Check the backend network connection and retry. This does not mean your credentials are invalid.") from None
            access_token = data.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise HTTPException(status_code=502, detail="Kite did not create a session. Get a fresh request token and try again.")
            browser_session = secrets.token_urlsafe(32)
            saved = SavedSession(api_key=body.api_key.get_secret_value(), access_token=access_token,
                                 browser_session_hash=hashlib.sha256(browser_session.encode()).hexdigest(),
                                 saved_at=datetime.now(timezone.utc).isoformat())
            try:
                store.save(saved)
            except OSError:
                raise HTTPException(status_code=500, detail="The backend could not save the session. Check write access to backend/.data, then get a fresh request token.") from None
            response.set_cookie(COOKIE_NAME, browser_session, httponly=True, samesite="strict",
                                secure=False, max_age=7 * 24 * 60 * 60, path="/api")
            return SessionStatus(authenticated=True, saved_at=saved.saved_at)

    @app.get("/api/session", response_model=SessionStatus)
    def session(request: Request, response: Response):
        with lock:
            saved = store.read()
            if not saved or not saved.matches(request.cookies.get(COOKIE_NAME)):
                response.delete_cookie(COOKIE_NAME, path="/api")
                return SessionStatus(authenticated=False)
            try:
                public_profile(saved)
            except HTTPException as error:
                if error.status_code != 401:
                    raise
                response.delete_cookie(COOKIE_NAME, path="/api")
                return SessionStatus(authenticated=False)
            return SessionStatus(authenticated=True, saved_at=saved.saved_at)

    @app.get("/api/profile", response_model=UserProfile)
    def profile(request: Request):
        with lock:
            return public_profile(authorized_session(request))

    @app.get("/api/signals/ema", response_model=ScanResult)
    def ema_signals(request: Request, parameters: Annotated[ScanParameters, Query()]):
        if request.headers.get("x-kite-client") != "local-web":
            raise HTTPException(status_code=403, detail="Start a scan from the workspace Signals tab.")
        with lock:
            saved = authorized_session(request)
        if not scan_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="A scan is already running. Wait for it to finish before generating another.")

        def check_scan_session():
            with lock:
                if store.read() != saved:
                    raise ScanSessionChanged

        try:
            with lock:
                check_scan_session()
                public_profile(saved)
            return scan(client_for(saved), parameters, check_scan_session)
        except TokenException:
            with lock:
                # An old scan must never delete a newer login's saved token.
                if store.read() == saved:
                    store.clear()
            raise HTTPException(status_code=401, detail="Your Kite session expired. Connect again, then generate signals.") from None
        except ScanSessionChanged:
            raise HTTPException(status_code=401, detail="Your connection changed during the scan. Reopen the workspace and try again.") from None
        except ScanDataError as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        finally:
            scan_lock.release()

    @app.post("/api/logout", response_model=SessionStatus)
    def logout(request: Request, response: Response):
        with lock:
            saved = store.read()
            if saved:
                saved = authorized_session(request)
                try:
                    client_for(saved).invalidate_access_token()
                except TokenException:
                    pass  # An already-expired token is safe to forget.
                except (KiteException, RequestException):
                    raise HTTPException(status_code=503, detail="Kite could not end the session. Please try disconnecting again.") from None
                store.clear()
            response.delete_cookie(COOKIE_NAME, path="/api")
            return SessionStatus(authenticated=False)

    return app


app = create_app()
