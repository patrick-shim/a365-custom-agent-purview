# 온보딩과 검증 · Onboarding and validation

**.NET/a365 CLI가 허용되지 않거나 기존 ID를 전달받은 실행자:** 이 문서의 생성·등록·권한 변경 명령은 건너뛰고 [제한 환경 실행 안내](restricted-environment.md)를 사용합니다. 이 문서는 권한 있는 상위 부서의 온보딩 담당자용입니다. / Runtime-only customers should use the restricted guide; the provisioning commands here are for authorized upstream administrators.

이 문서는 기존 Blueprint를 재사용하는 관리자를 위한 보충 안내입니다. 처음 실행한다면 [README의 5단계](../README.md)를 먼저 따르세요. 환경값의 화면 위치와 생성 방법은 [환경값별 안내](environment-values.md), SIT와 DLP 구성은 [Purview 설정](purview-setup.md)에 있습니다. 모든 `<...>`는 사용자의 실제 환경값으로 바꿉니다.

This guide supplements the README for administrators reusing an existing blueprint. Start with [the five-step README](../README.md); use [field-by-field environment setup](environment-values.md) and [Purview configuration](purview-setup.md) for the corresponding tasks. The repository includes no live tenant credentials or private deployment identifiers.

## 1. 준비와 파일 역할 · Prerequisites and files

Microsoft 365 테스트 사용자와 OneDrive, Entra Agent ID를 사용할 수 있는 테넌트, Purview 정책·수집·과금 설정, 호출 가능한 Foundry 모델 배포가 필요합니다. Blueprint를 수정하거나 동의를 부여하는 사람에게는 해당 관리 권한이 필요합니다. 실행용 권한 세 개와 관리자 도구의 프로비저닝 권한을 구분합니다.

You need a Microsoft 365 user with OneDrive, an eligible Agent ID tenant, configured Purview policies/collection/billing, and a deployed Foundry model. Blueprint changes and delegated grants require appropriate administrative authority. Provisioning permissions belong to the administrator's tool; they are distinct from the agent's three runtime Graph scopes.

| 파일 / File | 용도 / Purpose | Git |
|---|---|---|
| `.env.example` | 빈 환경값 예제 / Empty environment template | 추적 / Tracked |
| `.env` | 실제 ID·endpoint·비밀값 / Local actual values | 제외 / Ignored |
| `a365.config.example.json` | CLI 정적 설정 예제 / Static CLI template | 추적 / Tracked |
| `a365.config.json` | 실제 CLI 테넌트·인증 앱·이름 / Local CLI configuration | 제외 / Ignored |
| `a365.generated.config.json` | Blueprint·자식·등록 ID 상태 / Generated identity state | 제외 / Ignored |
| `.local/`, `logs/` | 로컬 진단 및 판단 기록 / Local evidence and logs | 제외 / Ignored |

Git에서 복제한 후 두 예제를 기존 파일이 없을 때만 복사합니다. CLI 생성 상태는 README의 공개 ID 예제로 별도 복원합니다. 다른 자식의 `agentRegistrationId`를 재사용하지 않습니다.

After cloning, copy the two templates only if their active files do not exist. Restore generated CLI state using the README example, filled with your own IDs. Do not reuse another child's `agentRegistrationId`.

<a id="reuse-or-create-a-child-agent"></a>
## 2. 기존 자식 재사용 또는 새 자식 생성 · Reuse or create a child agent

**기존 자식이 있다면:** Entra 관리 센터에서 Blueprint의 Linked agent identities를 확인해 정확한 자식 ID를 복사합니다. `.env`의 `AGENT_IDENTITY_ID`와 `PURVIEW_APP_ID`, 생성 상태의 `agenticAppId`에 그 값을 넣습니다. CLI 정적 설정에는 실제 표시 이름을 입력합니다. 이미 등록된 자식은 생성·등록을 반복하지 않습니다.

