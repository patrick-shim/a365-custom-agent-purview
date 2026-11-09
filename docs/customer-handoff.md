# 고객에게 받을 값과 권한 · Customer handoff checklist

**상위 부서에서 ID를 제공하고 고객이 .NET/CLI·앱 등록·정책 변경을 할 수 없다면:** [제한 환경 실행 안내](restricted-environment.md)를 먼저 사용합니다. 아래의 관리자 준비 항목은 **상위 부서에 기존 설정을 확인할 항목**입니다. 고객 담당자에게 추가 관리자 권한을 요구하거나 새 설정을 직접 수행하라는 뜻이 아닙니다. 외부 지원자가 테넌트에 접근할 수 없다면 고객이 자신의 승인된 PC에서 설정·로그인·검사를 수행하고, 허용된 진단 결과만 공유합니다. Secret은 외부 지원자에게 전달하지 않고 고객 PC에 보관해도 됩니다.

**English:** When upstream IT provides identities and restricts administration, follow the [restricted runbook](restricted-environment.md). Ask upstream IT to confirm existing approved configuration first. Customers run and authenticate locally; external support can work from approved diagnostic results without tenant access or customer secrets.

**고객 환경을 이 PC에서 테스트하려면, 고객의 설정값과 앱 자격 증명뿐 아니라 고객 테넌트 사용자의 실제 로그인도 필요합니다.** OBO는 로그인한 사용자를 대신하는 방식입니다. Tenant ID·사용자 이름·Agent ID를 입력하는 것만으로 고객의 OneDrive를 읽을 수는 없습니다.

가장 간단한 준비 방법은 **고객 관리자가 앱·권한·Purview 정책을 준비하고, OneDrive가 있는 고객 테스트 사용자가 로그인하는 것**입니다. 이 프로젝트의 Microsoft 365 쪽 구성은 같은 고객 테넌트의 웹 앱, Blueprint, 자식 Agent ID, 테스트 사용자, OneDrive, Purview를 전제로 합니다. Foundry는 별도로 접근 권한이 확보된 다른 테넌트여도 됩니다.

**English:** Customer IDs and credentials are not sufficient to impersonate a user. A customer user must sign in for OBO. Have the customer administrator prepare the same-tenant Microsoft 365 identities, consent, OneDrive, and Purview policy. Foundry access is configured separately and may use another tenant.

## 1. 먼저 정할 사람 · Agree who signs in

| 담당 · Person | 필요한 준비 · Preparation |
|---|---|
| 고객 Entra/Agent 365 담당자 | 웹 앱·Blueprint·자식 ID와 사용자별 동의를 준비합니다. / Prepares identities and consent. |
| 고객 Purview 담당자 | 테스트 사용자를 포함하는 앱 DLP 정책과 수집·감사 설정을 확인합니다. / Configures the application DLP policy and collection/audit settings. |
| OneDrive 테스트 사용자 | 고객 테넌트의 OneDrive를 사용할 수 있는 계정으로 브라우저에서 직접 로그인합니다. / Signs in interactively with a licensed customer OneDrive account. |
| 로컬 실행자 | Python 앱을 실행합니다. 기본 모델 인증 방식에서는 Azure CLI로 모델 호출 권한이 있는 계정에 로그인합니다. / Runs Python and signs in to Azure CLI for model access. |

OneDrive 로그인 사용자와 Foundry용 Azure CLI 사용자는 달라도 됩니다. **로컬 실행자에게 Global Administrator를 요청할 필요는 없습니다.** 관리자 작업을 고객이 완료했다면 로컬 실행에는 해당 앱의 동의·파일 접근·모델 호출 권한만 필요합니다.

