"""Authentication boundary tests; no tenant, token service, or real secrets used."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from msal import ConfidentialClientApplication as RealMsalClient

import auth


TENANT = "11111111-1111-4111-8111-111111111111"
WEB = "22222222-2222-4222-8222-222222222222"
BLUEPRINT = "33333333-3333-4333-8333-333333333333"
CHILD = "44444444-4444-4444-8444-444444444444"
USER = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def settings():
    return SimpleNamespace(
        entra_tenant_id=TENANT,
        web_client_id=WEB,
        web_client_secret="test-web-secret",
        redirect_uri="http://localhost:8000/auth/callback",
        blueprint_client_id=BLUEPRINT,
        blueprint_client_secret="test-blueprint-secret",
        agent_identity_id=CHILD,
        blueprint_scope=f"api://{BLUEPRINT}/access_as_user",
        expected_user="tester@example.com",
    )


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def token_factory(signing_key):
    def make(**overrides):
        now = int(time.time())
        claims = {
            "exp": now + 600, "iat": now - 1, "nbf": now - 1,
            "aud": BLUEPRINT,
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "tid": TENANT, "oid": USER, "scp": "access_as_user",
            "azp": WEB, "ver": "2.0",
        }
        claims.update(overrides)
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test"})
    return make


@pytest.fixture
def adapter(settings, signing_key):
    instance = auth.AgentOboAuth(settings)
    instance._jwks = Mock()
    instance._jwks.get_signing_key_from_jwt.return_value = SimpleNamespace(key=signing_key.public_key())
    instance._web_client = Mock()
    return instance


def login_result(token):
    return {
        "access_token": token,
        "id_token_claims": {
            "oid": USER, "tid": TENANT,
            "preferred_username": "tester@example.com", "name": "Test User",
        },
    }


def test_missing_config_does_not_open_network(settings):
    settings.web_client_secret = ""
    instance = auth.AgentOboAuth(settings)
    assert not instance.ready
    assert instance.missing_settings() == ["WEB_CLIENT_SECRET"]
    with pytest.raises(auth.AuthError, match="WEB_CLIENT_SECRET"):
        instance.begin_login()


@pytest.mark.parametrize("name,value", [
    ("entra_tenant_id", "common"),
    ("redirect_uri", "http://example.com/auth/callback"),
    ("blueprint_scope", "https://graph.microsoft.com/.default"),
])
def test_invalid_configuration_fails_closed(settings, name, value):
    setattr(settings, name, value)
    assert name.upper() in auth.AgentOboAuth(settings).missing_settings()


def test_begin_login_requests_blueprint_scope_and_server_side_state(adapter, settings):
    adapter._web_client.initiate_auth_code_flow.return_value = {"state": "random-state", "auth_uri": "https://login.microsoftonline.com/authorize"}
    flow = adapter.begin_login()
    assert flow["state"] == "random-state"
    args = adapter._web_client.initiate_auth_code_flow.call_args.kwargs
    assert args["scopes"] == [settings.blueprint_scope]
    assert args["redirect_uri"] == settings.redirect_uri
    assert args["prompt"] == "select_account"


def test_complete_login_uses_validated_human_identity(adapter, token_factory):
    token = token_factory()
    adapter._web_client.acquire_token_by_auth_code_flow.return_value = login_result(token)
    user = adapter.complete_login({"state": "state"}, {"state": "state", "code": "code"})
    assert user.oid == USER
    assert user.tenant_id == TENANT
    assert user.user_assertion == token
    assert token not in repr(user)


@pytest.mark.parametrize("overrides", [
    {"aud": "https://graph.microsoft.com"},
    {"iss": "https://untrusted.example/issuer"},
    {"tid": CHILD},
    {"azp": CHILD},
    {"scp": "unrelated_scope"},
    {"exp": 1},
    {"oid": "not-an-object-id"},
    {"ver": "1.0"},
])
def test_wrong_or_expired_assertions_are_rejected(adapter, token_factory, overrides):
    token = token_factory(**overrides)
    adapter._web_client.acquire_token_by_auth_code_flow.return_value = login_result(token)
    with pytest.raises(auth.AuthError, match="invalid or expired") as exc:
        adapter.complete_login({}, {})
    assert token not in str(exc.value)


def test_invalid_signature_is_rejected(adapter, token_factory):
    adapter._jwks.get_signing_key_from_jwt.return_value = SimpleNamespace(
        key=rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    )
    adapter._web_client.acquire_token_by_auth_code_flow.return_value = login_result(token_factory())
    with pytest.raises(auth.AuthError, match="invalid or expired"):
        adapter.complete_login({}, {})


def test_identity_token_must_match_blueprint_assertion(adapter, token_factory):
    result = login_result(token_factory())
    result["id_token_claims"]["oid"] = CHILD
    adapter._web_client.acquire_token_by_auth_code_flow.return_value = result
    with pytest.raises(auth.AuthError, match="does not match"):
        adapter.complete_login({}, {})


def test_expected_work_account_is_enforced(adapter, token_factory):
    result = login_result(token_factory())
    result["id_token_claims"]["preferred_username"] = "another@example.com"
    adapter._web_client.acquire_token_by_auth_code_flow.return_value = result
    with pytest.raises(auth.AuthError, match="work account"):
        adapter.complete_login({}, {})


def test_msal_state_nonce_errors_are_sanitized(adapter):
    adapter._web_client.acquire_token_by_auth_code_flow.side_effect = ValueError("bad state with secret-payload")
    with pytest.raises(auth.AuthError) as exc:
        adapter.complete_login({}, {})
    assert "secret-payload" not in str(exc.value)
    assert exc.value.__suppress_context__


def test_sdk_hop_one_passes_child_fmi_path(settings):
    sdk = auth._BoundedBlueprintAuth(auth.AgentAuthConfiguration(
        client_id=BLUEPRINT, tenant_id=TENANT, client_secret="fake"
    ))
    client = object.__new__(RealMsalClient)
    client.acquire_token_for_client = Mock(return_value={"access_token": "parent-assertion"})
    sdk._get_client = Mock(return_value=client)
    result = asyncio.run(sdk.get_agentic_application_token(TENANT, CHILD))
    assert result == "parent-assertion"
    client.acquire_token_for_client.assert_called_once_with(
        ["api://AzureAdTokenExchange/.default"], data={"fmi_path": CHILD}
    )


def test_graph_exchange_uses_child_and_both_assertions(adapter, token_factory, monkeypatch):
    token = token_factory()
    user = auth.UserContext(USER, TENANT, "Test User", "tester@example.com", token)
    adapter._parent_auth = SimpleNamespace(get_agentic_application_token=AsyncMock(return_value="parent-assertion"))
    child = Mock()
    child.acquire_token_on_behalf_of.return_value = {"access_token": "graph-access-token"}
    constructor = Mock(return_value=child)
    monkeypatch.setattr(auth, "ConfidentialClientApplication", constructor)
    assert asyncio.run(adapter.graph_token(user)) == "graph-access-token"
    adapter._parent_auth.get_agentic_application_token.assert_awaited_once_with(TENANT, CHILD)
    args = constructor.call_args.kwargs
    assert args["client_id"] == CHILD
    assert args["client_credential"] == {"client_assertion": "parent-assertion"}
    assert args["timeout"] == auth.HTTP_TIMEOUT
    child.acquire_token_on_behalf_of.assert_called_once_with(
        user_assertion=token, scopes=["https://graph.microsoft.com/.default"]
    )


def test_user_context_cannot_switch_subject(adapter, token_factory):
    user = auth.UserContext(CHILD, TENANT, "Test", "tester@example.com", token_factory())
    adapter._parent_auth = SimpleNamespace(get_agentic_application_token=AsyncMock())
    with pytest.raises(auth.AuthError, match="user context"):
        asyncio.run(adapter.graph_token(user))
    adapter._parent_auth.get_agentic_application_token.assert_not_awaited()


def test_graph_error_is_sanitized_and_has_no_fallback(adapter, token_factory, monkeypatch):
    user = auth.UserContext(USER, TENANT, "Test", "tester@example.com", token_factory())
    adapter._parent_auth = SimpleNamespace(get_agentic_application_token=AsyncMock(return_value="parent-assertion"))
    child = Mock()
    child.acquire_token_on_behalf_of.return_value = {"error": "invalid_grant", "error_description": "sensitive-error-details"}
    monkeypatch.setattr(auth, "ConfidentialClientApplication", Mock(return_value=child))
    with pytest.raises(auth.AuthError, match="Graph OBO failed") as exc:
        asyncio.run(adapter.graph_token(user))
    assert "sensitive-error-details" not in str(exc.value)
    child.acquire_token_for_client.assert_not_called()