**If the child exists:** find it under the blueprint's linked identities. Put its Object ID in `.env`'s `AGENT_IDENTITY_ID` and `PURVIEW_APP_ID`, and the generated state's `agenticAppId`. Set exact display names in the static CLI configuration. Existing registration does not require another creation or setup run.

**새 자식이 필요하다면:** 먼저 Blueprint Application ID, 사람인 sponsor의 사용자 Object ID, 권한이 준비된 CLI 인증 앱의 Application ID를 구합니다. 값의 위치는 [환경값 안내](environment-values.md)에 있습니다. 사용할 이름이 이미 존재하는지 포털에서 확인하고, 아래 생성 부분은 **한 번만** 실행합니다. 이 명령은 클라우드에 새 자식 ID를 만듭니다.

**If a new child is needed:** collect the Blueprint Application ID, the human sponsor's user Object ID, and the authorized CLI authentication application's client ID. Check the portal for an existing identity with the intended name. Run the following creation block **once**. It creates a cloud identity. The caller needs appropriate Agent ID administration/blueprint ownership and authorized provisioning scopes. [Agent identity creation API](https://learn.microsoft.com/en-us/graph/api/agentidentity-post?view=graph-rest-1.0)

이 블록 전에 README **3-9의 정적 CLI 설정**을 먼저 채웁니다. 자식 이름에는 만들 이름을 적을 수 있습니다. 아직 없는 자식 ID나 등록 ID를 지어내지 말고, 생성 상태 파일은 아래에서 ID를 반환받은 뒤 완성합니다. CLI 앱에는 이 생성 작업의 `AgentIdentity.Create.All` 동의가 필요합니다. / Complete the README's **static CLI settings in 3-9 first**, using the chosen new display name. Finish generated state only after creation returns the child ID; do not invent child or registration IDs. The CLI app must be authorized for `AgentIdentity.Create.All` for this operation.

```powershell
$cliClientId = '<authorized-cli-application-client-id>'
$blueprintId = '<existing-blueprint-application-client-id>'
$sponsorId = '<human-sponsor-user-object-id>'
$newAgentName = 'onedrive-purview-agent'

$tokenOutput = & a365 develop get-token --app-id $cliClientId --resource-id '00000003-0000-0000-c000-000000000000' --scopes '.default' --output raw
if ($LASTEXITCODE -ne 0) { throw 'CLI provisioning sign-in failed.' }
$jwtMatches = [regex]::Matches(($tokenOutput -join "`n"), 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')
if ($jwtMatches.Count -eq 0) { throw 'No provisioning token returned.' }
$headers = @{ Authorization = ('Bearer ' + $jwtMatches[$jwtMatches.Count - 1].Value); 'OData-Version' = '4.0' }
$tokenOutput = $null
$jwtMatches = $null

$body = @{
    displayName = $newAgentName
    agentIdentityBlueprintId = $blueprintId
    'sponsors@odata.bind' = @("https://graph.microsoft.com/v1.0/users/$sponsorId")
}
$newAgent = Invoke-RestMethod -ErrorAction Stop -Method Post -Uri 'https://graph.microsoft.com/v1.0/servicePrincipals/microsoft.graph.agentIdentity' -Headers $headers -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 6)
$headers = $null
$agentId = $newAgent.id
if (-not $agentId) { throw 'No new identity ID returned; do not continue.' }
$agentId
```

반환된 ID를 다음에 입력합니다. Blueprint를 재사용하므로 Blueprint의 세 ID와 기존 웹 로그인 앱은 유지할 수 있습니다. 자식 자체에 비밀값을 추가하지 않습니다.

Use the returned ID below. Reusing the blueprint permits retaining its three identity fields and the configured web sign-in app. Do not add credentials to the child itself.

| File | Setting | Value |
|---|---|---|
| `.env` | `AGENT_IDENTITY_ID`, `PURVIEW_APP_ID` | Returned child ID |
| `.env` | `APP_NAME` | Chosen agent display name |
| `a365.config.json` | `agentIdentityDisplayName` | Exact child display name |
| `a365.generated.config.json` | `agenticAppId` | Returned child ID |
| `a365.generated.config.json` | `agentRegistrationId` | Remove a previous child's property; the CLI records this child's registration. |

Blueprint가 달라지는 경우에는 `agentBlueprintId`(클라이언트 ID), `agentBlueprintObjectId`(애플리케이션 개체 ID), `agentBlueprintServicePrincipalObjectId`(서비스 주체 ID)를 모두 다시 확인합니다. 포털 Blueprint 목록의 Object ID는 서비스 주체 ID이며 애플리케이션 개체 ID와 혼동하면 안 됩니다.

If changing blueprints, update `agentBlueprintId` (client ID), `agentBlueprintObjectId` (application object ID), and `agentBlueprintServicePrincipalObjectId` (service-principal object ID). The portal blueprint list's Object ID identifies the service principal. Use the [environment guide's Graph lookup](environment-values.md) to distinguish these values.

## 3. 브라우저 로그인과 사용자별 동의 · Browser sign-in and consent

웹 앱은 일반 single-tenant App registration이며 Web callback은 `http://localhost:8000/auth/callback`입니다. 호환되는 기존 MSAL 웹 로그인 앱을 재사용하고, 없을 때만 새로 만듭니다. MSAL은 앱의 Client ID로 로그인·토큰 요청을 수행하는 라이브러리이며 앱 등록을 대신하지 않습니다. 이 앱의 클라이언트 ID와 비밀값은 `WEB_CLIENT_ID`, `WEB_CLIENT_SECRET`에 넣습니다. Blueprint는 별도 ID와 비밀값을 사용하고, v2 사용자 토큰을 받는 노출 API 범위가 있어야 합니다. API 범위와 비밀값을 준비하는 보존형 절차는 [환경값 안내](environment-values.md)에 있습니다.

