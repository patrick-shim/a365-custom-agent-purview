# 상위 부서가 준 설정으로 실행하기 · Run with centrally approved settings

**고객 PC에서 .NET이나 Agent 365 CLI를 설치할 필요는 없습니다.** 상위 부서가 준비한 신원·동의·정책을 사용하는 Python 실행 경로입니다. 고객 담당자는 허용된 PC에서 실행하고 직접 로그인합니다. 외부 지원자는 고객 테넌트에 접속하거나 Secret을 받지 않고도, 아래 확인표와 승인된 진단 결과로 지원할 수 있습니다.

이 문서는 고객에게 관리자 권한이나 정책 변경을 요구하는 절차가 아닙니다. **기존 정책으로 가능한지 먼저 확인하고, 부족한 항목만 상위 부서에 확인**합니다. Python 실행에는 `a365.config.json`, `a365.generated.config.json`, CLI 인증 앱 ID가 필요하지 않습니다. 조직에서 요구하는 Agent 365 등록·승인 상태는 상위 부서가 확인합니다.

**English:** Runtime does not require .NET or the Agent 365 CLI. The customer runs Python on an approved machine and signs in; external support can work from approved diagnostic summaries without tenant access or secrets. Existing identities, consent, policy coverage, and organizational registration approval must already be in place. No a365 configuration files are read by the Python runtime.

## 1. 먼저 받을 것은 추가 권한보다 확인 결과입니다 · Readiness first

상위 부서가 아래 항목마다 **준비됨 / 미준비 / 확인 필요**로 답하도록 요청합니다. ID가 발급되어 있다는 사실과 해당 사용자가 이 앱을 실행할 수 있다는 사실은 별개입니다.

| 확인 항목 · Central confirmation | 준비됨일 때 · Ready | 미준비·불명일 때 · Missing/unknown |
|---|---|---|
| Tenant ID, Blueprint Application ID, 연결된 자식 Agent ID, 유효한 Blueprint 자격 증명 | 고객 `.env`에 입력 | 자식의 연결 관계와 자격 증명 종류·만료일 확인 |
| 사용자를 로그인시킬 **기존 Web 클라이언트**와 비밀값, 승인된 localhost callback | 해당 Web 앱을 재사용 | 상위 부서가 승인한 로그인 경로가 필요함 |
| Blueprint의 활성 API 범위·v2 액세스 토큰 설정과 Web → Blueprint 사용자 동의 | 정확한 범위 문자열 사용 | API 범위·토큰 버전·사용자 동의 확인 요청 |
| 자식 Agent의 사용자 위임 Graph 권한 3개 | OBO 파일/정책 호출 가능 여부 진단 | 누락된 동의만 상위 부서에 확인 요청 |
| 해당 자식·사용자·`uploadText`에 적용되는 기존 inline DLP 정책 | 정책을 수정하지 않고 검증 | 정책 대상·활동·실행 모드 확인 요청 |
| 고객 테스트 계정의 OneDrive와 승인된 TXT 자료 | 고객이 직접 로그인·테스트 | 계정·파일 준비 또는 허용된 실행 위치 확인 |
| 승인된 Foundry 목적지와 모델 인증 수단 | 전체 채팅 실행 | Foundry 없는 OneDrive/Purview 진단까지만 가능 |

**미준비 항목을 임의 ID, 다른 앱 Secret, 샘플 토큰, 로컬 정규식으로 대신하지 않습니다.** 필요한 사용자 로그인이나 정책이 없다면 실제 Purview 차단 시연은 진행할 수 없습니다. 확인되지 않은 항목은 성공으로 표시하지 않습니다.

**English:** Treat identity, consent, policy coverage, user access, and model access as separate gates. Missing centrally approved prerequisites cannot be replaced by sample IDs, another application's secret, or a simulated classifier. An unknown configuration is not a successful policy test.

## 2. `tenant / blueprint / agent / secret`만 받았다면 · Identify the supplied values

`secret`이라는 값 하나만 있다면 **어느 Application ID의 Secret인지** 먼저 확인합니다. 이 버전의 브라우저 로그인은 아래 두 자격 증명을 별도로 사용합니다.

