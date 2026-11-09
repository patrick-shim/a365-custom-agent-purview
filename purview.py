"""Microsoft Purview policy evaluation at the application's data boundary.

Document text is incoming model content (``uploadText``), not a URL to be
dereferenced by Purview. The application must supply the entire supported file.
An input is released only after a matching inline scope and a complete verdict.
Response ``downloadText`` checks can be audit-only; an accepted audit submission
is deliberately not represented as proof that sensitive output was filtered.
"""

from __future__ import annotations

import json
import logging
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx


LOGGER = logging.getLogger("agent.policy")
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
_ACTIVITIES = {"none", "uploadText", "uploadFile", "downloadText", "downloadFile"}


class PurviewError(RuntimeError):
    """An evaluation could not safely complete. Never contains submitted text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    blocked: bool
    reason: str
    activity: str
    correlation_id: str
    # True means an evaluation/audit submission was accepted, not that a portal
    # has ingested it or that an offline audit has completed.
    audited: bool
    inline_evaluated: bool = False


@dataclass(frozen=True)
class _Scope:
    inline: bool
    restriction: str | None
    etag: str


class PurviewEvaluator:
    """Evaluate using Graph v1.0, with no fail-open or local-regex fallback.

    This sample computes scopes for every request rather than maintaining a
    cross-user policy cache. Inject an AsyncClient for tests; injected clients
    remain owned by their caller. Call ``aclose`` for a client created here.
    """

    def __init__(self, settings: Any, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def evaluate(
        self,
        text: str,
        user_id: str,
        graph_token: str,
        *,
        stage: str,
        correlation_id: str,
        file_metadata: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Return a decision or raise a sanitized error; callers must stop on both.

        ``prompt`` and ``file`` require inline uploadText protection. ``response``
        permits a configured offline downloadText audit unless
        ``require_inline_output`` is true. No content or tokens are logged.
        """
        activity = "downloadText" if stage == "response" else "uploadText"
        safe_user: str | None = None
        safe_correlation: str | None = None
        try:
            if stage not in {"prompt", "file", "response"}:
                raise PurviewError("invalid_stage", "Unsupported policy evaluation stage.")
            safe_user = self._uuid(user_id, "user_id")
            safe_correlation = self._uuid(correlation_id, "correlation_id")
            app_id = self._uuid(getattr(self.settings, "purview_app_id", ""), "purview_app_id")
            base_url = getattr(self.settings, "graph_base_url", GRAPH_BASE_URL).rstrip("/")
            if base_url != GRAPH_BASE_URL:
                raise PurviewError("invalid_graph_endpoint", "The Graph endpoint must be the Microsoft Graph v1.0 endpoint.")
            if not isinstance(graph_token, str) or not graph_token.strip():
                raise PurviewError("missing_token", "A delegated Graph token is required for policy evaluation.")
            if not isinstance(text, str) or not text.strip():
                raise PurviewError("empty_content", "Policy evaluation requires non-empty content.")
            try:
                encoded_length = len(text.encode("utf-8"))
            except UnicodeError:
                raise PurviewError("invalid_text", "The content is not valid UTF-8 text.") from None
            if encoded_length > self.settings.max_text_bytes:
                raise PurviewError("content_too_large", "The complete content exceeds the configured inspection limit.")

            require_inline = stage != "response" or self.settings.require_inline_output
            headers = {
                "Authorization": f"Bearer {graph_token}",
                "Content-Type": "application/json",
                "Prefer": "include-unknown-enum-members",
                "Client-Request-Id": safe_correlation,
            }
            path = f"{base_url}/users/{safe_user}/dataSecurityAndGovernance"
            payload = self._content_payload(text, encoded_length, app_id, stage, safe_correlation, file_metadata)

            scope = await self._compute_scope(path, headers, app_id, activity, payload["contentToProcess"])
            if scope.restriction:
                return self._decision(False, scope.restriction, activity, safe_correlation,
                                      safe_user, stage, file_metadata, False, False)
            if require_inline and not scope.inline:
                raise PurviewError("inline_policy_required", "An inline Purview policy is required for this activity and application.")

            process_headers = {**headers, "If-None-Match": scope.etag}
            if scope.inline:
                process_headers["Prefer"] = "include-unknown-enum-members, evaluateInline"
            response = await self._post(f"{path}/processContent", process_headers, payload)
            if response.status_code in {202, 204}:
                if require_inline or scope.inline:
                    raise PurviewError("missing_inline_verdict", "Purview did not return a completed inline decision.")
                if response.content:
                    raise PurviewError("unexpected_async_body", "Purview returned an unexpected asynchronous response.")
                return self._decision(True, "output_audit_submitted", activity, safe_correlation,
                                      safe_user, stage, file_metadata, True, False)
            if response.status_code != 200:
                raise PurviewError("process_http_error", "Purview content evaluation failed. Check permissions and service availability.")

            body = self._object(response)
            errors = body.get("processingErrors")
            if not isinstance(errors, list):
                raise PurviewError("incomplete_verdict", "Purview returned an incomplete content evaluation.")
            if errors:
                raise PurviewError("processing_error", "Purview could not inspect all submitted content.")
            state = body.get("protectionScopeState")
            if state not in {"modified", "notModified"}:
                raise PurviewError("unknown_scope_state", "Purview returned an unrecognized policy state.")
            restriction = self._restriction(body.get("policyActions"))
            if restriction:
                # A completed content restriction is authoritative and cannot
                # be weakened by refreshing cached protection-scope metadata.
                return self._decision(False, restriction, activity, safe_correlation,
                                      safe_user, stage, file_metadata, True, scope.inline)
            if state == "modified":
                # Graph defines modified as a scope-cache refresh signal, not
                # a failed content evaluation. Refresh context and enforce the
                # completed verdict; do not demand ETag convergence or submit
                # the same content again. See Purview's use-the-api tutorial.
                refreshed = await self._compute_scope(path, headers, app_id, activity,
                                                      payload["contentToProcess"])
                if refreshed.restriction:
                    return self._decision(False, f"refreshed_scope_{refreshed.restriction}", activity,
                                          safe_correlation, safe_user, stage, file_metadata, True, scope.inline)
                if require_inline and not refreshed.inline:
                    raise PurviewError("inline_policy_required", "An inline Purview policy is required for this activity and application.")
                if not scope.inline and refreshed.inline:
                    raise PurviewError("output_policy_requires_inline", "The output policy now requires inline inspection. The response was withheld.")

            reason = "inline_evaluation_permitted" if scope.inline else "output_audit_evaluated"
            return self._decision(True, reason, activity, safe_correlation, safe_user,
                                  stage, file_metadata, True, scope.inline)
        except PurviewError as exc:
            self._log(stage if stage in {"prompt", "file", "response"} else "invalid", activity,
                      safe_user, safe_correlation, "error", exc.code, file_metadata,
                      audited=False, inline=False)
            raise
        except (TypeError, ValueError, AttributeError):
            self._log(stage if stage in {"prompt", "file", "response"} else "invalid", activity,
                      safe_user, safe_correlation, "error", "invalid_configuration", file_metadata,
                      audited=False, inline=False)
            raise PurviewError("invalid_configuration", "The policy evaluator configuration or response is invalid.") from None

    async def _compute_scope(
        self, path: str, headers: dict[str, str], app_id: str, activity: str,
        content_context: dict[str, Any],
    ) -> _Scope:
        response = await self._post(
            f"{path}/protectionScopes/compute", headers,
            {"activities": activity,
             "locations": [{"@odata.type": "microsoft.graph.policyLocationApplication", "value": app_id}],
             # Match the processContent policy context, as the Agent Framework
             # Purview processor does; a scope version describes this context.
             "deviceMetadata": content_context["deviceMetadata"],
             "integratedAppMetadata": content_context["integratedAppMetadata"]},
        )
        if response.status_code != 200:
            raise PurviewError("scope_http_error", "Purview protection scopes could not be computed.")
        body = self._object(response)
        scopes = body.get("value")
        if not isinstance(scopes, list) or body.get("@odata.nextLink"):
            raise PurviewError("invalid_scopes", "Purview returned incomplete protection scopes.")
        etag = response.headers.get("ETag")
        if not etag:
            raise PurviewError("missing_scope_etag", "Purview did not provide the policy version required for evaluation.")
        # The Microsoft Agent Framework Python Purview client sends the opaque
        # scope identifier without its enclosing ETag quotation marks in the
        # processContent If-None-Match header.
        etag = self._policy_version(etag)
        if not etag:
            raise PurviewError("missing_scope_etag", "Purview did not provide the policy version required for evaluation.")

        matched = False
        inline = False
        restrictions: list[str] = []
        for scope in scopes:
            if not isinstance(scope, dict) or not isinstance(scope.get("activities"), str):
                raise PurviewError("invalid_scopes", "Purview returned malformed protection scopes.")
            activities = {item.strip() for item in scope["activities"].split(",")}
            if not activities or not activities.issubset(_ACTIVITIES):
                raise PurviewError("unknown_activity", "Purview returned an unrecognized protected activity.")
            if activity not in activities:
                continue
            locations = scope.get("locations")
            if not isinstance(locations, list):
                raise PurviewError("invalid_scopes", "Purview returned malformed protection locations.")
            matches_location = any(
                isinstance(location, dict)
                and str(location.get("value", "")).lower() == app_id
                and str(location.get("@odata.type", "microsoft.graph.policyLocationApplication")).lstrip("#")
                    == "microsoft.graph.policyLocationApplication"
                for location in locations
            )
            if not matches_location:
                continue
            matched = True
            mode = scope.get("executionMode")
            if mode not in {"evaluateInline", "evaluateOffline"}:
                raise PurviewError("unknown_execution_mode", "Purview returned an unrecognized execution mode.")
            inline |= mode == "evaluateInline"
            restriction = self._restriction(scope.get("policyActions"))
            if restriction:
                restrictions.append(restriction)
        if not matched:
            raise PurviewError("missing_policy_scope", "No Purview protection scope applies to this user, application, and activity.")
        restriction = "policy_block" if "policy_block" in restrictions else (restrictions[0] if restrictions else None)
        return _Scope(inline=inline, restriction=restriction, etag=etag)

    @staticmethod
    def _policy_version(etag: str) -> str:
        # Remove one surrounding pair only. Do not equate weak validators,
        # rewrite the opaque value, or ignore an actual policy-state change.
        return etag[1:-1] if len(etag) >= 2 and etag.startswith('"') and etag.endswith('"') else etag

    async def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> httpx.Response:
        try:
            return await self._client.post(url, headers=headers, json=payload,
                                           timeout=_TIMEOUT, follow_redirects=False)
        except httpx.HTTPError:
            # HTTP exceptions may embed requests/URLs. Do not propagate them.
            raise PurviewError("service_unavailable", "Purview could not be reached. No content was released.") from None

    @staticmethod
    def _object(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            raise PurviewError("invalid_json", "Purview returned an unreadable response.") from None
        if not isinstance(body, dict):
            raise PurviewError("invalid_json", "Purview returned an unexpected response shape.")
        return body

    @staticmethod
    def _restriction(actions: Any) -> str | None:
        if not isinstance(actions, list):
            raise PurviewError("missing_policy_actions", "Purview did not return valid policy actions.")
        warning = False
        for action in actions:
            if not isinstance(action, dict) or action.get("action") != "restrictAccess":
                raise PurviewError("unknown_policy_action", "Purview returned an unsupported policy action; the request was stopped.")
            restriction = action.get("restrictionAction")
            if restriction == "block":
                return "policy_block"
            if restriction == "warn":
                warning = True  # This sample offers no user override.
            elif restriction != "audit":
                raise PurviewError("unknown_restriction", "Purview returned an unsupported restriction; the request was stopped.")
        return "policy_warning_no_override" if warning else None

    def _content_payload(
        self, text: str, length: int, app_id: str, stage: str,
        correlation_id: str, file_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        entry: dict[str, Any] = {
            "@odata.type": "microsoft.graph.processConversationMetadata",
            "identifier": str(uuid4()),
            "content": {"@odata.type": "microsoft.graph.textContent", "data": text},
            "name": {"prompt": "User prompt", "file": "OneDrive document input", "response": "Agent response"}[stage],
            "correlationId": correlation_id,
            "sequenceNumber": 0,
            "isTruncated": False,
            "length": length,
            "createdDateTime": now,
            "modifiedDateTime": now,
        }
        # Only the documented resource reference fields are forwarded. Document
        # metadata cannot override the content, policy activity, or app identity.
        if file_metadata:
            resource: dict[str, Any] = {
                "@odata.type": "microsoft.graph.resourceAccessDetail",
                "accessType": "read", "status": "success",
                # Required non-null Boolean in Graph v1.0 CSDL. This sample
                # reports no cross-prompt-injection detection; false is not a
                # security clearance or a claim that a CPI scanner ran.
                "isCrossPromptInjectionDetected": False,
            }
            for source, target in (("id", "identifier"), ("name", "name"), ("webUrl", "url")):
                value = file_metadata.get(source)
                if isinstance(value, str) and value:
                    resource[target] = value[:2048]
            if "identifier" in resource:
                entry["accessedResources_v2"] = [resource]
        blueprint = getattr(self.settings, "blueprint_client_id", "")
        agent_id = getattr(self.settings, "agent_identity_id", "")
        if blueprint and agent_id:
            entry["agents"] = [{
                "@odata.type": "microsoft.graph.aiAgentInfo",
                "blueprintId": self._uuid(blueprint, "blueprint_client_id"),
                "identifier": self._uuid(agent_id, "agent_identity_id"),
                "name": self.settings.app_name,
                "version": "0.1.0",
            }]
        return {"contentToProcess": {
            "contentEntries": [entry],
            "activityMetadata": {"activity": "downloadText" if stage == "response" else "uploadText"},
            "deviceMetadata": {
                "deviceType": "Unmanaged",
                "operatingSystemSpecifications": {
                    "operatingSystemPlatform": platform.system(),
                    "operatingSystemVersion": platform.release(),
                },
            },
            "protectedAppMetadata": {
                "name": self.settings.app_name, "version": "0.1.0",
                "applicationLocation": {"@odata.type": "microsoft.graph.policyLocationApplication", "value": app_id},
            },
            "integratedAppMetadata": {"name": self.settings.app_name, "version": "0.1.0"},
        }}

    @staticmethod
    def _uuid(value: str, field: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise PurviewError(f"invalid_{field}", f"A valid {field} is required for policy evaluation.") from None

    def _decision(
        self, allowed: bool, reason: str, activity: str, correlation_id: str,
        user_id: str, stage: str, file_metadata: dict[str, Any] | None,
        audited: bool, inline: bool,
    ) -> PolicyDecision:
        self._log(stage, activity, user_id, correlation_id, "allow" if allowed else "block",
                  reason, file_metadata, audited=audited, inline=inline)
        return PolicyDecision(allowed, not allowed, reason, activity, correlation_id, audited, inline)

    @staticmethod
    def _log(
        stage: str, activity: str, user_id: str | None, correlation_id: str | None,
        outcome: str, reason: str, file_metadata: dict[str, Any] | None,
        *, audited: bool, inline: bool,
    ) -> None:
        event: dict[str, Any] = {
            "event": "purview_decision", "stage": stage, "activity": activity,
            "user_id": user_id, "correlation_id": correlation_id,
            "outcome": outcome, "reason": reason,
            "audit_submitted": audited, "inline_evaluated": inline,
        }
        if isinstance(file_metadata, dict):
            for source, target in (("id", "file_id"), ("eTag", "file_version")):
                value = file_metadata.get(source)
                if isinstance(value, str):
                    event[target] = value[:512]
        LOGGER.info(json.dumps(event, ensure_ascii=True, separators=(",", ":")))
