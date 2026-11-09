"""Purview policy location follows the actual OBO child client by default."""

import pytest

import config


CHILD = "11111111-1111-4111-8111-111111111111"
BLUEPRINT = "22222222-2222-4222-8222-222222222222"
OVERRIDE = "33333333-3333-4333-8333-333333333333"


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    # Never read the developer's .env or inherit their live tenant credentials.
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    for name in config.Settings.__dataclass_fields__:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.mark.parametrize("override", [None, "", "   "])
def test_purview_defaults_to_obo_child_not_blueprint(monkeypatch, override):
    monkeypatch.setenv("AGENT_IDENTITY_ID", CHILD)
    monkeypatch.setenv("BLUEPRINT_CLIENT_ID", BLUEPRINT)
    if override is not None:
        monkeypatch.setenv("PURVIEW_APP_ID", override)
    assert config.Settings.from_env().purview_app_id == CHILD


def test_explicit_purview_location_override_is_preserved(monkeypatch):
    monkeypatch.setenv("AGENT_IDENTITY_ID", CHILD)
    monkeypatch.setenv("BLUEPRINT_CLIENT_ID", BLUEPRINT)
    monkeypatch.setenv("PURVIEW_APP_ID", OVERRIDE)
    assert config.Settings.from_env().purview_app_id == OVERRIDE


def test_missing_child_does_not_silently_use_blueprint(monkeypatch):
    monkeypatch.setenv("BLUEPRINT_CLIENT_ID", BLUEPRINT)
    assert config.Settings.from_env().purview_app_id == ""
