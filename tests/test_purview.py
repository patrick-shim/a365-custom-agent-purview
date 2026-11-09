import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from purview import PurviewError, PurviewEvaluator


APP_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
CORRELATION = "33333333-3333-4333-8333-333333333333"
SECRET_TEXT = "complete document: synthetic sensitive content at the very end"


def settings(**changes):
    defaults = dict(purview_app_id=APP_ID, app_name="Test agent", max_text_bytes=65536,
                    require_inline_output=False)
    return SimpleNamespace(**(defaults | changes))


def scope(activity="uploadText", mode="evaluateInline", actions=None, app_id=APP_ID):
    return {"activities": activity, "executionMode": mode,
            "locations": [{"@odata.type": "#microsoft.graph.policyLocationApplication", "value": app_id}],
            "policyActions": [] if actions is None else actions}


def scopes_response(scopes=None, etag='"policy-1"'):
    return httpx.Response(200, headers={"ETag": etag},
                          json={"value": [scope()] if scopes is None else scopes})


def verdict(actions=None, state="notModified", errors=None, **extra):
    return {"policyActions": [] if actions is None else actions,
            "processingErrors": [] if errors is None else errors,
            "protectionScopeState": state, **extra}


def block(restriction="block"):
    return {"@odata.type": "#microsoft.graph.restrictAccessAction",
            "action": "restrictAccess", "restrictionAction": restriction}