| 받을 값 · Value | `.env` 입력 위치 · Destination |
|---|---|
| 고객 Tenant ID | `ENTRA_TENANT_ID` |
| Blueprint **Application/Client ID** | `BLUEPRINT_CLIENT_ID` |
| 해당 Blueprint Client Secret **Value** | `BLUEPRINT_CLIENT_SECRET` |
| 연결된 자식 Agent identity **Object ID** | `AGENT_IDENTITY_ID`와 `PURVIEW_APP_ID`에 같은 값 |
| 기존 일반 Web 로그인 앱의 **Application/Client ID** | `WEB_CLIENT_ID` |
| 해당 Web 앱 Client Secret **Value** | `WEB_CLIENT_SECRET` |
| 실제 활성 Blueprint API 범위 전체 문자열 | `BLUEPRINT_SCOPE=api://<BLUEPRINT_CLIENT_ID>/<실제 범위 이름>` |
| Web 앱에 승인된 callback | `REDIRECT_URI=http://localhost:8000/auth/callback` |
| 고객 테스트 사용자 UPN | `EXPECTED_USER` |
| 그 사용자의 OneDrive 상대 파일 경로 | `TEST_FILE_PATH=test-summary.txt` 등 |

비밀값의 **Value와 만료일**을 확인합니다. Secret ID를 입력하지 않습니다. 고객이 자기 PC의 `.env`에 입력하고 외부 지원자에게 전달하지 않아도 됩니다. ID·URL과 달리 Secret·API Key·토큰은 Git이나 지원 요청에 넣지 않습니다. 자식 Agent 자체에 Secret을 새로 만들 필요는 없습니다.

