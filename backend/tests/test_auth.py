"""Contract tests use a fake Kite SDK; no live credentials or network required."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from kiteconnect.exceptions import TokenException
from requests.exceptions import ConnectionError

from app.main import COOKIE_NAME, LoginBody, create_app

ACCESS_TOKEN = "server-only-test-access-token"
API_SECRET = "never-persist-this-test-secret"
REQUEST_TOKEN = "one-time-test-request-token"
CREDENTIALS = {"api_key": "test-api-key", "api_secret": API_SECRET, "request_token": REQUEST_TOKEN}
HEADERS = {"X-Kite-Client": "local-web", "Origin": "http://127.0.0.1:5173"}
PROFILE = {"user_name": "Test User", "user_id": "AB1234", "products": ["CNC", "MIS", "NRML"], "exchanges": ["NSE", "BSE", "NFO"]}


@pytest.fixture
def setup(tmp_path):
    sdk = MagicMock()
    sdk.generate_session.return_value = {"access_token": ACCESS_TOKEN, "api_secret": API_SECRET, "enctoken": "private-enctoken"}
    sdk.profile.return_value = {**PROFILE, "access_token": ACCESS_TOKEN, "api_secret": API_SECRET}
    factory = MagicMock(return_value=sdk)
    path = tmp_path / "private" / "session.json"
    with TestClient(create_app(path, factory)) as client:
        yield client, sdk, factory, path


def sign_in(client):
    response = client.post("/api/login", json=CREDENTIALS, headers=HEADERS)
    assert response.status_code == 200
    return response


def test_login_saves_only_required_backend_state_and_hides_tokens(setup):
    client, sdk, factory, path = setup
    response = sign_in(client)
    sdk.generate_session.assert_called_once_with(REQUEST_TOKEN, api_secret=API_SECRET)
    factory.assert_called_with(api_key="test-api-key", timeout=10, debug=False)
    assert set(response.json()) == {"authenticated", "saved_at"}
    assert response.json()["authenticated"] is True
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api" in cookie
    for secret in (ACCESS_TOKEN, API_SECRET, REQUEST_TOKEN, "private-enctoken"):
        assert secret not in response.text
        assert secret not in cookie
    saved = json.loads(path.read_text())
    assert saved["access_token"] == ACCESS_TOKEN
    assert set(saved) == {"api_key", "access_token", "browser_session_hash", "saved_at"}
    assert API_SECRET not in path.read_text() and REQUEST_TOKEN not in path.read_text()
    assert client.cookies.get(COOKIE_NAME) not in path.read_text()


def test_profile_is_allowlisted_and_uses_saved_token(setup):
    client, sdk, _, _ = setup
    sign_in(client)
    response = client.get("/api/profile")
    assert response.status_code == 200 and response.json() == PROFILE
    sdk.set_access_token.assert_called_with(ACCESS_TOKEN)
    assert response.headers["cache-control"] == "no-store"


def test_restart_restores_same_browser_without_exchanging_request_again(setup):
    client, sdk, factory, path = setup
    sign_in(client)
    with TestClient(create_app(path, factory)) as restarted:
        restarted.cookies.update(client.cookies)
        assert restarted.get("/api/session").json()["authenticated"] is True
        assert restarted.get("/api/profile").json() == PROFILE
    sdk.generate_session.assert_called_once()


def test_unrelated_browser_cannot_use_or_delete_saved_account(setup):
    client, _, factory, path = setup
    assert client.get("/api/session").json()["authenticated"] is False
    assert client.get("/api/profile").status_code == 401
    sign_in(client)
    with TestClient(create_app(path, factory)) as stranger:
        assert stranger.get("/api/session").json()["authenticated"] is False
        assert stranger.get("/api/profile").status_code == 401
        assert stranger.post("/api/logout", headers=HEADERS).status_code == 401
    assert path.exists()


@pytest.mark.parametrize("endpoint", ["/api/profile", "/api/session"])
def test_expired_session_is_cleared(setup, endpoint):
    client, sdk, _, path = setup
    sign_in(client)
    sdk.profile.side_effect = TokenException("Do not reflect " + ACCESS_TOKEN)
    response = client.get(endpoint)
    assert response.status_code == (401 if endpoint == "/api/profile" else 200)
    if endpoint == "/api/session":
        assert response.json()["authenticated"] is False
    assert ACCESS_TOKEN not in response.text
    assert not path.exists()


@pytest.mark.parametrize("endpoint", ["/api/profile", "/api/session"])
def test_temporary_outage_keeps_saved_token(setup, endpoint):
    client, sdk, _, path = setup
    sign_in(client)
    sdk.profile.side_effect = ConnectionError("private upstream context " + ACCESS_TOKEN)
    response = client.get(endpoint)
    assert response.status_code == 503
    assert ACCESS_TOKEN not in response.text
    assert path.exists()
    sdk.profile.side_effect = None
    assert client.get("/api/session").json()["authenticated"] is True


def test_logout_revokes_and_forgets_session(setup):
    client, sdk, _, path = setup
    sign_in(client)
    response = client.post("/api/logout", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    sdk.invalidate_access_token.assert_called_once()
    assert not path.exists()
    assert client.get("/api/profile").status_code == 401


def test_failed_logout_can_be_retried(setup):
    client, sdk, _, path = setup
    sign_in(client)
    sdk.invalidate_access_token.side_effect = ConnectionError(ACCESS_TOKEN)
    response = client.post("/api/logout", headers=HEADERS)
    assert response.status_code == 503 and path.exists()
    assert ACCESS_TOKEN not in response.text


@pytest.mark.parametrize("payload", [
    {**CREDENTIALS, "api_secret": ""},
    {**CREDENTIALS, "unexpected": API_SECRET},
    {**CREDENTIALS, "request_token": {"sensitive": REQUEST_TOKEN}},
    {"api_secret": API_SECRET},
])
def test_validation_does_not_echo_sensitive_input(setup, payload):
    client, _, _, _ = setup
    response = client.post("/api/login", json=payload, headers=HEADERS)
    assert response.status_code == 422
    assert API_SECRET not in response.text and REQUEST_TOKEN not in response.text


def test_sdk_error_does_not_expose_credentials(setup):
    client, sdk, _, path = setup
    sdk.generate_session.side_effect = TokenException(API_SECRET)
    response = client.post("/api/login", json=CREDENTIALS, headers=HEADERS)
    assert response.status_code == 401
    assert API_SECRET not in response.text
    assert not path.exists()


def test_unexpected_error_is_sanitized(setup):
    client, sdk, _, _ = setup
    sdk.generate_session.side_effect = RuntimeError(API_SECRET)
    response = client.post("/api/login", json=CREDENTIALS, headers=HEADERS)
    assert response.status_code == 500
    assert API_SECRET not in response.text


def test_cross_origin_and_missing_header_requests_are_rejected(setup):
    client, sdk, _, _ = setup
    assert client.post("/api/login", json=CREDENTIALS).status_code == 403
    assert client.post("/api/login", json=CREDENTIALS, headers={**HEADERS, "Origin": "https://untrusted.example"}).status_code == 403
    assert client.get("/api/profile", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "untrusted.example"}).status_code == 400
    sdk.generate_session.assert_not_called()


def test_corrupted_store_returns_login_and_can_be_replaced(setup):
    client, _, _, path = setup
    path.parent.mkdir()
    path.write_text("{interrupted-json")
    assert client.get("/api/session").json()["authenticated"] is False
    sign_in(client)
    assert client.get("/api/profile").status_code == 200


def test_failed_persistence_never_sets_browser_cookie(setup, monkeypatch):
    client, _, _, _ = setup
    monkeypatch.setattr("app.store.SessionStore.save", MagicMock(side_effect=PermissionError(API_SECRET)))
    response = client.post("/api/login", json=CREDENTIALS, headers=HEADERS)
    assert response.status_code == 500
    assert "set-cookie" not in response.headers
    assert API_SECRET not in response.text


def test_models_redact_secrets_in_representations():
    assert API_SECRET not in repr(LoginBody(**CREDENTIALS))
    assert REQUEST_TOKEN not in repr(LoginBody(**CREDENTIALS))