def run(responses, *, text=SECRET_TEXT, stage="file", config=None, metadata=None):
    calls = []

    def handler(request):
        calls.append(request)
        response = responses[len(calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    async def evaluate():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            evaluator = PurviewEvaluator(config or settings(), client)
            result = await evaluator.evaluate(text, USER_ID, "secret-graph-token", stage=stage,
                                             correlation_id=CORRELATION, file_metadata=metadata)
            return result, calls

    return asyncio.run(evaluate())


def test_complete_file_is_sent_as_input_before_allow():
    result, calls = run([scopes_response(), httpx.Response(200, json=verdict())],
                        metadata={"id": "file-1", "eTag": "v1", "name": "sensitive.txt", "webUrl": "https://tenant.sharepoint.com/file"})
    assert result.allowed and result.inline_evaluated and result.audited
    assert len(calls) == 2
    assert calls[0].url.path.endswith("/protectionScopes/compute")
    assert calls[1].headers["If-None-Match"] == "policy-1"
    body = json.loads(calls[1].content)["contentToProcess"]
    computed = json.loads(calls[0].content)
    assert computed["deviceMetadata"] == body["deviceMetadata"]
    assert computed["integratedAppMetadata"] == body["integratedAppMetadata"]
    assert calls[1].headers["Prefer"] == "include-unknown-enum-members, evaluateInline"
    assert body["activityMetadata"]["activity"] == "uploadText"
    entry = body["contentEntries"][0]
    assert entry["content"]["data"] == SECRET_TEXT
    assert entry["isTruncated"] is False
    assert entry["length"] == len(SECRET_TEXT.encode("utf-8"))
    assert entry["accessedResources_v2"][0]["identifier"] == "file-1"
    assert entry["accessedResources_v2"][0]["isCrossPromptInjectionDetected"] is False


@pytest.mark.parametrize("stage", ["file", "prompt", "response"])
def test_blocked_content_has_no_allow_decision(stage):
    activity = "downloadText" if stage == "response" else "uploadText"
    result, _ = run([scopes_response([scope(activity=activity)]),
                     httpx.Response(200, json=verdict([block()]))], stage=stage)
    assert result.blocked and not result.allowed
    assert result.reason == "policy_block"


def test_scope_level_block_prevents_content_submission():
    result, calls = run([scopes_response([scope(actions=[block()])])])
    assert result.blocked
    assert len(calls) == 1
    assert not result.audited


@pytest.mark.parametrize("scopes", [[], [scope(app_id="44444444-4444-4444-8444-444444444444")],
                                   [scope(activity="downloadText")]])
def test_missing_or_other_application_scope_never_allows(scopes):
    with pytest.raises(PurviewError) as error:
        run([scopes_response(scopes)])
    assert error.value.code == "missing_policy_scope"


def test_offline_input_policy_is_not_a_blocking_guarantee():
    with pytest.raises(PurviewError) as error:
        run([scopes_response([scope(mode="evaluateOffline")])])
    assert error.value.code == "inline_policy_required"


@pytest.mark.parametrize("status", [202, 204])
def test_async_input_result_never_counts_as_allow(status):
    with pytest.raises(PurviewError) as error:
        run([scopes_response(), httpx.Response(status)])
    assert error.value.code == "missing_inline_verdict"


@pytest.mark.parametrize("body", [{}, {"policyActions": []}, verdict(errors=[{"message": SECRET_TEXT}]),
                                  verdict(state="unknownFutureValue"), verdict(actions=[{"action": "newAction"}]),
                                  verdict(actions=[block("unknown")])])
def test_incomplete_or_unknown_result_fails_closed_without_sensitive_error(body):
    with pytest.raises(PurviewError) as error:
        run([scopes_response(), httpx.Response(200, json=body)])
    assert SECRET_TEXT not in str(error.value)
    assert "secret-graph-token" not in str(error.value)


def test_modified_policy_refreshes_scopes_and_consumes_completed_verdict():
    result, calls = run([
        scopes_response(), httpx.Response(200, json=verdict(state="modified")),
        scopes_response(etag='"policy-2"'),
    ])
    assert result.allowed and result.inline_evaluated and len(calls) == 3
    assert json.loads(calls[0].content) == json.loads(calls[2].content)


def test_new_policy_block_is_enforced_after_refresh():
    result, calls = run([
        scopes_response(), httpx.Response(200, json=verdict(state="modified")),
        scopes_response([scope(actions=[block()])], etag='"policy-2"'),
    ])
    assert result.blocked and len(calls) == 3


def test_modified_policy_with_failed_refresh_does_not_release_content():
    with pytest.raises(PurviewError) as error:
        run([scopes_response(), httpx.Response(200, json=verdict(state="modified")),
             httpx.Response(503)])
    assert error.value.code == "scope_http_error"


@pytest.mark.parametrize("computed,processed", [('"policy-1"', '"policy-1"'),
                                                ('"policy-1"', "policy-1"),
                                                ("policy-1", '"policy-1"')])
def test_scope_identifier_uses_sdk_quote_normalization(computed, processed):
    result, calls = run([scopes_response(etag=computed),
                        httpx.Response(200, headers={"ETag": processed}, json=verdict())])
    assert result.allowed and len(calls) == 2
    assert calls[1].headers["If-None-Match"] == "policy-1"


def test_response_etag_difference_is_not_an_authorization_signal():
    result, calls = run([scopes_response(etag='"policy-1"'),
                        httpx.Response(200, headers={"ETag": '"different-version"'}, json=verdict())])
    assert result.allowed and len(calls) == 2


def test_input_requires_inline_scope_after_modified_refresh():
    with pytest.raises(PurviewError) as error:
        run([scopes_response(), httpx.Response(200, json=verdict(state="modified")),
             scopes_response([scope(mode="evaluateOffline")])])
    assert error.value.code == "inline_policy_required"


def test_offline_output_upgraded_to_inline_is_withheld():
    with pytest.raises(PurviewError) as error:
        run([scopes_response([scope(activity="downloadText", mode="evaluateOffline")]),
             httpx.Response(200, json=verdict(state="modified")),
             scopes_response([scope(activity="downloadText", mode="evaluateInline")])], stage="response")
    assert error.value.code == "output_policy_requires_inline"


def test_inline_output_retains_actual_evaluation_flag_after_offline_refresh():
    result, _ = run([scopes_response([scope(activity="downloadText")]),
                     httpx.Response(200, json=verdict(state="modified")),
                     scopes_response([scope(activity="downloadText", mode="evaluateOffline")])], stage="response")
    assert result.allowed and result.inline_evaluated


def test_explicit_content_block_is_preserved_when_scope_state_modified():
    result, calls = run([scopes_response(), httpx.Response(200, json=verdict([block()], state="modified"))])
    assert result.blocked and result.reason == "policy_block"
    assert len(calls) == 2


def test_response_audit_is_distinguished_from_inline_clearance():
    result, calls = run([scopes_response([scope(activity="downloadText", mode="evaluateOffline")]),
                     httpx.Response(202)], stage="response")
    assert calls[1].headers["Prefer"] == "include-unknown-enum-members"
    assert result.allowed and result.audited
    assert not result.inline_evaluated
    assert result.reason == "output_audit_submitted"


def test_response_can_require_inline_protection_explicitly():
    with pytest.raises(PurviewError) as error:
        run([scopes_response([scope(activity="downloadText", mode="evaluateOffline")])],
            stage="response", config=settings(require_inline_output=True))
    assert error.value.code == "inline_policy_required"


def test_warn_has_no_override():
    result, _ = run([scopes_response(), httpx.Response(200, json=verdict([block("warn")]))])
    assert result.blocked and result.reason == "policy_warning_no_override"


def test_audit_action_is_understood_without_treating_it_as_block():
    result, _ = run([scopes_response(), httpx.Response(200, json=verdict([block("audit")]))])
    assert result.allowed


def test_combined_scopes_use_most_restrictive_mode():
    result, _ = run([scopes_response([scope(mode="evaluateOffline"), scope()]),
                     httpx.Response(200, json=verdict())])
    assert result.allowed and result.inline_evaluated


def test_unknown_mode_and_missing_policy_version_fail_closed():
    with pytest.raises(PurviewError):
        run([scopes_response([scope(mode="newMode")])])
    with pytest.raises(PurviewError) as error:
        run([httpx.Response(200, json={"value": [scope()]})])
    assert error.value.code == "missing_scope_etag"


def test_timeout_does_not_leak_content_or_token():
    with pytest.raises(PurviewError) as error:
        run([httpx.ReadTimeout(f"{SECRET_TEXT} secret-graph-token")])
    assert error.value.code == "service_unavailable"
    assert SECRET_TEXT not in str(error.value)
    assert "secret-graph-token" not in str(error.value)


def test_oversized_unicode_is_rejected_before_any_request():
    with pytest.raises(PurviewError) as error:
        run([], text="한" * 10, config=settings(max_text_bytes=20))
    assert error.value.code == "content_too_large"


def test_redirects_are_not_followed_with_graph_token():
    with pytest.raises(PurviewError):
        run([httpx.Response(302, headers={"Location": "https://untrusted.example"})])


def test_logs_include_decision_and_file_version_without_document_text(caplog):
    caplog.set_level("INFO", logger="agent.policy")
    run([scopes_response(), httpx.Response(200, json=verdict([block()]))],
        metadata={"id": "file-1", "eTag": "v7", "name": "private-title.txt"})
    assert SECRET_TEXT not in caplog.text
    assert "secret-graph-token" not in caplog.text
    assert "private-title.txt" not in caplog.text
    event = json.loads(caplog.records[-1].message)
    assert event["outcome"] == "block"
    assert event["file_id"] == "file-1" and event["file_version"] == "v7"
    assert event["correlation_id"] == CORRELATION