**Blueprint Secret은 대화형 로그인 앱을 대신하지 못합니다.** 호환되는 Web 앱이 없다면 상위 부서가 승인된 앱을 준비하거나 기존 로그인 호스트와의 연동 방식을 정해야 합니다. 후자는 현재 로컬 브라우저 샘플의 인증 코드 변경이 필요하며, ID만 교체하면 되는 기능이 아닙니다. 인증서/FIC만 제공되는 경우도 현재 두 Client Secret 기반 설정과 다르므로 별도 인증 구현 검토가 필요합니다. [공식 Agent OBO 구조](https://learn.microsoft.com/en-us/entra/agent-id/agent-on-behalf-of-oauth-flow)

**English:** Identify which application owns each secret. This sample needs both a blueprint secret and an ordinary confidential Web-client secret, plus the exact enabled blueprint scope and approved callback. A blueprint cannot initiate the interactive user sign-in flow. Reusing an approved host or certificate/FIC authentication requires an integration change, not only replacement IDs.

## 3. 기존 Purview 정책을 그대로 쓸 수 있나요? · Reuse central policy

**가능합니다. 단, 기존 정책이 이 실행의 자식 Agent·사용자·활동에 실제로 적용되어야 합니다.** 고객 PC에 DLP 정책을 설치하거나 Blueprint 설정 파일 안에 SIT를 넣는 작업은 없습니다. 앱이 사용자·앱·활동을 전달하면 Purview가 적용할 보호 범위와 콘텐츠 판정을 반환합니다. [공식 API 흐름](https://learn.microsoft.com/en-us/purview/developer/use-the-api)

상위 부서가 기존 승인 정책에서 아래를 확인합니다.

1. **신원/동의:** Web → Blueprint의 실제 노출 API 범위 동의, 자식 Agent → Graph의 Delegated `Files.Read`, `Content.Process.User`, `ProtectionScopes.Compute.User`가 테스트 사용자에게 유효한가요? **기존 직접 동의 또는 승인된 Blueprint 권한 상속**으로 충족할 수 있으며, 새 직접 동의를 무조건 만들지 않습니다. 상속 권한은 자식의 포털/API 권한 목록에 보이지 않을 수 있으므로 중앙 담당자가 실제 자식의 유효 권한을 확인합니다. 토큰 원문을 외부 지원자에게 보내지 않습니다. [직접·상속 권한과 유효 권한](https://learn.microsoft.com/en-us/entra/agent-id/concept-inheritable-permissions)
2. **정책 범위:** Application DLP 정책이 **자식 Agent ID와 테스트 사용자**를 포함하나요? Blueprint에 정책이 있다는 설명만으로 자식 적용 여부를 판단하지 않습니다.
3. **검사 활동:** 이 코드는 TXT 전체 내용을 **`uploadText`**로 제출합니다. 그 활동의 SIT 조건과 **`UploadText=Block`** 규칙이 활성화되어 있나요?
4. **실행 모드:** 실제 보호 범위 계산에서 해당 앱·사용자·활동에 **`evaluateInline`**이 반환되나요? offline 감사만으로 입력을 실시간 차단할 수는 없습니다.
5. **서비스 준비:** 해당 통합의 라이선스·청구·수집 설정과 고객이 확인할 감사 경로가 준비되었나요?

상위 부서가 이미 정한 SIT와 임계값을 사용합니다. 고객 담당자가 새 SIT를 만들거나 기존 정책을 바꿀 필요는 없습니다. **이 앱의 `.env`에는 정책 ID나 SIT 선택 항목이 없으며, 요청마다 임의의 정책/SIT를 지정할 수 없습니다.** 정책 이름·ID·규칙·SIT는 중앙 담당자와 확인할 근거로만 받습니다. SharePoint/OneDrive 저장소 정책이나 `uploadFile` 전용 규칙만 있다는 사실은 이 앱의 `uploadText` 보호 범위를 증명하지 않습니다.

권한은 있지만 정책 범위가 없거나 inline 평가가 없으면 앱은 입력을 모델로 보내지 않고 중단합니다. 이것은 **보호 조건 미충족**이며, 파일의 SIT를 찾아 차단했다는 뜻이 아닙니다. 기존 정책으로 충족할 수 없다면 상위 부서가 허용하는 범위 추가·대체 실행 환경을 검토해야 합니다. 고객 PC에서 정책을 우회해서 해결할 수는 없습니다.

현재 Microsoft 안내는 Entra 등록 앱의 DLP 규칙 생성에 관리자 PowerShell을 요구합니다. 이는 **정책을 관리하는 상위 부서의 관리 환경**에서 수행할 작업입니다. 고객 PC에 .NET/관리 모듈을 설치하도록 요구하지 않습니다. 정책 생성 자체가 조직에서 허용되지 않는다면 포털만으로 같은 설정을 만들 수 있다고 약속하지 않습니다. [정책 구성 요구 사항](https://learn.microsoft.com/en-us/purview/developer/use-the-api#prerequisites)

**English:** Verify effective child permissions through existing direct grants or approved blueprint inheritance; do not require duplicate grants. Reuse the central policy only when its scope covers the child, signed-in user, and `uploadText` with inline evaluation. No policy ID or SIT selector is supplied by this app. Storage-only coverage is insufficient evidence. Missing coverage stops the app; it does not prove sensitive-data detection. Authorized policy changes belong to central IT.

## 4. 고객 PC에서 Python만 준비하기 · Local preparation

아래는 Windows의 **명령 프롬프트(Command Prompt, `cmd`)**에서 실행하는 로컬 명령입니다. Windows Terminal을 사용하면 Command Prompt 프로필을 선택합니다. PowerShell 7, 추가 .NET 런타임/SDK, Agent 365 CLI, 관리자 모듈을 설치하지 않습니다. Python 3.14와 Git, 패키지 설치는 고객의 허용된 배포 방식과 저장소를 사용합니다. Git도 제한된다면 상위 부서가 승인한 Git 미러/코드 배포 경로를 사용합니다.

```bat
git clone https://github.com/patrick-shim/a365-custom-agent-purview.git
cd a365-custom-agent-purview
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if not exist .env copy .env.example .env
notepad .env
```

조직이 사내 패키지 인덱스/프록시를 요구하면 승인된 pip 설정을 먼저 적용합니다. 인터넷 저장소를 임의로 추가하거나 TLS 검증을 끄지 않습니다. 기존 `.venv`가 있으면 생성 명령을 반복할 필요가 없습니다. 고객은 위 2절의 값을 `.env`에 입력합니다. `a365.config*.json`은 만들지 않아도 됩니다.

**English:** Run these local commands in Windows Command Prompt (`cmd`) using approved Python/Git/package distribution. Only `.env` is needed at runtime; no a365 configuration is required. No additional .NET runtime, PowerShell 7, or administrator module is installed. Use the customer's approved package index rather than bypassing network controls.

## 5. 모델 인증은 별도로 선택합니다 · Model authentication

OneDrive/Purview는 **고객 사용자의 브라우저 로그인 + 자식 OBO**를 사용합니다. Foundry는 그 사용자 토큰을 재사용하지 않습니다. 다음 중 고객이 승인한 방법 하나를 사용합니다.

| 고객이 허용한 방법 · Approved method | 설정과 조건 · Configuration |
|---|---|
| Azure CLI는 허용됨 | 기본 `FOUNDRY_AUTH_MODE=azure_cli`. 기존 Azure CLI의 모델 호출 계정에 해당 리소스 inference 권한이 필요합니다. Azure CLI는 a365 CLI와 별개입니다. |
| 모든 CLI가 제한되지만 모델 API Key 사용은 허용됨 | `FOUNDRY_AUTH_MODE=api_key`와 `FOUNDRY_API_KEY` 설정. 상위 부서가 제공한 유효한 모델 키를 `.env`에만 보관합니다. Azure CLI가 필요 없습니다. |
| Azure CLI와 API Key 모두 허용되지 않음 | 현재 모델 인증 구현으로 전체 채팅을 실행할 수 없습니다. 상위 부서가 승인한 모델 호출 경로와 별도 코드 연동이 필요합니다. |

두 방식 모두 `FOUNDRY_ENDPOINT`에는 모델 리소스 **루트 URL**, `FOUNDRY_DEPLOYMENT`에는 **배포 이름**, `FOUNDRY_TENANT_ID`에는 모델 테넌트 ID를 넣습니다. 기존 정책에서 키 인증을 꺼 두었다면 이 실습을 위해 임의로 켜지 않습니다. 상세 값과 Azure CLI 로그인은 [환경값 안내](environment-values.md)를 참고합니다.

**English:** Model authentication is independent of OneDrive OBO. Approved API-key mode removes the Azure CLI dependency. If neither supported model method is allowed, use only the model-free diagnostic until an approved integration is implemented. Do not enable key authentication to bypass an organizational restriction.

## 6. 먼저 모델 없이 OneDrive/Purview만 확인하기 · Model-free diagnostic

일반 앱이 실행 중이라면 해당 창에서 `Ctrl+C`로 먼저 중지합니다. 고객이 승인한 합성 테스트 파일을 자기 OneDrive에 놓고 `.env`의 `TEST_FILE_PATH`에 상대 경로를 입력합니다. 현재는 UTF-8 TXT만 지원합니다. 이 진단도 **파일을 로컬 Python으로 다운로드하고 전체 텍스트를 Purview에 제출**하므로 고객이 승인한 자료·PC를 사용합니다.

```bat
.\.venv\Scripts\python.exe scripts/check_setup.py
.\.venv\Scripts\python.exe scripts/check_onedrive_purview.py --mode pipeline
```

첫 검사는 필수 설정의 존재를 확인하며, 권한·정책의 유효성을 증명하지 않습니다. Foundry 설정만 없다면 전체 앱용 검사에는 `SETUP NEEDED`가 나올 수 있습니다. 두 번째 **모델 없는 진단**은 Foundry 설정·로그인 없이 사용할 수 있지만, Web/Blueprint/자식 신원 설정과 사용자 동의는 반드시 준비되어야 합니다. 모델 값을 임의로 채워 첫 검사를 통과시키지 않습니다.

고객이 같은 PC에서 `http://localhost:8000`을 열어 로그인한 뒤 짧은 메시지를 보냅니다. 진단은 메시지 내용을 사용하지 않고 고정된 진단 질문과 `TEST_FILE_PATH`를 검사합니다. 파일 입력란은 비우거나 같은 상대 경로를 넣습니다. 이 진단은 정상/차단 어느 경우에도 Foundry를 호출하지 않습니다. 브라우저 로그인 자체가 실패하면 아래 진단 JSON이 생기기 전일 수 있으므로, 전체 로그인 URL 대신 화면에 표시된 오류 코드와 발생 시각을 공유합니다.

| 결과 · Result | 뜻과 다음 조치 · Interpretation |
|---|---|
| `authentication_failed` | Web 로그인/OBO 신원·동의·Conditional Access를 중앙 담당자와 확인 |
| `document_read_failed` | OneDrive 사용자·파일 경로·접근 조건 확인 |
| `policy_evaluation_unavailable` + `missing_policy_scope` 또는 `inline_policy_required` | 정책 범위/inline 조건 미충족. 중앙 담당자에게 해당 코드 전달 |
| `pipeline_permitted_stopped_before_model` | 이 테스트 입력은 파이프라인에서 허용되어 모델 직전에 진단이 중지됨. SIT 탐지 성공을 의미하지 않음 |
| `file_scope_policy_block` | 범위 수준 제한. 파일 내용을 검사해 SIT를 찾았다는 증거와 구분 |
| `file_content_policy_block` | 파일 내용에 대한 실제 차단. 아래 확인값과 중앙 Purview 이벤트를 함께 확인 |

차단용 파일은 `onedrive_read_succeeded=true`, 전체 파일/검사 바이트 수, `content_block_confirmed=true`, `model_boundary_reached=false`, `foundry_http_calls=0`을 함께 확인합니다. **진단은 항상 모델 호출 0회이므로 그 값 하나만으로 차단 성공을 판단하지 않습니다.** 실제 일치 SIT/규칙은 상위 부서가 correlation ID에 해당하는 Purview 이벤트에서 확인합니다. 권한 거부나 정책 없음은 SIT 차단 성공이 아닙니다. 일반 앱도 정책 차단에 HTTP 403을 사용하므로 상태 코드만으로 판단하지 않습니다.

일반 TXT와 중앙 담당자가 SIT 일치를 확인한 합성 TXT를 각각 검사합니다. `TEST_FILE_PATH`를 바꾸었다면 진단을 중지하고 다시 실행합니다. 파일 차단을 확인하고 Foundry도 승인·준비되었다면 진단을 중지한 뒤 다음으로 일반 앱을 실행합니다.

```bat
.\.venv\Scripts\python.exe app.py
```

**English:** Run the pipeline diagnostic first; it never calls Foundry. Distinguish configuration/authentication errors, scope-level blocks, permitted input, and an actual file-content verdict. Verify full-file coverage and the model-boundary flag. Customer-side Purview events establish the matched rule/SIT. Default response evaluation may be audit-only; inline output blocking is a separate requirement.

## 7. 외부 지원자에게 전달할 결과 · Support without tenant access

고객이 진단을 실행하고 상위 부서의 허용 범위에서 **실행 시각, 코드 버전, `mode`, `stage`, `outcome`, `error_code`, correlation ID, 검사 바이트 수, 차단/모델 경계 확인값**만 발췌해 전달합니다. 빈 필드는 그대로 두면 됩니다. 이 정도로 어느 단계에서 멈췄는지 먼저 구분할 수 있습니다.

`.local/live-probe.jsonl`과 화면의 전체 JSON에는 사용자·테넌트·앱 식별자와 정책 범위 메타데이터도 들어갈 수 있으므로, 전체 파일을 자동으로 외부에 보내지 않습니다. 로그는 콘텐츠 원문·토큰을 기록하지 않도록 작성되어 있지만 회사의 공유 기준을 따릅니다. `.env`, Secret, API Key, 토큰, 고객 문서 원문, 로그인 URL 전체는 지원 자료에 포함하지 않습니다. Patrick/외부 지원자에게 고객 테넌트 접속권한을 줄 필요는 없습니다.

**English:** Share an approved excerpt of timestamps, version, stage/outcome/error codes, correlation ID, byte counts, and verification flags. Diagnostic JSON also contains identifiers and scope metadata; review it before external sharing. Do not send configuration files, credentials, raw documents, or complete sign-in URLs.

## 상위 부서에 보낼 확인 요청 · Central IT request

> 기존에 발급받은 Tenant/Blueprint/Agent ID를 사용하여 승인된 고객 PC에서 Python 에이전트를 실행하려고 합니다. 이 PC에는 .NET/a365 CLI를 설치할 수 없으며, 신규 관리자 권한이나 임의 정책 변경을 요청하는 것은 아닙니다.
>
> 1. 제공된 Secret이 어느 Application ID의 값인지, 유효 기간과 자식-Blueprint 연결 관계를 확인해 주세요. 조직상 필요한 Agent 365 등록·승인도 완료되었는지 부탁드립니다.
> 2. 사용할 기존 Web 로그인 앱, localhost callback, Blueprint API 범위, 테스트 사용자의 Web→Blueprint 동의가 준비되어 있는지 확인해 주세요. 승인된 다른 로그인 호스트만 가능하면 그 연동 조건을 알려 주세요.
> 3. 자식 Agent의 테스트 사용자 OBO에 `Files.Read`, `Content.Process.User`, `ProtectionScopes.Compute.User`가 유효한지 확인해 주세요.
> 4. **기존 승인된** Application DLP 정책이 이 자식·사용자·`uploadText`를 포함하고 inline SIT 차단을 제공하는지 확인해 주세요. 사용할 SIT/기준, 합성 테스트 자료, 정책·규칙 확인 담당자를 알려 주세요. 미충족 항목이 있다면 허용된 처리 방법만 안내해 주세요.
> 5. 모델은 승인된 Foundry endpoint·배포를 사용하겠습니다. 허용되는 모델 인증 방식과 실행 PC/네트워크 조건을 알려 주세요. 모델 인증이 준비되지 않으면 먼저 Foundry를 호출하지 않는 OneDrive/Purview 진단까지만 하겠습니다.
>
> 비밀값은 고객 내부 보안 경로로만 전달하고 고객 PC에 입력하겠습니다. 외부 지원자에게는 승인된 진단 요약만 공유하겠습니다.

**English:** Ask central IT to confirm existing approved identities, the interactive sign-in client and consent, effective child permissions, applicable inline UploadText policy, and the allowed model/runtime environment. Request only the approved resolution for missing prerequisites, not broad administrative access.