The interactive web client is an ordinary single-tenant app registration with the exact Web callback above. Reuse an existing compatible MSAL Web client; create one only if absent. MSAL uses the registered Client ID for authentication and does not replace app registration. Its ID and secret populate `WEB_CLIENT_ID` and `WEB_CLIENT_SECRET`. The blueprint has separate credentials and an exposed API scope configured for v2 access tokens. Follow the [environment guide](environment-values.md) to inspect or add these without replacing existing scopes or credentials. The child, not this sign-in client, holds the Graph `Files.Read` permission.

사용자에게는 두 동의가 필요합니다. / Two distinct delegated grants are required:

| Grant | clientId | resourceId | scope |
|---|---|---|---|
| 웹 앱 → Blueprint / Web → blueprint | Web client service-principal Object ID | Blueprint service-principal Object ID | Exposed scope, for example `access_agent_as_user` |
| 자식 → Graph / Child → Graph | Child identity Object ID | Tenant's Microsoft Graph service-principal Object ID | `Files.Read Content.Process.User ProtectionScopes.Compute.User` |

두 동의 모두 `consentType=Principal`, `principalId=<test-user-object-id>`로 테스트 사용자 한 명에게 제한할 수 있습니다. README의 Graph 동의 명령은 기존 범위를 유지하며 필요한 세 범위를 추가하고 다시 조회합니다. 웹 앱 동의는 환경값 안내의 별도 절차를 사용합니다. `EXPECTED_USER`는 앱의 로그인 제한이며 동의를 생성하지 않습니다.

