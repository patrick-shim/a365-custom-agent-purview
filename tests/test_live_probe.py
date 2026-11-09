"""Probe evidence stays metadata-only, including the real pipeline boundary."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from fastapi.testclient import TestClient

from auth import UserContext
from config import Settings
from onedrive import Document
from purview import PolicyDecision, PurviewError
import scripts.check_onedrive_purview as probe


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def harness(monkeypatch, tmp_path):
    events = []
    user = UserContext("11111111-1111-4111-8111-111111111111",
                       "22222222-2222-4222-8222-222222222222",
                       "Test user", "test@example.com", "private-assertion")
    identity = SimpleNamespace(graph_token=AsyncMock(return_value="private-graph-token"))
    document = Document("private document contents", {
        "size": 25, "id": "private-id", "eTag": "private-version", "name": "private-name.txt",
    })

    async def read(path, token):
        events.append("onedrive")
        assert token == "private-graph-token"
        return document

    async def evaluate(text, user_id, token, **kwargs):
        events.append(kwargs["stage"])
        return PolicyDecision(True, False, "inline_evaluation_permitted", "uploadText",
                              kwargs["correlation_id"], True, True)

    drive = SimpleNamespace(read_text=AsyncMock(side_effect=read))
    policy = SimpleNamespace(evaluate=AsyncMock(side_effect=evaluate))
    monkeypatch.setattr(probe, "OneDriveClient", lambda *args: drive)
    monkeypatch.setattr(probe, "PurviewEvaluator", lambda *args: policy)
    output = tmp_path / "live-probe.jsonl"
    return SimpleNamespace(user=user, identity=identity, document=document, drive=drive,
                           policy=policy, events=events, output=output)


async def run(harness, mode="direct", path=""):
    agent = probe.ProbeAgent(Settings(), harness.identity, mode=mode, output_path=harness.output)
    result = await agent.chat(harness.user, "private ignored prompt", path,
                              [{"role": "user", "content": "private ignored history"}])
    evidence = json.loads(result.text)
    assert json.loads(harness.output.read_text()) == evidence
    assert evidence["foundry_http_calls"] == 0
    for private in ("private-graph-token", "private-assertion", "private document contents",
                    "private-id", "private-version", "private-name", "private ignored"):
        assert private not in result.text
    return evidence


@pytest.mark.anyio
async def test_direct_verifies_read_before_prompt_and_file_policy(harness):
    evidence = await run(harness)
    assert harness.events == ["onedrive", "prompt", "file"]
    assert evidence["outcome"] == "file_content_permitted"
    assert evidence["content_block_confirmed"] is False
    assert evidence["onedrive_read_succeeded"] is True
    assert evidence["file_bytes"] == 25
    assert evidence["inspected_utf8_bytes"] == 25
    assert len(evidence["file_id_sha256"]) == 64
    assert harness.policy.evaluate.call_args_list[1].args[0] == harness.document.text


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["direct", "pipeline"])
@pytest.mark.parametrize("scope_only", [True, False])
async def test_block_classifies_scope_and_content_without_model(harness, mode, scope_only):
    original = harness.policy.evaluate.side_effect

    async def evaluate(*args, **kwargs):
        if kwargs["stage"] == "file":
            return PolicyDecision(False, True, "policy_block", "uploadText",
                                  kwargs["correlation_id"], not scope_only, not scope_only)
        return await original(*args, **kwargs)

    harness.policy.evaluate.side_effect = evaluate
    evidence = await run(harness, mode)
    assert evidence["outcome"] == ("file_scope_policy_block" if scope_only else "file_content_policy_block")
    assert evidence["content_block_confirmed"] is (not scope_only)
    assert evidence["model_boundary_reached"] is False
    assert "matched policy/SIT" in evidence["interpretation"] if not scope_only else "does not demonstrate" in evidence["interpretation"]


@pytest.mark.anyio
async def test_missing_policy_keeps_independent_onedrive_read_evidence(harness):
    harness.policy.evaluate.side_effect = PurviewError("missing_policy_scope", "safe failure")
    evidence = await run(harness)
    assert evidence["outcome"] == "policy_evaluation_unavailable"
    assert evidence["error_code"] == "missing_policy_scope"
    assert evidence["content_block_confirmed"] is False
    assert evidence["onedrive_read_succeeded"] is True
    assert evidence["file_evaluation_skipped"] == "prompt_check_unavailable_same_uploadText_scope"
    harness.drive.read_text.assert_awaited_once()
    harness.policy.evaluate.assert_awaited_once()


@pytest.mark.anyio
async def test_pipeline_stops_at_model_boundary_on_permitted_file(harness):
    evidence = await run(harness, "pipeline")
    assert evidence["outcome"] == "pipeline_permitted_stopped_before_model"
    assert evidence["model_boundary_reached"] is True
    assert evidence["onedrive_read_succeeded"] is True
    assert evidence["content_block_confirmed"] is False


@pytest.mark.anyio
async def test_probe_only_accepts_configured_file(harness):
    evidence = await run(harness, path="different.txt")
    assert evidence["outcome"] == "document_read_failed"
    harness.identity.graph_token.assert_not_awaited()
    harness.drive.read_text.assert_not_awaited()


@pytest.mark.anyio
async def test_warning_is_not_claimed_as_service_block(harness):
    original = harness.policy.evaluate.side_effect

    async def evaluate(*args, **kwargs):
        if kwargs["stage"] == "file":
            return PolicyDecision(False, True, "policy_warning_no_override", "uploadText",
                                  kwargs["correlation_id"], True, True)
        return await original(*args, **kwargs)

    harness.policy.evaluate.side_effect = evaluate
    evidence = await run(harness)
    assert evidence["outcome"] == "file_content_policy_warning_no_override"
    assert evidence["content_block_confirmed"] is False


@pytest.mark.anyio
async def test_unknown_failure_never_serializes_exception(harness):
    harness.drive.read_text.side_effect = RuntimeError("private document contents private-graph-token")
    evidence = await run(harness)
    assert evidence["outcome"] == "diagnostic_failed"
    assert evidence["content_block_confirmed"] is False


@pytest.mark.anyio
async def test_scope_hook_captures_allowlisted_metadata_and_bounds_collections():
    evidence = {"stage": "prompt"}
    app_id = "11111111-1111-4111-8111-111111111111"
    scope = {"activities": "uploadText,downloadText", "executionMode": "evaluateInline",
             "locations": [{"value": app_id}, {"value": "*"}, {"value": "private-location"}],
             "policyActions": [{"action": "restrictAccess", "restrictionAction": "block", "private": "private-action"}],
             "private": "private-scope"}
    request = httpx.Request("POST", "https://graph.microsoft.com/v1.0/users/private-user/dataSecurityAndGovernance/protectionScopes/compute",
                            headers={"Authorization": "Bearer private-token"}, json={"private": "private-request"})
    response = httpx.Response(200, request=request, headers={"ETag": "private-etag"},
                              json={"value": [scope] * 30, "private": "private-body"})
    await probe._scope_response_hook(evidence)(response)
    diagnostic = evidence["scope_http_diagnostics"][0]
    assert diagnostic["response_status"] == 200
    assert diagnostic["etag_present"] is True
    assert diagnostic["scope_count"] == 30
    assert len(diagnostic["scopes"]) == 20
    assert diagnostic["scopes_omitted"] == 10
    assert diagnostic["scopes"][0]["locations"][0]["value"] == app_id
    assert diagnostic["scopes"][0]["locations"][1]["value"] == "*"
    assert "private" not in json.dumps(evidence)


@pytest.mark.anyio
async def test_scope_hook_proves_empty_response_not_location_parser_failure():
    evidence = {"stage": "prompt"}
    response = httpx.Response(200, json={"value": []}, headers={"ETag": "version"},
        request=httpx.Request("POST", "https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/protectionScopes/compute"))
    await probe._scope_response_hook(evidence)(response)
    assert evidence["scope_http_diagnostics"][0]["scope_count"] == 0
    assert evidence["scope_http_diagnostics"][0]["scopes"] == []


@pytest.mark.anyio
async def test_scope_hook_never_captures_file_or_processing_response():
    evidence = {"stage": "file"}
    for url in ("https://private.sharepoint.com/download?private-ticket", "https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent"):
        response = httpx.Response(200, text="private-content", request=httpx.Request("GET", url))
        await probe._scope_response_hook(evidence)(response)
    assert "scope_http_diagnostics" not in evidence
    assert "private" not in json.dumps(evidence)


@pytest.mark.anyio
async def test_process_hook_records_state_and_etag_comparison_without_secrets():
    evidence = {"stage": "prompt"}
    response = httpx.Response(200, headers={"ETag": "private-etag"},
        request=httpx.Request("POST", "https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent",
            headers={"Authorization": "Bearer private-token", "If-None-Match": '"private-etag"',
                     "Prefer": "include-unknown-enum-members, evaluateInline"}, content="private-request"),
        json={"protectionScopeState": "modified", "policyActions": [], "content": "private-content",
              "processingErrors": [{"code": "InvalidContent", "errorType": "permanent", "message": "private-message"}]})
    await probe._scope_response_hook(evidence)(response)
    record = evidence["process_http_diagnostics"][0]
    assert record["response_status"] == 200
    assert record["protection_scope_state"] == "modified"
    assert record["etags_raw_equal"] is False
    assert record["etags_unquoted_equal"] is True
    assert record["requested_evaluate_inline"] is True
    assert record["processing_error_count"] == 1
    assert record["processing_errors"][0]["code"] == "InvalidContent"
    assert record["policy_actions"] == []
    assert "private" not in json.dumps(evidence)


def test_probe_ui_does_not_claim_response_audit():
    app = probe.create_probe_app(Settings())
    client = TestClient(app)
    response = client.get("/static/app.js")
    assert response.status_code == 200
    assert "No Foundry call or response audit was performed." in response.text
    assert "Response audit submitted" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_graph_error_classification_never_exposes_echoed_document_or_token():
    evidence = {"stage": "file"}
    response = httpx.Response(400, request=httpx.Request("POST",
        "https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/processContent"),
        json={"error": {"code": "BadRequest", "message": (
            "The property 'storageId' is required on resourceAccessDetail in accessedResources_v2. "
            "private-filename.txt private-document-4111111111111111 Bearer private-token"
        ), "target": "contentToProcess.contentEntries[0].accessedResources_v2[0].storageId"}})
    await probe._scope_response_hook(evidence)(response)
    error = evidence["process_http_diagnostics"][0]["graph_error"]
    assert error["code"] == "badrequest"
    assert "storageId" in error["referenced_schema_fields"]
    assert "accessedResources_v2" in error["referenced_schema_fields"]
    assert "missing_required_property" in error["validation_categories"]
    serialized = json.dumps(evidence)
    assert "private" not in serialized and "4111111111111111" not in serialized and "Bearer" not in serialized
