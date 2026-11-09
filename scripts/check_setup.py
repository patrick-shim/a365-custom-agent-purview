"""Local configuration preflight; no tokens or secret values are printed."""
import argparse
import asyncio
from importlib.metadata import version
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth import AgentOboAuth
from config import Settings
from agent import FoundryClient


async def smoke(settings):
    client = FoundryClient(settings)
    try:
        response = await client.respond([{"role": "user", "content": "Reply with the single word READY."}], tools=False)
        if response.status != "completed" or not response.output_text:
            raise RuntimeError("No completed response")
        print("PASS Foundry connection: completed one synthetic connectivity request.")
        return True
    except Exception:
        print("FAIL Foundry connection. Verify endpoint, model, tenant login, and model RBAC.")
        return False
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-foundry", action="store_true", help="Make one paid, synthetic model request; never reads OneDrive.")
    args = parser.parse_args()
    settings = Settings.from_env()
    print("Python:", sys.version.split()[0])
    for package in ("microsoft-agents-a365-runtime", "microsoft-agents-authentication-msal", "msal", "openai"):
        print(f"{package}: {version(package)}")
    missing = AgentOboAuth(settings).missing_settings()
    for name in ("foundry_endpoint", "foundry_deployment", "foundry_tenant_id", "purview_app_id"):
        if not getattr(settings, name):
            missing.append(name.upper())
    if settings.foundry_auth_mode == "api_key" and not settings.foundry_api_key:
        missing.append("FOUNDRY_API_KEY")
    if missing:
        print("SETUP NEEDED:", ", ".join(sorted(set(missing))))
        print("See docs/onboarding.md. The server can start to show setup instructions, but protected chat requires these settings.")
    else:
        print("PASS Required local configuration is present; tenant permissions/policies still need a live test.")
    print("OneDrive and Purview tenant:", settings.entra_tenant_id or "not configured")
    print("Foundry tenant:", settings.foundry_tenant_id or "not configured")
    print("File formats: complete UTF-8 TXT only. No local-sync file bypass.")
    if args.check_foundry and not asyncio.run(smoke(settings)):
        return 1
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