Both grants can use `consentType=Principal` and the selected user's Object ID as `principalId`. The README's Graph-grant block preserves existing scopes, adds missing required scopes, and reads the result back. Use the environment guide for the separate web-client grant. `EXPECTED_USER` limits local sign-in; it does not create consent. [Grant API](https://learn.microsoft.com/en-us/graph/api/oauth2permissiongrant-post?view=graph-rest-1.0)

이 직접 권한 모델에서는 Blueprint Graph 동의나 `inheritablePermissions`를 추가할 필요가 없습니다. 기존의 더 넓은 동의·상속은 별도로 확인하며 이 예제에서 자동 삭제하지 않습니다. / Direct child assignment does not require adding blueprint Graph grants or permission inheritance. Review any pre-existing broader grants/inheritance separately; this example does not remove them. [Direct and inherited permissions](https://learn.microsoft.com/en-us/entra/agent-id/migrate-custom-app-registrations-to-agent-id)

## 4. Agent 365 CLI 등록 · Registration

이 절차는 CLI **1.1.221**에서 확인했습니다. 정적 설정은 기존 Blueprint 이름과 자식 이름을 정확히 가리키고, 생성 상태에는 대응되는 ID가 있어야 합니다. `clientAppId`는 CLI 인증 앱이며 웹 앱 또는 Blueprint가 아닙니다.

This workflow was checked with CLI **1.1.221**. Static configuration must select exact blueprint/child names, and generated state must contain the matching IDs. `clientAppId` identifies the CLI's authentication app, not the interactive web client or blueprint.

```json
{
  "tenantId": "<ENTRA_TENANT_ID>",
  "clientAppId": "<CLI_CLIENT_APP_ID>",
  "agentIdentityDisplayName": "<AGENT_DISPLAY_NAME>",
  "agentBlueprintDisplayName": "<EXISTING_BLUEPRINT_DISPLAY_NAME>",
  "aiTeammate": false,
  "useBlueprint": true,
  "authMode": "obo"
}
```

등록이 아직 없거나 재시도가 필요할 때만 프로젝트 폴더에서 실행합니다. / Run from the project folder only when registration is missing or a retry is needed:

```powershell
a365 --version
a365 setup all --help
a365 query-entra instance-scopes
a365 setup all --agent-registration-only --dry-run
a365 setup all --agent-registration-only
```

등록 전용 경로는 **기존 자식**을 필요로 하며 새 자식 생성이나 Blueprint 권한 설정을 대신하지 않습니다. 해당 버전의 dry-run은 자식 ID가 없을 때 생성 문구를 보여 줄 수 있으므로 실제 생성 기능이라고 해석하지 마세요. 전체 `setup all`은 기본적으로 메일·채팅·파일 쓰기 등 넓은 권한을 구성할 수 있습니다. `--agent-name`은 파생 이름을 만들 수 있으므로 정확한 설정 파일 이름을 사용합니다.

Registration-only requires an **existing child**; it does not provision that child or its blueprint permissions. This version's dry-run may print creation wording when a child ID is missing, but the actual path still requires an existing child. Full setup can add broad default mail/chat/file-write permissions; additional custom scopes do not replace those defaults. Use exact names in configuration instead of derived `--agent-name` naming. [CLI reference](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/reference/cli/setup), [pinned implementation](https://github.com/microsoft/Agent365-devTools/blob/ea1579f37f/src/Microsoft.Agents.A365.DevTools.Cli/Commands/SetupSubcommands/NonDwBlueprintSetupOrchestrator.cs)

## 5. Purview와 모델 연결 · Purview and Foundry

[Purview 안내](purview-setup.md)에서 사용할 SIT, `uploadText` DLP 규칙, **자식 Agent ID와 테스트 사용자**를 설정합니다. `PURVIEW_APP_ID`는 이 OBO 경로의 자식 ID입니다. 파일 URL만 보내는 것이 아니라 전체 텍스트를 제출합니다. 적용 가능한 inline 입력 정책이 없으면 앱이 요청을 중단합니다.

Use [the Purview guide](purview-setup.md) to configure the SIT, UploadText rule, and **child identity plus intended user**. `PURVIEW_APP_ID` is the child identity in this OBO flow. The application sends complete text, not merely a file URL, and stops input processing without applicable inline protection.

`processContent`의 `protectionScopeState=modified`는 완료된 콘텐츠 판단을 무효화하지 않습니다. 앱은 같은 사용자·앱·활동의 scope를 새로 조회하고, 갱신된 제한과 inline 요구 사항을 확인한 뒤 반환된 판단을 적용합니다. 갱신 실패, 처리 오류, 알 수 없는 상태는 계속 실패 처리합니다. ETag 일치만을 위해 콘텐츠를 반복 제출하지 않습니다.

A completed `processContent` verdict remains valid when `protectionScopeState=modified`. The app refreshes the matching scope, enforces refreshed restrictions/inline requirements, and applies the completed verdict. Refresh failures, processing errors, and unknown states still fail closed; content is not repeatedly submitted merely to make ETags converge. Output that newly requires inline protection must complete inline before release. [Protocol guidance](https://learn.microsoft.com/en-us/purview/developer/use-the-api)

Foundry는 README와 환경값 안내에서 찾은 자신의 endpoint·deployment·tenant를 사용합니다. 모델 접근은 Azure CLI 또는 명시한 API 키, Graph 접근은 사람의 Agent ID OBO로 서로 분리됩니다. 다른 테넌트의 모델 사용 권한이 Microsoft 365 파일 접근 권한을 대신하지 않습니다.

Configure your own Foundry endpoint, deployment name, and tenant using the README/environment guide. Model authentication uses Azure CLI or an explicitly configured API key; Graph uses the human-user Agent ID OBO flow. Model access does not grant access to another tenant's Microsoft 365 files.

## 6. 실행과 실제 검증 · Run and validate

```powershell
.\.venv\Scripts\python.exe scripts/check_setup.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe app.py
```

설정 검사에서 빠진 값이 없으면 localhost 브라우저에서 테스트 사용자로 로그인합니다. 테스트 환경에서는 **152개 자동 테스트**, 일반 채팅의 실제 모델 응답, 실제 OneDrive 파일 차단이 확인되었습니다. 별도 진단은 93바이트 전체를 검사한 뒤 차단하고 Foundry를 호출하지 않았습니다. 이 결과가 새 테넌트의 정책을 구성하거나 모든 SIT 인식을 보장하지는 않습니다.

Once local settings pass, sign in at localhost as the test user. The test environment passed **152 offline tests**, a live model reply, and live OneDrive file blocking. A separate diagnostic inspected all 93 bytes of the fixture and blocked it without calling Foundry. These results do not configure a new tenant or prove detection of every sensitive information type.

모델 연결만 검사하려면 다음 명령을 사용합니다. **유료일 수 있는 작은 합성 요청 한 번**을 보내고 파일을 읽지 않습니다. / To check only model connectivity, the following sends **one potentially billable synthetic request** and reads no files:

```powershell
.\.venv\Scripts\python.exe scripts/check_setup.py --check-foundry
```

`check_setup.py`는 필수 설정이 없으면 코드 2로 종료합니다. Foundry 연결 검사가 성공해도 다른 필수값 누락을 무시하지 않습니다. / The setup script exits with code 2 when required settings are missing, even if an optional model connectivity check succeeds.

<a id="live-acceptance-checks"></a>
## 7. 모델을 호출하지 않는 파일 진단 · File diagnostic without model calls

OneDrive 최상위에 승인된 테스트용 UTF-8 파일을 준비하고 `.env`의 `TEST_FILE_PATH`에 이름을 넣습니다. 정상 앱을 Ctrl+C로 멈춘 뒤 다음 중 하나만 실행합니다. / Put an approved UTF-8 fixture in the test user's OneDrive root and set `TEST_FILE_PATH`. Stop the normal app with Ctrl+C, then run one diagnostic mode:

```powershell
.\.venv\Scripts\python.exe scripts/check_onedrive_purview.py --mode pipeline
```

Pipeline 모드는 실제 앱의 검사 순서를 사용하되 모델 호출 경계에서 멈춥니다. 파일 조회를 별도로 먼저 확인하려면 `--mode direct`를 사용합니다. localhost에서 로그인하고 메시지를 보내면 되며, 진단 모드는 채팅 내용을 사용하지 않고 고정된 진단 질문과 설정된 테스트 파일을 사용합니다.

Pipeline mode follows production gate ordering and stops at the model boundary. Use `--mode direct` to verify file retrieval independently before policy evaluation. Sign in at localhost and send a message; diagnostic modes use a fixed clean prompt and configured fixture rather than chat text/history.

`.local/live-probe.jsonl`의 `outcome=file_content_policy_block`, `content_block_confirmed=true`, `foundry_http_calls=0`를 확인합니다. `model_boundary_reached=false`는 차단이 모델 경계 전에 일어났음을 보여 줍니다. 오류·정책 없음·offline 입력 scope는 성공적인 콘텐츠 차단과 다른 결과입니다.

Look for `outcome=file_content_policy_block`, `content_block_confirmed=true`, and `foundry_http_calls=0` in local `.local/live-probe.jsonl`. `model_boundary_reached=false` confirms the block occurred before that boundary. Evaluation errors, missing policies, or offline input scopes are different outcomes.

| 테스트 / Test | 기대 결과 / Expected result |
|---|---|
| 일반 질문 / Clean prompt | Inline 검사 후 모델 응답 / Inline evaluation followed by a reply |
| 정책 대상 SIT 질문 / Matching sensitive prompt | 모델 호출 전 차단 / Block before model use |
| 일반 TXT / Clean file | 전체 검사 후 요약 / Full inspection before summary |
| 정책 대상 SIT TXT / Matching sensitive file | 내용이 모델에 전달되기 전 차단 / Block before content reaches model |
| 파일 끝부분의 SIT / SIT near file end | 처음 부분과 동일하게 검사 / Full coverage includes the end |
| Purview 오류·정책 없음 / Error or absent input protection | 요청 중단 / Stop the turn |
| 미지원 파일·큰 파일 / Unsupported or oversized file | 부분 내용 전달 없음 / No partial-content release |
| Strict output + inline 정책 없음 / Strict output without inline policy | 답변 숨김 / Withhold the reply |

로컬 로그는 판단 메타데이터만 담습니다. Purview portal의 이벤트·경보는 수집 설정과 반영 시간에 따라 별도 확인합니다. API의 차단 action만으로 정확히 어떤 SIT/rule이 일치했는지 단정하지 않습니다.

Local logs contain decision metadata only. Portal events and alerts require separate checks of collection settings and ingestion timing. A block action alone does not identify the exact matched SIT or rule.

## 8. SDK 범위 · SDK and telemetry boundaries

인증은 `microsoft-agents-authentication-msal`의 Blueprint FMI와 MSAL의 자식 OBO를 같은 Python 프로세스에서 처리합니다. `microsoft-agents-a365-runtime`의 `Utility`는 요청 식별에 사용합니다. 대화는 직접 Foundry Responses API를 호출하는 작은 도구 루프이며 Agent Framework나 인증 sidecar가 필요하지 않습니다.

Authentication uses the Agents MSAL library for blueprint FMI and MSAL for child human-user OBO in one Python process. Agent 365 runtime `Utility` identifies outbound requests. Conversation uses a small direct Foundry Responses API tool loop; Agent Framework and an authentication sidecar are unnecessary.

이 예제는 Agent 365 원격 telemetry exporter를 구성하지 않습니다. 로컬 판단 로그와 Purview API 제출이 구현된 기록 경로입니다. 등록만으로 모든 로컬 trace가 관리 센터에 나타나지는 않습니다. Teams/Copilot 배포와 공개 호스팅은 별도 작업입니다.

The sample does not configure an Agent 365 remote telemetry exporter. Its implemented audit paths are local metadata logs and Purview API submissions. Registration alone does not publish all local traces in an admin portal. Teams/Copilot channels and hosted deployment are separate work.
