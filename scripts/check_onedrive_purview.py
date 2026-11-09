"""Browser-authenticated OneDrive/Purview diagnostic; never calls Foundry.

Stop app.py first, run this script, and sign in through the usual local UI.
Sending a chat checks TEST_FILE_PATH and a fixed synthetic prompt, ignoring chat
text/history. The optional file field must match that configured path exactly.
Use --mode pipeline to exercise ProtectedAgent with a hard model-boundary stop.
Only decision metadata is written to .local/live-probe.jsonl. Tokens remain in
memory; neither document text nor file names/URLs are written to that evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import AgentError, ChatResult, PolicyBlocked, ProtectedAgent
from auth import AgentOboAuth, AuthError
from config import ROOT, Settings
from extractors import DocumentError
from onedrive import OneDriveClient, normalize_path
from purview import PurviewError, PurviewEvaluator


SYNTHETIC_PROMPT = "Run the OneDrive document policy diagnostic."


def _safe_graph_error(body):
    """Classify a Graph error without retaining any free-form service text."""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {"shape": "missing_error_object"}
    code, message, target = error.get("code"), error.get("message"), error.get("target")
    known_codes = {"badrequest", "invalidrequest", "invalidargument", "invalidrequestbody",
                   "request_badrequest", "request_resource_notfound", "authorization_requestdenied",
                   "invalidcontent", "unsupportedcontenttype", "invalidjson", "accessdenied", "forbidden",
                   "unauthorized", "unknownerror", "internalservererror", "toomanyrequests", "paymentrequired"}
    fields = ("contentToProcess", "contentEntries", "accessedResources_v2", "accessedResources",
              "resourceAccessDetail", "processConversationMetadata", "aiAgentInfo", "agents", "blueprintId",
              "identifier", "storageId", "labelId", "name", "url", "accessType", "status",
              "isCrossPromptInjectionDetected", "content", "data", "length", "isTruncated", "correlationId",
              "sequenceNumber", "createdDateTime", "modifiedDateTime", "protectedAppMetadata",
              "applicationLocation", "deviceMetadata", "integratedAppMetadata", "activityMetadata",
              "resourceAccessType", "resourceAccessStatus", "Edm.String", "Edm.Boolean", "Edm.Int64")
    combined = " ".join(value[:16384] for value in (message, target) if isinstance(value, str))
    categories = {
        "missing_required_property": r"\brequired\b|\bmissing\b|must be (?:provided|specified|present)|cannot be (?:null|empty)",
        "unsupported_property_or_type": r"does not exist|not (?:supported|allowed|declared)|undeclared|unknown (?:property|type)",
        "invalid_type_or_conversion": r"cannot (?:convert|be converted)|type mismatch|expected (?:type|a|an)|invalid (?:type|value|format)",
        "malformed_request": r"malformed|invalid (?:json|request|payload)|(?:parse|parsing|deserializ)\w*",
        "invalid_resource_identifier": r"invalid (?:identifier|id|uri|url)|absolute (?:uri|url)|valid (?:guid|uuid|uri|url)",
        "limit_exceeded": r"too (?:long|large)|exceeds?|maximum|limit",
    }
    return {
        "code": code.lower() if isinstance(code, str) and code.lower() in known_codes else "unrecognized_or_missing",
        "code_sha256": sha256(code.encode()).hexdigest() if isinstance(code, str) else None,
        "message_chars": len(message) if isinstance(message, str) else None,
        "message_sha256": sha256(message.encode()).hexdigest() if isinstance(message, str) else None,
        "referenced_schema_fields": [field for field in fields if re.search(r"(?<![\w])" + re.escape(field) + r"(?![\w])", combined, re.IGNORECASE)],
        "validation_categories": [name for name, pattern in categories.items() if re.search(pattern, combined, re.IGNORECASE)],
    }


def _scope_response_hook(evidence):
    """Record allowlisted policy metadata, never raw URLs/headers/bodies."""
    def enum(value, choices):
        return value if isinstance(value, str) and value in choices else "unrecognized_or_missing"

    def actions(values):
        if not isinstance(values, list):
            return None
        return [{"action": enum(value.get("action"), {"restrictAccess", "unknownFutureValue"}),
                 "restrictionAction": enum(value.get("restrictionAction"), {"block", "warn", "audit", "unknownFutureValue"})}
                if isinstance(value, dict) else {"shape": "invalid"} for value in values[:10]]

    def digest(value):
        return sha256(value.encode()).hexdigest() if value else None

    def location(value):
        if not isinstance(value, dict):
            return {"shape": "invalid"}
        raw = value.get("value")
        result = {"type": enum(str(value.get("@odata.type", "omitted")).lstrip("#"), {
            "omitted", "microsoft.graph.policyLocationApplication", "microsoft.graph.policyLocationDomain",
            "microsoft.graph.policyLocationUrl", "microsoft.graph.policyLocation",
        })}
        try:
            result["value"] = str(UUID(raw))
        except (ValueError, TypeError, AttributeError):
            if isinstance(raw, str) and raw.lower() in {"*", "all", "allapplications"}:
                result["value"] = raw.lower()  # Diagnostic only, no wildcard authorization.
            else:
                result["value"] = "unrecognized_or_missing"
        return result

    async def capture(response):
        request = response.request
        is_scope = request.url.path.endswith("/dataSecurityAndGovernance/protectionScopes/compute")
        is_process = request.url.path.endswith("/dataSecurityAndGovernance/processContent")
        if request.url.host != "graph.microsoft.com" or not (is_scope or is_process):
            return
        records = evidence.setdefault("scope_http_diagnostics" if is_scope else "process_http_diagnostics", [])
        if len(records) >= 8:
            return
        etag = response.headers.get("ETag")
        record = {"stage": evidence["stage"], "response_status": response.status_code,
                  "etag_present": bool(etag), "etag_sha256": digest(etag),
                  "etag_unquoted_sha256": digest(etag.strip('"') if etag else None),
                  "etag_quoted": bool(etag and etag.startswith('"') and etag.endswith('"')),
                  "etag_weak": bool(etag and etag.startswith('W/'))}
        if is_process:
            sent = request.headers.get("If-None-Match")
            record.update({
                "request_etag_present": bool(sent), "request_etag_sha256": digest(sent),
                "request_etag_quoted": bool(sent and sent.startswith('"') and sent.endswith('"')),
                "etags_raw_equal": sent == etag if sent and etag else None,
                "etags_unquoted_equal": sent.strip('"') == etag.strip('"') if sent and etag else None,
                "requested_evaluate_inline": "evaluateInline" in {value.strip() for value in request.headers.get("Prefer", "").split(",")},
            })
        records.append(record)
        if response.status_code != 200:
            # Error text can echo submitted data. Only a fixed classification
            # vocabulary and hashes survive this diagnostic boundary.
            if 400 <= response.status_code <= 599:
                await response.aread()
                if len(response.content) <= 262144:
                    try:
                        record["graph_error"] = _safe_graph_error(response.json())
                    except (ValueError, UnicodeError):
                        record["graph_error"] = {"shape": "invalid_json"}
                else:
                    record["graph_error"] = {"shape": "too_large_to_inspect"}
            return
        await response.aread()
        if len(response.content) > 262144:
            record["scope_body_status"] = "too_large_to_record"
            return
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            record["scope_body_status"] = "invalid_json"
            return
        if is_process:
            if not isinstance(body, dict):
                record["process_body_status"] = "invalid_object"
                return
            errors = body.get("processingErrors")
            record.update({
                "protection_scope_state": enum(body.get("protectionScopeState"), {"modified", "notModified"}),
                "policy_actions": actions(body.get("policyActions")),
                "processing_error_count": len(errors) if isinstance(errors, list) else None,
                "processing_errors": [],
            })
            for error in errors[:10] if isinstance(errors, list) else []:
                if not isinstance(error, dict):
                    record["processing_errors"].append({"shape": "invalid"})
                    continue
                code = error.get("code")
                record["processing_errors"].append({
                    "code": enum(code, {"BadRequest", "InvalidRequest", "InvalidContent", "UnsupportedContentType",
                                        "ContentTooLarge", "FileTooLarge", "TooManyRequests", "ServiceUnavailable",
                                        "InternalServerError", "ClassificationFailure", "AccessDenied", "Unauthorized"}),
                    "code_sha256": digest(code) if isinstance(code, str) else None,
                    "error_type": enum(error.get("errorType"), {"transient", "permanent", "unknownFutureValue"}),
                })
            return
        scopes = body.get("value") if isinstance(body, dict) else None
        if not isinstance(scopes, list):
            record["scope_body_status"] = "missing_scope_collection"
            return
        record.update(scope_count=len(scopes), next_link_present=bool(body.get("@odata.nextLink")), scopes=[])
        for scope in scopes[:20]:
            if not isinstance(scope, dict):
                record["scopes"].append({"shape": "invalid"})
                continue
            flags = scope.get("activities", "").split(",") if isinstance(scope.get("activities"), str) else []
            locations = scope.get("locations")
            policy_actions = scope.get("policyActions")
            item = {
                "activities": [enum(flag.strip(), {"none", "uploadText", "uploadFile", "downloadText", "downloadFile", "unknownFutureValue"}) for flag in flags[:10]],
                "executionMode": enum(scope.get("executionMode"), {"evaluateInline", "evaluateOffline"}),
                "locations": [location(value) for value in locations[:10]] if isinstance(locations, list) else None,
                "location_count": len(locations) if isinstance(locations, list) else None,
                "policyActions": actions(policy_actions),
            }
            record["scopes"].append(item)
        record["scopes_omitted"] = max(0, len(scopes) - 20)
    return capture


class _ModelBoundaryReached(AgentError):
    pass


class _NoFoundry:
    """Deliberately has no model client, credentials, or HTTP implementation."""

    async def respond(self, *args, **kwargs):
        raise _ModelBoundaryReached("Diagnostic stopped at the model boundary.")


class _ObservedOneDrive:
    def __init__(self, client, evidence):
        self.client, self.evidence = client, evidence

    async def read_text(self, path, token):
        self.evidence["stage"] = "onedrive"
        document = await self.client.read_text(path, token)
        self.evidence.update({
            "onedrive_read_succeeded": True,
            "file_bytes": document.metadata["size"],
            "inspected_utf8_bytes": len(document.text.encode("utf-8")),
            "file_id_sha256": sha256(document.metadata["id"].encode()).hexdigest(),
            "file_version_sha256": sha256(document.metadata["eTag"].encode()).hexdigest(),
        })
        return document


class _ObservedPurview:
    def __init__(self, evaluator, evidence):
        self.evaluator, self.evidence = evaluator, evidence

    async def evaluate(self, *args, **kwargs):
        stage = kwargs["stage"]
        self.evidence["stage"] = stage
        # ProtectedAgent supplies its own correlation ID; record the real one.
        self.evidence["correlation_id"] = kwargs["correlation_id"]
        decision = await self.evaluator.evaluate(*args, **kwargs)
        self.evidence["decisions"].append({
            "stage": stage, "allowed": decision.allowed,
            "blocked": decision.blocked, "reason": decision.reason,
            "inline_evaluated": decision.inline_evaluated,
            "audit_submitted": decision.audited,
        })
        return decision


def _blocked_outcome(evidence):
    decision = evidence["decisions"][-1]
    suffix = "block" if decision["reason"].endswith("policy_block") else "warning_no_override"
    if decision["stage"] != "file":
        return f"prompt_policy_{suffix}"
    if decision["audit_submitted"] and decision["inline_evaluated"] and not decision["reason"].startswith("refreshed_scope_"):
        return f"file_content_policy_{suffix}"
    return f"file_scope_policy_{suffix}"


class ProbeAgent:
    def __init__(self, settings, auth, *, mode="direct", output_path=None):
        if mode not in {"direct", "pipeline"}:
            raise ValueError("Unknown diagnostic mode.")
        self.settings, self.auth, self.mode = settings, auth, mode
        self.output_path = output_path or ROOT / ".local" / "live-probe.jsonl"

    async def chat(self, user, prompt, file_path="", history=None):
        evidence = {
            "event": "onedrive_purview_live_probe",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode, "correlation_id": str(uuid4()),
            "stage": "path", "user_id": user.oid, "tenant_id": user.tenant_id,
            "onedrive_read_succeeded": False, "decisions": [],
            "foundry_http_calls": 0, "model_boundary_reached": False,
        }
        try:
            path = normalize_path(self.settings.test_file_path)
            if file_path and normalize_path(file_path) != path:
                raise DocumentError("The diagnostic only reads TEST_FILE_PATH.")
            async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), follow_redirects=False,
                                         event_hooks={"response": [_scope_response_hook(evidence)]}) as client:
                drive = _ObservedOneDrive(OneDriveClient(self.settings, client), evidence)
                policy = _ObservedPurview(PurviewEvaluator(self.settings, client), evidence)
                if self.mode == "pipeline":
                    evidence["stage"] = "authentication"
                    protected = ProtectedAgent(self.settings, self.auth, drive, policy, _NoFoundry())
                    await protected.chat(user, SYNTHETIC_PROMPT, path, [])
                    raise AgentError("The diagnostic reached an unexpected pipeline state.")
                else:
                    evidence["stage"] = "authentication"
                    token = await self.auth.graph_token(user)
                    # The diagnostic verifies delegated read independently of
                    # policy setup. It has no route to any model. Production
                    # ProtectedAgent retains its original pre-read prompt gate.
                    document = await drive.read_text(path, token)
                    decision = await policy.evaluate(
                        SYNTHETIC_PROMPT, user.oid, token,
                        stage="prompt", correlation_id=evidence["correlation_id"],
                    )
                    if not decision.allowed:
                        evidence["outcome"] = _blocked_outcome(evidence)
                    else:
                        decision = await policy.evaluate(
                            document.text, user.oid, token,
                            stage="file", correlation_id=evidence["correlation_id"],
                            file_metadata=document.metadata,
                        )
                        evidence["outcome"] = "file_content_permitted" if decision.allowed else _blocked_outcome(evidence)
        except _ModelBoundaryReached:
            evidence["model_boundary_reached"] = True
            evidence["outcome"] = "pipeline_permitted_stopped_before_model"
        except PolicyBlocked:
            evidence["outcome"] = _blocked_outcome(evidence)
        except PurviewError as error:
            evidence["outcome"] = "policy_evaluation_unavailable"
            evidence["error_code"] = error.code
            if self.mode == "direct" and evidence["stage"] == "prompt":
                evidence["file_evaluation_skipped"] = "prompt_check_unavailable_same_uploadText_scope"
        except AuthError:
            evidence["outcome"] = "authentication_failed"
        except DocumentError:
            evidence["outcome"] = "document_read_failed"
        except Exception:
            # Never record raw exceptions: library errors may contain tokens,
            # request URLs, or submitted text. This is not a content verdict.
            evidence["outcome"] = "diagnostic_failed"
        evidence["content_block_confirmed"] = evidence["outcome"] == "file_content_policy_block"
        evidence["interpretation"] = (
            "Purview returned a content restriction; inspect the correlated Purview event for the matched policy/SIT."
            if evidence["content_block_confirmed"] else
            "This result does not demonstrate a sensitive-information-type block."
        )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(evidence, separators=(",", ":")) + "\n")
        return ChatResult(json.dumps(evidence, indent=2), evidence["correlation_id"], False)


def create_probe_app(settings=None, *, mode="direct", output_path=None):
    from app import create_app
    from starlette.responses import Response
    from starlette.routing import Route

    settings = settings or Settings.from_env()
    auth = AgentOboAuth(settings)
    app = create_app(settings, auth_override=auth, agent_override=ProbeAgent(
        settings, auth, mode=mode, output_path=output_path,
    ))

    async def diagnostic_script(request):
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        script = script.replace(
            "(data.output_inline_evaluated ? 'Response evaluated inline.' : 'Response audit submitted; output filtering is not guaranteed.')",
            "'Diagnostic only. No Foundry call or response audit was performed.'",
        )
        return Response(script, media_type="application/javascript")

    # Exact route precedes the shared /static/{name} route; all security
    # middleware still applies. Production static assets remain unchanged.
    app.router.routes.insert(0, Route("/static/app.js", diagnostic_script, methods=["GET"]))
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("direct", "pipeline"), default="direct")
    args = parser.parse_args()
    settings = Settings.from_env()
    import uvicorn

    print(f"OneDrive/Purview diagnostic ({args.mode}); Foundry is disabled.")
    print(f"Open {settings.origin}, sign in, and send a message to check TEST_FILE_PATH.")
    print("Evidence: .local/live-probe.jsonl (metadata only). Stop the normal app before starting this diagnostic.")
    uvicorn.run(create_probe_app(settings, mode=args.mode), host="127.0.0.1",
                port=urlparse(settings.redirect_uri).port or 8000,
                access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
