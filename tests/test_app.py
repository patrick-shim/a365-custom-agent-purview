"""Local chat/session boundaries, using fake identity and model services."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import time

import pytest
from fastapi.testclient import TestClient

import app as application
from agent import ChatResult, PolicyBlocked
from auth import AuthError, UserContext
from config import Settings


@pytest.fixture
def web(monkeypatch):
    # Test routes must not write policy log files or call tenant services.
    monkeypatch.setattr(application, "configure_logging", lambda: None)
    user = UserContext(
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "Test User", "tester@example.com", "private-user-assertion",
    )
    identity = SimpleNamespace(
        ready=True,
        missing_settings=Mock(return_value=[]),
        begin_login=Mock(return_value={
            "state": "oauth-state", "auth_uri": "https://login.microsoftonline.com/test/authorize",
            "code_verifier": "private-pkce-verifier",
        }),
        complete_login=Mock(return_value=user),
    )
    agent = SimpleNamespace(chat=AsyncMock(return_value=ChatResult("Safe answer", "correlation", False)))
    app = application.create_app(Settings(), auth_override=identity, agent_override=agent)
    with TestClient(app, base_url="http://localhost:8000") as client:
        yield SimpleNamespace(client=client, identity=identity, agent=agent, user=user)


def sign_in(web):
    login = web.client.get("/auth/login", follow_redirects=False)
    assert login.status_code == 302
    callback = web.client.get("/auth/callback?state=oauth-state&code=test-code", follow_redirects=False)
    assert callback.status_code == 303
    session = web.client.get("/api/session").json()
    assert session["authenticated"] is True
    return session["csrf"]


def chat_headers(csrf):
    return {"Origin": "http://localhost:8000", "x-csrf-token": csrf}


def test_chat_requires_authenticated_session(web):
    response = web.client.post("/api/chat", json={"message": "hello"}, headers=chat_headers("unknown"))
    assert response.status_code == 401
    web.agent.chat.assert_not_awaited()


def test_sign_in_rotates_cookie_and_keeps_tokens_server_side(web):
    start = web.client.get("/auth/login", follow_redirects=False)
    before = web.client.cookies.get(application.COOKIE)
    assert "httponly" in start.headers["set-cookie"].lower()
    assert "samesite=lax" in start.headers["set-cookie"].lower()
    response = web.client.get("/auth/callback?state=oauth-state&code=test-code", follow_redirects=False)
    after = web.client.cookies.get(application.COOKIE)
    assert before != after
    session = web.client.get("/api/session")
    browser_data = response.text + str(response.headers) + session.text + str(web.client.cookies)
    assert "private-user-assertion" not in browser_data
    assert "private-pkce-verifier" not in browser_data
    assert session.json()["username"] == "tester@example.com"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("headers", [
    {},
    {"Origin": "https://attacker.example"},
    {"Origin": "http://localhost:8000", "x-csrf-token": "wrong"},
])
def test_chat_rejects_cross_site_or_missing_csrf(web, headers):
    sign_in(web)
    response = web.client.post("/api/chat", json={"message": "hello"}, headers=headers)
    assert response.status_code == 403
    web.agent.chat.assert_not_awaited()


def test_request_host_is_restricted(web):
    response = web.client.get("/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400


def test_authenticated_chat_passes_server_identity_and_returns_safe_result(web):
    csrf = sign_in(web)
    response = web.client.post(
        "/api/chat", json={"message": "Summarize", "file_path": "example.txt"}, headers=chat_headers(csrf)
    )
    assert response.status_code == 200
    assert response.json() == {
        "text": "Safe answer", "correlation_id": "correlation", "output_inline_evaluated": False,
    }
    args = web.agent.chat.call_args.args
    assert args[0] is web.user
    assert args[1:3] == ("Summarize", "example.txt")
    assert "private-user-assertion" not in response.text


def test_failed_login_invalidates_pending_session(web):
    web.identity.complete_login.side_effect = AuthError("Sign-in failed safely.")
    web.client.get("/auth/login", follow_redirects=False)
    response = web.client.get("/auth/callback?state=wrong&code=test-code", follow_redirects=False)
    assert response.status_code == 401
    assert not web.client.get("/api/session").json()["authenticated"]
    retry = web.client.get("/auth/callback?state=oauth-state&code=test-code", follow_redirects=False)
    assert retry.status_code == 401
    web.identity.complete_login.assert_called_once()


def test_callback_is_not_replayable(web):
    sign_in(web)
    response = web.client.get("/auth/callback?state=oauth-state&code=test-code", follow_redirects=False)
    assert response.status_code == 400
    web.identity.complete_login.assert_called_once()


@pytest.mark.parametrize("error, status", [
    (PolicyBlocked("The policy blocked this request."), 403),
    (RuntimeError("private-document-body-and-token"), 503),
])
def test_failed_turn_is_not_persisted_and_raw_errors_are_hidden(web, error, status):
    csrf = sign_in(web)
    web.agent.chat.side_effect = error
    response = web.client.post("/api/chat", json={"message": "Denied turn"}, headers=chat_headers(csrf))
    assert response.status_code == status
    assert "private-document-body-and-token" not in response.text
    seen_history = []

    async def next_turn(user, prompt, file_path, history):
        seen_history.extend(history)
        return ChatResult("Allowed", "next", True)

    web.agent.chat.side_effect = next_turn
    response = web.client.post("/api/chat", json={"message": "Next turn"}, headers=chat_headers(csrf))
    assert response.status_code == 200
    assert seen_history == []


def test_validation_does_not_echo_rejected_prompt(web):
    csrf = sign_in(web)
    sentinel = "PRIVATE-REJECTED-PROMPT"
    response = web.client.post(
        "/api/chat", json={"message": sentinel + ("x" * 8001)}, headers=chat_headers(csrf)
    )
    assert response.status_code == 422
    assert sentinel not in response.text
    web.agent.chat.assert_not_awaited()


def test_expired_session_cannot_invoke_agent(web, monkeypatch):
    csrf = sign_in(web)
    future = time.time() + application.SESSION_SECONDS + 1
    monkeypatch.setattr(application.time, "time", lambda: future)
    response = web.client.post("/api/chat", json={"message": "hello"}, headers=chat_headers(csrf))
    assert response.status_code == 401
    web.agent.chat.assert_not_awaited()


def test_logout_requires_csrf_and_clears_session(web):
    csrf = sign_in(web)
    refused = web.client.post("/auth/logout", headers=chat_headers("wrong"))
    assert refused.status_code == 403
    assert web.client.get("/api/session").json()["authenticated"]
    success = web.client.post("/auth/logout", headers=chat_headers(csrf))
    assert success.status_code == 200
    assert not web.client.get("/api/session").json()["authenticated"]
    response = web.client.post("/api/chat", json={"message": "hello"}, headers=chat_headers(csrf))
    assert response.status_code == 401


def test_request_size_limit_prevents_agent_invocation(web):
    csrf = sign_in(web)
    response = web.client.post("/api/chat", json={"message": "x" * 70000}, headers=chat_headers(csrf))
    assert response.status_code == 413
    web.agent.chat.assert_not_awaited()