처음 테스트에는 고객이 제공하는 전용 테스트 사용자를 권장합니다. 게스트 초대만으로 고객의 특정 직원 OneDrive가 이 앱의 `/me/drive`가 되지는 않습니다. 현재 앱은 **로그인한 사용자 자신의 OneDrive**를 읽습니다. 사용자의 암호·PIN·MFA 코드를 전달받지 말고, 사용자가 직접 인증하도록 진행합니다. 고객 정책상 외부 PC에서 로그인이 허용되지 않으면 고객이 허용한 PC/VM에서 같은 프로젝트를 실행합니다. [Graph의 현재 사용자 드라이브](https://learn.microsoft.com/en-us/graph/api/drive-get?view=graph-rest-1.0)

**English:** The OneDrive user and model caller can differ. Runtime does not require Global Administrator. An external guest invitation alone does not make another employee's drive available through `/me/drive`. The user authenticates directly; passwords and MFA codes are not handoff values. Use a customer-approved machine if Conditional Access requires one.

## 2. 받아서 `.env`에 넣을 공개 설정값 · Non-secret runtime settings

아래 표를 고객에게 보내 빈칸을 채워 달라고 요청합니다. 값을 찾는 화면과 복사 방법은 [환경값별 안내](environment-values.md)에 있습니다. **ID·URL·배포 이름은 비밀값이 아닙니다.** 회사의 정보 공유 기준에 맞춰 전달하면 됩니다.

| 고객에게 요청할 값 · Request | 넣을 설정 · Destination | 정확히 무엇인가요? · Meaning |
|---|---|---|
| 고객 Tenant ID | `ENTRA_TENANT_ID` | 고객 Microsoft 365 디렉터리의 GUID입니다. 도메인 이름이 아닙니다. |
| 테스트 사용자 UPN | `EXPECTED_USER` | 예: `tester@customer.example`. 이 프로젝트의 로그인 허용 계정으로 설정합니다. |
| Blueprint Application ID | `BLUEPRINT_CLIENT_ID` | 사용할 Blueprint의 **Application/Client ID**입니다. |
| Blueprint의 활성 API 범위 전체 문자열 | `BLUEPRINT_SCOPE` | 예: `api://<BLUEPRINT_CLIENT_ID>/access_agent_as_user`. ID와 마지막 범위 이름을 실제 값으로 바꿉니다. 범위의 GUID가 아닙니다. |
| 해당 Blueprint에 연결된 자식 Agent ID | `AGENT_IDENTITY_ID` | 선택한 **자식 Agent identity의 Object ID**입니다. Blueprint ID와 구분합니다. |
| Purview에서 대상으로 선택한 앱 ID | `PURVIEW_APP_ID` | 이 OBO 구현에서는 위 **자식 Agent ID와 동일**하게 설정합니다. 비워도 코드가 자식 ID를 사용합니다. |
| 일반 웹 로그인 앱의 Application ID | `WEB_CLIENT_ID` | 같은 고객 테넌트의 confidential **Web** 로그인 앱입니다. 호환되는 기존 MSAL 앱을 재사용할 수 있습니다. |
| 웹 앱에 등록된 callback | `REDIRECT_URI` | 기본값은 정확히 `http://localhost:8000/auth/callback`입니다. 앱 등록의 **Web** 플랫폼에 등록합니다. |
| 모델 리소스의 루트 endpoint | `FOUNDRY_ENDPOINT` | 예: `https://example-resource.services.ai.azure.com`. `/api/projects/...`, `/openai/v1/`, `/responses`는 붙이지 않습니다. |
| 호출할 모델의 배포 이름 | `FOUNDRY_DEPLOYMENT` | 모델 종류 이름이 아니라 **deployment name**입니다. |
| 모델 리소스의 Tenant ID | `FOUNDRY_TENANT_ID` | 모델이 배포된 디렉터리의 GUID입니다. Microsoft 365 테넌트와 다를 수 있습니다. |
| 테스트 파일의 OneDrive 상대 경로 | `TEST_FILE_PATH` | 루트에 있다면 `test-summary.txt`. PC의 `C:\...` 경로나 공유 링크를 넣는 칸이 아닙니다. |

`APP_NAME`은 표시용 이름입니다. 고객이 사용할 이름으로 정하면 됩니다. 모델 배포는 이 앱이 사용하는 **Azure OpenAI 호환 Responses API와 도구 호출**을 지원해야 합니다. 파일 검사 기본 제한은 128 KiB이며, 이 버전은 **전체 내용을 읽을 수 있는 UTF-8 `.txt`**만 지원합니다. PDF·Word 파일은 현재 지원 대상이 아닙니다.

**English:** Collect the tenant, test-user UPN, blueprint client ID and exact enabled API scope, child identity ID, ordinary Web client ID, callback, Foundry resource root/deployment/tenant, and relative TXT path. Purview's application location must match the child identity. The model deployment name is not necessarily its model name.

## 3. 별도 보안 경로로 받을 비밀값 · Credentials

| 비밀값 · Secret | 넣을 설정 · Destination | 요청할 때 확인할 점 · Check |
|---|---|---|
| 웹 로그인 앱 Client Secret **Value** | `WEB_CLIENT_SECRET` | 해당 `WEB_CLIENT_ID`에 연결된 유효한 값과 만료일. Secret ID가 아닙니다. |
| Blueprint Client Secret **Value** | `BLUEPRINT_CLIENT_SECRET` | 해당 `BLUEPRINT_CLIENT_ID`의 값과 만료일. 기존 공유 자격 증명은 삭제하지 않습니다. |
| Foundry API Key — 키 방식을 선택할 때만 | `FOUNDRY_API_KEY` | 기본 `azure_cli` 방식에서는 받지 않아도 됩니다. 키 방식은 `FOUNDRY_AUTH_MODE=api_key`로 설정합니다. |

고객이 승인한 비밀관리 도구나 보안 전달 경로로 전달받아 **로컬 `.env`에만** 넣습니다. `.env` 전체, 비밀값, access/refresh token을 Git·이슈·README에 올리지 않습니다. 고객이 이 PC의 `.env`에 직접 입력해도 됩니다. **자식 Agent ID 자체의 Client Secret은 요청하지 않습니다.** 이 흐름은 Blueprint 자격 증명으로 자식을 인증합니다.

**English:** Obtain two secret **Values** with expiry dates: the Web client secret and blueprint secret. A Foundry API key is optional. Use an approved secret channel or let the customer enter them locally. No child-agent secret, user password, or exported access/refresh token is needed. Keep all secrets out of Git.

## 4. 고객 관리자가 준비할 권한 · Required consent and access

API permissions 화면에 항목을 추가한 것만으로 끝내지 말고 **실제 동의가 생성되었는지** 확인해 달라고 요청합니다. 한 명만 테스트한다면 두 위임 동의를 `consentType=Principal`, `principalId=<테스트 사용자 Object ID>`로 제한할 수 있습니다. [동의 구성 절차](environment-values.md), [공식 OBO 흐름](https://learn.microsoft.com/en-us/entra/agent-id/agent-on-behalf-of-oauth-flow)

| 누구에게 · Client | 대상 · Resource | 필요한 권한 · Permission | 목적 · Purpose |
|---|---|---|---|
| 일반 웹 로그인 앱 | Blueprint API | 실제 노출한 위임 범위, 예: `access_agent_as_user` | 사용자의 Blueprint 대상 토큰을 받습니다. |
| **자식 Agent ID** | Microsoft Graph | **Delegated `Files.Read`** | 로그인한 사용자의 OneDrive 파일을 읽습니다. |
| **자식 Agent ID** | Microsoft Graph | **Delegated `Content.Process.User`** | 사용자 컨텍스트로 `processContent` 검사를 요청합니다. |
| **자식 Agent ID** | Microsoft Graph | **Delegated `ProtectionScopes.Compute.User`** | 적용할 Purview 보호 범위를 계산합니다. |
| Azure CLI로 로그인할 모델 호출 계정 | Foundry/Azure OpenAI 리소스 | 해당 모델의 inference 데이터 접근 권한 | 기본 `azure_cli` 방식으로 모델을 호출합니다. |

Azure OpenAI 모델을 이 예제의 v1 API로 호출할 때는 모델 리소스 범위의 **Cognitive Services OpenAI User**가 대표적인 최소 역할입니다. 고객의 배포 종류에 맞는 inference 권한을 확인합니다. Azure 구독 `Reader`만으로 모델 호출 권한이 생기는 것은 아닙니다. 기본 방식에서는 `FOUNDRY_AUTH_MODE=azure_cli`로 두고, 로컬 실행자가 `az login --tenant "<FOUNDRY_TENANT_ID>"`로 로그인합니다. [키 없는 Azure OpenAI 인증과 역할](https://learn.microsoft.com/en-us/azure/developer/ai/keyless-connections)

**OneDrive `Files.Read`를 사용하는 주체는 웹 앱이 아니라 자식 Agent ID입니다.** MSAL은 로그인 코드를 제공하는 라이브러리이며 앱 등록이나 동의를 대신하지 않습니다. 이 저장소의 관리 예제는 자식에 직접 권한을 부여합니다. 그러나 고객 상위 부서가 Blueprint 동의와 상속으로 필요한 권한을 이미 제공했다면 기존 방식을 먼저 확인하며, 직접 동의를 추가할 필요가 있다고 단정하지 않습니다. 상속 권한은 자식 권한 목록에 표시되지 않을 수 있습니다. [유효 권한: 직접 부여와 상속](https://learn.microsoft.com/en-us/entra/agent-id/concept-inheritable-permissions)

**English:** The child uses the Graph scopes. Existing centrally approved inheritance can supply those effective scopes; do not require new direct grants merely because the repository's provisioning example uses them. Inherited permissions may not appear in the child's permission listing.

고객이 직접 동의를 설정하면 아래 관리용 ID를 로컬 실행자에게 모두 전달할 필요는 없습니다. 우리가 설정을 도와야 한다면 고객 담당자와 다음 ID도 확인합니다.

| 관리 작업에 쓰는 값 · Administration-only value | 용도 · Purpose |
|---|---|
| 테스트 사용자 **Object ID** | `principalId`에 사용합니다. UPN과 구분합니다. |
| 웹 앱의 **서비스 주체 Object ID** | Web → Blueprint 동의의 `clientId`입니다. Web Application ID와 다릅니다. |
| Blueprint의 **서비스 주체 Object ID** | Web → Blueprint 동의의 `resourceId`입니다. |
| Blueprint의 **애플리케이션 Object ID** | Blueprint API 설정 변경 및 CLI 생성 상태에 사용합니다. 서비스 주체 ID와 구분합니다. |
| Blueprint 노출 범위의 **scope ID** | 웹 앱의 요청 API 권한 목록에 사용합니다. `.env`에는 범위 문자열을 넣습니다. |
| 고객 테넌트의 Microsoft Graph **서비스 주체 Object ID** | Child → Graph 동의의 `resourceId`입니다. 공통 Graph Application ID와 다릅니다. |

**English:** The Web client needs delegated consent to the blueprint API; the child needs the three delegated Graph scopes listed above for the test user. The Azure CLI account separately needs model inference access. Request provisioning identifiers only if you are helping administer consent; they are not extra runtime `.env` fields. Customer administrators can complete provisioning without giving the runtime operator broad administrative roles.

## 5. 고객 Purview 담당자에게 요청할 설정 · Purview policy

다음 항목을 확인해 달라고 요청합니다. 실제 명령과 화면은 [Purview 설정 안내](purview-setup.md)에 있습니다.

1. 해당 테넌트가 Purview 앱 통합에 필요한 라이선스·사용량 청구·수집 설정을 갖추었는지 확인합니다.
2. **Application** 대상 DLP 정책에 **자식 Agent ID**와 **테스트 사용자**가 포함되어야 합니다. Blueprint 이름을 전달하는 것만으로 정책이 연결되지 않습니다.
3. 정책은 활성화(`Mode=Enable`), 규칙은 사용 상태(`Disabled=false`)여야 합니다.
4. 신용카드 테스트라면 기본 **Credit Card Number** SIT를 사용하고, 예제와 맞추려면 신뢰도 **85 이상**, 개수 **1개 이상**으로 설정합니다. 다른 요구가 있다면 고객의 승인된 SIT와 기준을 사용합니다.
5. 액션은 **`UploadText=Block`**입니다. 이 앱은 OneDrive 파일을 다운로드한 뒤 **전체 텍스트를 `uploadText`로 검사**합니다. `uploadFile` 전용 규칙이나 SharePoint 저장소 정책만으로 이 앱의 검사 경로가 준비되었다고 판단하지 않습니다.
6. 해당 사용자·앱·활동에 대해 실제 Graph 보호 범위가 **inline 평가**를 제공하는지 확인합니다. offline 감사만으로 입력을 실시간 차단할 수 없습니다.
7. 정책 이름/ID, 규칙 이름/ID, SIT 이름, 대상 앱·사용자, 적용 완료 시간을 공유합니다. 이 값은 확인용이며 `.env`에 정책 ID를 넣는 칸은 없습니다.
8. 포털 로그 확인도 필요하면 Audit/AI 상호작용 수집 설정을 확인합니다. 차단 응답과 포털 이벤트·알림의 표시 시점은 별도로 검증합니다.

**English:** Request an enabled Application DLP policy targeting the **child identity and test user**, an enabled SIT rule with `UploadText=Block`, and applicable inline protection. Share policy/rule identifiers for verification; they are not runtime environment fields. Collection and audit visibility require their own configuration. [공식 통합 안내 / Integration guidance](https://learn.microsoft.com/en-us/purview/developer/use-the-api)

`REQUIRE_INLINE_OUTPUT=false`인 기본 설정은 응답을 감사용으로 평가할 수 있지만 **응답 내용의 실시간 차단을 보장하지 않습니다**. 응답 차단도 요구한다면 응답 활동에 대한 inline 정책을 준비하고 `REQUIRE_INLINE_OUTPUT=true`로 별도 검증합니다. 이번 기본 검증 범위는 질문과 파일 입력 차단입니다.

**English:** Default output evaluation can be audit-only. Enforcing sensitive-output blocking requires an applicable inline output policy and `REQUIRE_INLINE_OUTPUT=true`, followed by separate testing.

## 6. Agent 365 CLI 등록을 맡는 경우에만 · Optional onboarding handoff

고객이 이미 자식 Agent ID를 생성하고 Agent 365 등록까지 완료했다면 **Python 실행을 위해 다시 등록할 필요가 없습니다**. 새 자식 생성이나 등록을 우리가 맡는 경우에만 다음을 추가 요청합니다. [CLI 절차](onboarding.md)

| 추가 요청 · Additional request | 넣을 곳/용도 · Destination/purpose |
|---|---|
| 정확한 Blueprint·자식 표시 이름 | `a365.config.json`의 `agentBlueprintDisplayName`, `agentIdentityDisplayName` |
| 고객 테넌트의 허용된 CLI 인증 앱 Application ID | `a365.config.json`의 `clientAppId`. 웹 로그인 앱 ID와 구분합니다. |
| Blueprint Application ID·Application Object ID·Service-principal Object ID, 자식 ID | `a365.generated.config.json`의 해당 필드. 예제 구조는 README에 있습니다. |
| 기존 Agent 365 등록 ID와 등록 여부 | 이미 등록된 **그 자식**의 상태 확인. 다른 자식의 등록 ID를 재사용하지 않습니다. |
| 새 자식의 사람 sponsor Object ID — 새로 만들 때만 | 자식 생성에 사용합니다. |
| 고객의 등록 작업 담당자와 승인된 프로비저닝 권한 | CLI/관리 도구가 로그인할 사람입니다. 런타임 Graph 권한 세 개와 별개입니다. |

CLI 인증 앱의 필요한 관리 범위와 등록 명령은 [환경값별 CLI 설정](environment-values.md)과 [온보딩 안내](onboarding.md)를 따릅니다. 기존 자식을 쓸 때 `setup all` 전체 설정을 무조건 실행하지 않습니다. 문서의 등록 전용 경로를 사용합니다.

**English:** CLI credentials and provisioning authority are needed only if you perform creation/registration. Existing registered identities can be used directly by Python. The CLI authentication client is distinct from the interactive Web client, and provisioning privileges are separate from runtime Graph scopes.

## 7. 고객과 같이 확인할 테스트 · Acceptance test

1. 고객이 허용한 테스트 사용자의 OneDrive에 **일반 UTF-8 TXT**와 **SIT 일치를 미리 확인한 합성 테스트 TXT**를 준비합니다. 실제 고객 신용카드 정보를 테스트 자료로 받지 않습니다. 임의의 테스트 숫자는 기본 SIT에서 제외될 수 있으므로 먼저 SIT 테스트를 확인합니다.
2. 이 PC에서 Entra 로그인, Microsoft Graph/OneDrive 다운로드, Purview, Foundry endpoint에 접근 가능한지 확인합니다. 고객 Conditional Access, 네트워크/프록시, Foundry 방화벽·private endpoint 조건에 맞는 실행 위치를 사용합니다.
3. 테스트 사용자가 로그인한 뒤, 일반 파일이 읽히고 정책상 허용되는지 확인합니다.
4. 민감 테스트 파일은 진단에서 `file_content_policy_block`, `content_block_confirmed=true`, `model_boundary_reached=false`, `foundry_http_calls=0`을 확인합니다. 진단은 원래 모델을 호출하지 않으므로 0회라는 값만으로 성공을 판단하지 않습니다. 로그인 실패·Graph/Purview의 권한 거부·정책 없음 때문에 중단된 것은 **SIT 탐지 성공으로 세지 않습니다**. 일반 앱의 확인된 정책 차단도 HTTP 403을 반환하므로 상태 코드만으로 성공 여부를 판단하지 않습니다.
5. 일반 앱에서 정상 질문의 모델 응답과 민감 파일의 차단을 각각 확인합니다. 정확한 SIT·규칙 일치는 Purview 이벤트와 함께 확인합니다.

파일은 검사 전에 **이 PC의 Python 프로세스로 다운로드**되고, 전체 텍스트가 고객 Purview에 제출됩니다. **허용된 내용만** 구성한 Foundry로 전달됩니다. 따라서 고객이 승인한 테스트 자료와 실행 장소·모델 목적지를 사용합니다. 기존 개인/개발용 Foundry 연결을 재사용하는 경우에도 그 목적지에서 고객 테스트 데이터를 처리해도 되는지 고객과 맞춥니다. 로컬 정책 로그는 원문 대신 결정 메타데이터를 기록하지만, Purview 수집 정책은 제출 내용을 보존할 수 있습니다.

**English:** Use an approved clean TXT and a synthetic fixture confirmed by the SIT tester. Verify network/Conditional Access, successful retrieval, actual content blocking, and zero model calls in the diagnostic. Fail-closed errors are not evidence of SIT detection. The local process receives the file, Purview receives its full text, and only permitted content reaches the configured Foundry model.

## 고객에게 바로 보낼 요청문 · Copyable request

아래 문구는 설정 담당자에게 보내는 일반 요청문입니다. 권한이 제한된 고객은 [상위 부서용 기존 설정 확인 요청문](restricted-environment.md)을 사용하세요. / Restricted customers should use the upstream-IT confirmation request in the linked runbook.

> 고객 테넌트에서 OneDrive 문서의 Purview 차단을 로컬 Python 에이전트로 테스트하려고 합니다.
>
> **공개 설정값:** Tenant ID, 테스트 사용자 UPN·Object ID, Blueprint Application ID와 활성 API scope 전체 문자열, 연결된 자식 Agent ID, 웹 로그인 앱 Application ID, Foundry 루트 endpoint·deployment name·Tenant ID, 테스트 TXT 상대 경로를 부탁드립니다.
>
> **별도 보안 전달:** 웹 앱 Client Secret Value와 Blueprint Client Secret Value 및 만료일을 부탁드립니다. 기본 Azure CLI 모델 인증을 사용하면 Foundry API Key는 필요 없습니다. 사용자 암호·MFA 코드·액세스 토큰은 전달하지 않으셔도 됩니다.
>
> **고객 측 설정:** 웹 앱의 Web callback을 `http://localhost:8000/auth/callback`으로 등록하고, 테스트 사용자에 대해 Web → Blueprint API 범위 동의와 자식 Agent → Graph의 Delegated `Files.Read`, `Content.Process.User`, `ProtectionScopes.Compute.User` 동의를 준비해 주세요. 모델 호출 계정에는 해당 Foundry 모델의 inference 권한을 부탁드립니다.
>
> **Purview:** 자식 Agent ID와 테스트 사용자를 포함하는 활성 Application DLP 정책, 테스트 SIT, `UploadText=Block`, inline 입력 평가를 준비하고 정책·규칙 이름/ID를 알려 주세요. Credit Card Number 예제 기준은 신뢰도 85 이상, 1개 이상입니다.
>
> **테스트:** 고객 사용자가 직접 로그인할 수 있는 일정과 승인된 실행 PC, OneDrive의 일반 TXT·SIT 확인된 합성 TXT를 준비해 주세요. 기존 Agent 365 등록 여부도 알려 주세요. 새 등록을 맡기는 경우 CLI 인증 앱·프로비저닝 담당자 정보는 추가로 맞추겠습니다.

**English summary:** Request non-secret runtime settings, two secrets through an approved channel, both user-specific delegated grants, independent model inference access, the child/user-targeted inline UploadText DLP policy, and a customer user who can sign in on the approved test machine. Request CLI provisioning information only when new onboarding is required.
