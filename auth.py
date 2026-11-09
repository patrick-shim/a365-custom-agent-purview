"""Local web sign-in and the Agent ID two-hop human-user OBO flow.

The browser signs in to an ordinary confidential web client. Its access token
targets the blueprint API. The blueprint authenticates its child with FMI; the
child then exchanges the human's assertion for delegated Microsoft Graph access.
No app-only, Azure CLI, or agent-user identity fallback is used for OneDrive.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import jwt
from jwt import PyJWKClient
from microsoft_agents.authentication.msal import MsalAuth
from microsoft_agents.hosting.core import AgentAuthConfiguration, AuthTypes
from msal import ConfidentialClientApplication


GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]
HTTP_TIMEOUT = (5, 20)


class AuthError(Exception):
    """A safe, user-displayable authentication failure without token details."""


@dataclass(frozen=True)
class UserContext:
    oid: str
    tenant_id: str
    name: str
    username: str
    user_assertion: str = field(repr=False)


class _BoundedBlueprintAuth(MsalAuth):
    """Keep the SDK's FMI implementation, with bounded MSAL HTTP calls.

    The pinned SDK constructs its MSAL application in this protected factory.
    This local-development adapter deliberately supports a blueprint secret only.
    The public get_agentic_application_token method performs the FMI exchange.
    """

    def _create_client_application(self, tenant_id: str | None = None):
        config = self.configuration
        return ConfidentialClientApplication(
            client_id=config.CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{tenant_id or config.TENANT_ID}",
            client_credential=config.CLIENT_SECRET,
            timeout=HTTP_TIMEOUT,
            exclude_scopes=["offline_access"],
        )


class AgentOboAuth:
    _required = (
        "entra_tenant_id",
        "web_client_id",
        "web_client_secret",
        "redirect_uri",
        "blueprint_client_id",
        "blueprint_client_secret",
        "agent_identity_id",
        "blueprint_scope",
    )
    _identifiers = (
        "entra_tenant_id", "web_client_id", "blueprint_client_id", "agent_identity_id"
    )

    def __init__(self, settings: Any):
        self.settings = settings
        self._web_client: ConfidentialClientApplication | None = None
        self._parent_auth: MsalAuth | None = None
        self._jwks: PyJWKClient | None = None
        self._client_lock = Lock()

    def missing_settings(self) -> list[str]:
        """Return missing/invalid configuration keys, never configuration values."""
        missing = []
        for name in self._required:
            value = str(getattr(self.settings, name, "") or "").strip()
            if not value or value.startswith(("<", "YOUR_", "REPLACE_")):
                missing.append(name.upper())
        for name in self._identifiers:
            if name.upper() in missing:
                continue
            try:
                UUID(str(getattr(self.settings, name)))
            except (ValueError, TypeError, AttributeError):
                missing.append(name.upper())
        if "REDIRECT_URI" not in missing:
            uri = urlparse(str(self.settings.redirect_uri))
            if (
                uri.scheme not in {"http", "https"}
                or not uri.hostname
                or uri.username
                or uri.password
                or uri.query
                or uri.fragment
                or (uri.scheme == "http" and uri.hostname not in {"localhost", "127.0.0.1", "::1"})
            ):
                missing.append("REDIRECT_URI")
        if "BLUEPRINT_SCOPE" not in missing and "BLUEPRINT_CLIENT_ID" not in missing:
            prefix = f"api://{self.settings.blueprint_client_id}/"
            scope = str(self.settings.blueprint_scope)
            if not scope.startswith(prefix) or scope[len(prefix):] in {"", ".default"} or " " in scope:
                missing.append("BLUEPRINT_SCOPE")
        return missing

    @property
    def ready(self) -> bool:
        return not self.missing_settings()

    def _require_ready(self) -> None:
        missing = self.missing_settings()
        if missing:
            raise AuthError("Complete the authentication settings: " + ", ".join(missing))

    @property
    def _authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.settings.entra_tenant_id}"

    def _get_web_client(self) -> ConfidentialClientApplication:
        self._require_ready()
        with self._client_lock:
            if self._web_client is None:
                self._web_client = ConfidentialClientApplication(
                    client_id=self.settings.web_client_id,
                    client_credential=self.settings.web_client_secret,
                    authority=self._authority,
                    timeout=HTTP_TIMEOUT,
                    exclude_scopes=["offline_access"],
                )
            return self._web_client

    def begin_login(self) -> dict:
        """Return an MSAL flow. Store the whole flow server-side, not in cookies."""
        self._require_ready()
        try:
            options = {
                "scopes": [self.settings.blueprint_scope],
                "redirect_uri": self.settings.redirect_uri,
                "response_mode": "query",
                "prompt": "select_account",
            }
            if getattr(self.settings, "expected_user", ""):
                options["login_hint"] = self.settings.expected_user
            flow = self._get_web_client().initiate_auth_code_flow(**options)
            if not isinstance(flow, dict) or not flow.get("auth_uri") or not flow.get("state"):
                raise AuthError("Microsoft sign-in could not be started. Check the web client registration.")
            return flow
        except AuthError:
            raise
        except Exception:
            raise AuthError("Microsoft sign-in is unavailable. Check the web client configuration and connectivity.") from None

    def _validate_assertion(self, token: str) -> dict:
        """Verify an access token for our v2 blueprint API, not an opaque Graph token."""
        if not isinstance(token, str) or not token:
            raise AuthError("Microsoft sign-in did not supply a blueprint access token.")
        try:
            with self._client_lock:
                if self._jwks is None:
                    self._jwks = PyJWKClient(
                        f"{self._authority}/discovery/v2.0/keys",
                        timeout=10,
                        cache_jwk_set=True,
                        lifespan=3600,
                    )
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.blueprint_client_id,
                issuer=f"{self._authority}/v2.0",
                leeway=30,
                options={"require": ["exp", "iat", "nbf", "aud", "iss", "tid", "oid", "scp"]},
            )
            if str(UUID(claims["tid"])) != str(UUID(self.settings.entra_tenant_id)):
                raise ValueError("Wrong tenant")
            UUID(claims["oid"])
            if claims.get("ver") != "2.0":
                raise ValueError("Blueprint must issue v2 access tokens")
            if claims.get("azp", "").lower() != self.settings.web_client_id.lower():
                raise ValueError("Unexpected calling client")
            scope_name = self.settings.blueprint_scope.rsplit("/", 1)[-1]
            if scope_name not in str(claims["scp"]).split():
                raise ValueError("Missing blueprint scope")
            return claims
        except Exception:
            raise AuthError("The user token is invalid or expired. Sign in again with the configured work account.") from None

    def complete_login(self, flow: dict, query: dict) -> UserContext:
        """MSAL checks OAuth state/nonce; signed access claims bind the user to OBO."""
        self._require_ready()
        try:
            result = self._get_web_client().acquire_token_by_auth_code_flow(flow, query)
            if not isinstance(result, dict) or not result.get("access_token"):
                raise AuthError("Microsoft sign-in failed. Check user consent and the web client registration.")
            assertion = result["access_token"]
            claims = self._validate_assertion(assertion)
            identity = result.get("id_token_claims", {})
            if not isinstance(identity, dict) or (
                identity.get("oid", "").lower() != claims["oid"].lower()
                or identity.get("tid", "").lower() != claims["tid"].lower()
            ):
                raise AuthError("The sign-in identity does not match the blueprint user token.")
            username = str(identity.get("preferred_username") or identity.get("upn") or "")
            expected = str(getattr(self.settings, "expected_user", "") or "").strip()
            if expected and username.casefold() != expected.casefold():
                raise AuthError("Sign in with the work account configured for this test.")
            return UserContext(
                oid=claims["oid"],
                tenant_id=claims["tid"],
                name=str(identity.get("name") or username or "Signed-in user"),
                username=username,
                user_assertion=assertion,
            )
        except AuthError:
            raise
        except Exception:
            raise AuthError("Microsoft sign-in could not be completed. Start sign-in again.") from None

    async def graph_token(self, user: UserContext) -> str:
        """Acquire Graph delegated access as the child agent for this human user."""
        self._require_ready()
        try:
            claims = await asyncio.to_thread(self._validate_assertion, user.user_assertion)
            if claims["oid"].lower() != user.oid.lower() or claims["tid"].lower() != user.tenant_id.lower():
                raise AuthError("The signed-in user context is invalid. Sign in again.")
            if self._parent_auth is None:
                self._parent_auth = _BoundedBlueprintAuth(AgentAuthConfiguration(
                    auth_type=AuthTypes.client_secret,
                    client_id=self.settings.blueprint_client_id,
                    tenant_id=self.settings.entra_tenant_id,
                    client_secret=self.settings.blueprint_client_secret,
                ))
            # The SDK sends fmi_path=child agent ID while authenticating the blueprint.
            parent_assertion = await asyncio.wait_for(
                self._parent_auth.get_agentic_application_token(
                    self.settings.entra_tenant_id, self.settings.agent_identity_id
                ),
                timeout=40,
            )
            if not parent_assertion:
                raise AuthError("The blueprint could not authenticate this agent identity. Check its credentials and registration.")

            def exchange() -> dict:
                # IMPORTANT: this client ID is the CHILD, not the blueprint or web app.
                child = ConfidentialClientApplication(
                    client_id=self.settings.agent_identity_id,
                    authority=self._authority,
                    client_credential={"client_assertion": parent_assertion},
                    timeout=HTTP_TIMEOUT,
                    exclude_scopes=["offline_access"],
                )
                return child.acquire_token_on_behalf_of(
                    user_assertion=user.user_assertion,
                    scopes=GRAPH_SCOPES,
                )

            result = await asyncio.wait_for(asyncio.to_thread(exchange), timeout=40)
            if not isinstance(result, dict) or not result.get("access_token"):
                raise AuthError("Graph OBO failed. Check the agent's delegated Graph grant and user consent, then sign in again.")
            return result["access_token"]
        except AuthError:
            raise
        except Exception:
            raise AuthError("Graph OBO is unavailable. Check the agent identity configuration and connectivity.") from None
