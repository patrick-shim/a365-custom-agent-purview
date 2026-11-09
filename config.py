"""Configuration for the local, single-process test agent."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    entra_tenant_id: str = ""
    web_client_id: str = ""
    web_client_secret: str = field(default="", repr=False)
    redirect_uri: str = "http://localhost:8000/auth/callback"
    blueprint_client_id: str = ""
    blueprint_client_secret: str = field(default="", repr=False)
    agent_identity_id: str = ""
    blueprint_scope: str = ""
    expected_user: str = ""
    foundry_endpoint: str = ""
    foundry_deployment: str = ""
    foundry_tenant_id: str = ""
    foundry_auth_mode: str = "azure_cli"
    foundry_api_key: str = field(default="", repr=False)
    purview_app_id: str = ""
    app_name: str = "OneDrive Purview Agent"
    graph_base_url: str = "https://graph.microsoft.com/v1.0"
    require_inline_output: bool = False
    max_file_bytes: int = 131072
    max_text_bytes: int = 262144
    test_file_path: str = "test-summary.txt"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        values = {}
        for name in cls.__dataclass_fields__:
            value = os.environ.get(name.upper())
            if value is not None:
                values[name] = value.strip()
        for name in ("max_file_bytes", "max_text_bytes"):
            if name in values:
                values[name] = int(values[name])
        if "require_inline_output" in values:
            raw = values["require_inline_output"].lower()
            if raw not in {"true", "false"}:
                raise ValueError("REQUIRE_INLINE_OUTPUT must be true or false.")
            values["require_inline_output"] = raw == "true"
        # OBO Graph calls identify the child agent as the client. Purview's
        # default application location must match that identity, not its parent
        # blueprint. Retain an explicit override for a deliberately scoped policy.
        values["purview_app_id"] = values.get("purview_app_id") or values.get("agent_identity_id", "")
        settings = cls(**values)
        if not 1 <= settings.max_file_bytes <= settings.max_text_bytes <= 1048576:
            raise ValueError("Set positive MAX_FILE_BYTES <= MAX_TEXT_BYTES <= 1048576.")
        if settings.foundry_auth_mode not in {"azure_cli", "api_key"}:
            raise ValueError("FOUNDRY_AUTH_MODE must be azure_cli or api_key.")
        uri = urlparse(settings.redirect_uri)
        if uri.scheme != "http" or uri.hostname not in {"localhost", "127.0.0.1"} or uri.path != "/auth/callback":
            raise ValueError("This local scaffold requires a loopback HTTP /auth/callback redirect URI.")
        if settings.foundry_endpoint and urlparse(settings.foundry_endpoint).scheme != "https":
            raise ValueError("FOUNDRY_ENDPOINT must use HTTPS.")
        if settings.graph_base_url != "https://graph.microsoft.com/v1.0":
            raise ValueError("This scaffold supports the global Microsoft Graph v1.0 endpoint.")
        return settings

    @property
    def origin(self) -> str:
        uri = urlparse(self.redirect_uri)
        return f"{uri.scheme}://{uri.netloc}"
