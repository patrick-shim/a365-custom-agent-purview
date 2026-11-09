# 설정값을 어디서 찾고 어디에 넣나요? · Configuration value guide

이 문서는 공개 템플릿의 빈칸을 **찾기 → 복사 → 붙여넣기 → 확인** 순서로 채우는 안내입니다. PowerShell은 프로젝트 폴더에서 실행합니다. `<...>`는 설명용 자리표시자이므로 실제 값으로 바꿉니다. 아래 반복 숫자 UUID와 `example.com` 주소는 모두 **가상 예시**이며 작동하는 계정이나 자격 증명이 아닙니다.

This guide maps each setting to its source and destination. Replace every placeholder with your own value. Repeated-digit UUIDs and example domains are fictional.

**상위 부서가 값을 제공하는 실행자:** [제한 환경 안내](restricted-environment.md)에 따라 `.env`만 준비합니다. 이 문서의 앱/Secret 생성·Graph 변경·CLI 절차는 권한 있는 담당자를 위한 참고이며, Python 실행의 필수 단계가 아닙니다. / Runtime-only customers use the restricted guide and prepare `.env`; provisioning commands and CLI files belong to authorized administrators.

## 1. 두 파일 준비 · Prepare two files

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
if (-not (Test-Path -LiteralPath a365.config.json)) {
    Copy-Item -LiteralPath a365.config.example.json -Destination a365.config.json
}
notepad .env
notepad a365.config.json
```

`.env`는 Python 프로그램, `a365.config.json`은 등록용 CLI가 읽습니다. 두 실제 설정 파일과 `a365.generated.config.json`은 Git에서 제외됩니다. 공개 예제 파일에 실제 비밀값을 넣지 않습니다. 아래 Graph 변경 예제는 **해당 자원을 관리할 권한이 있는 관리자/소유자**가 실행하는 별도 설정 작업입니다. 로컬 프로그램 실행에 관리자 권한이 필요한 것은 아닙니다.

The Python app reads `.env`; the onboarding CLI reads `a365.config.json`. Administrator provisioning is separate from running the app.

**공개 설정값과 비밀값:** Tenant·Client·Blueprint·Agent ID, endpoint URL, 배포 이름은 공개 가능한 설정값입니다. Client Secret, API Key, access/refresh token은 비밀값이며 Git에 넣지 않습니다. 이 가이드의 가상 ID는 환경별 재사용을 위한 예제입니다. 실제 ID가 비밀이라는 뜻은 아닙니다.

**Public values versus credentials:** IDs, endpoint URLs, and deployment names may be shared. Client secrets, API keys, and tokens must stay outside Git. Fictional IDs make these examples reusable; they are not a claim that identifiers are secrets.

### MSAL을 설치했는데 왜 앱 ID도 필요한가요? · SDK versus identity

| 항목 · Item | 역할 · Role |
|---|---|
| MSAL / Microsoft Agents Python SDK | 토큰 요청·검증을 구현하는 코드 라이브러리입니다. 설치해도 Entra에 로그인 앱이 등록되지는 않습니다. / Libraries implement authentication; installation does not create an app registration. |
| `WEB_CLIENT_ID`의 일반 로그인 앱 | 사용자를 로그인시키고 Blueprint용 사용자 토큰을 받는 클라이언트입니다. 호환되는 기존 앱을 재사용할 수 있습니다. / An existing compatible sign-in client can be reused. |
| Blueprint + 자식 `AGENT_IDENTITY_ID` | Blueprint 자격 증명으로 자식을 인증하고, `Files.Read`를 가진 자식이 사용자 OBO로 Graph에 접근합니다. / The child holds file permissions and accesses Graph on behalf of the user. |

이 프로젝트에서 웹 앱은 OneDrive를 직접 읽지 않습니다. 새 웹 앱 생성은 호환되는 로그인 클라이언트가 없을 때의 준비 단계입니다.

## 2. 테넌트와 테스트 사용자 · Tenant and test user

**찾기:** [Azure portal](https://portal.azure.com)에서 Microsoft Entra ID의 Overview에 있는 **Tenant ID**를 확인합니다. OneDrive 파일을 소유한 사용자의 테넌트여야 합니다. 사용자 프로필의 **User principal name**은 로그인할 계정명이고, **Object ID**는 Graph 권한 부여에 쓰는 별도 UUID입니다. [테넌트와 사용자 ID 찾기](https://learn.microsoft.com/en-us/partner-center/account-settings/find-ids-and-domain-names)

**붙여넣기:**

```dotenv
ENTRA_TENANT_ID=11111111-1111-4111-8111-111111111111
EXPECTED_USER=tester@example.com
```

위 값은 예시입니다. 같은 실제 테넌트 UUID를 `a365.config.json`의 `tenantId`에도 넣습니다. `EXPECTED_USER`는 선택 사항입니다. 비워 두면 이 테넌트의 다른 사용자도 로그인할 수 있지만, 각 사용자의 OBO 동의와 OneDrive/Purview 권한은 여전히 필요합니다.

**확인:** Azure CLI가 설치되어 있다면 다음 조회로 실제 사용자 Object ID를 얻습니다. 이 명령은 일반 사용자 메타데이터 조회이며, Agent ID 설정용 Graph 토큰을 만드는 명령이 아닙니다.

```powershell
az login --tenant "<ENTRA_TENANT_ID>"
az account show --query tenantId -o tsv
az ad user show --id "tester@your-tenant.example" --query "{id:id,userPrincipalName:userPrincipalName}" -o json
```

Copy Tenant ID into both tenant settings. Copy the user's UPN into `EXPECTED_USER` and keep their object ID for user-specific consent. A UPN and a user object ID are not interchangeable.

## 3. 기존 Blueprint와 자식 Agent ID · Existing blueprint and child

**찾기:** [Entra admin center](https://entra.microsoft.com) → **Entra ID → Agents → Agent blueprints**에서 사용할 Blueprint를 선택합니다. 목록의 열을 선택해 다음 두 값을 구분합니다.

| 화면/응답 값 · Source | 넣을 곳 · Destination |
|---|---|
| **Blueprint Application ID** | `.env: BLUEPRINT_CLIENT_ID`; CLI 생성 상태의 `agentBlueprintId` |
| Blueprint 목록의 **Object ID** | Blueprint **서비스 주체** ID; `agentBlueprintServicePrincipalObjectId` |
| Blueprint 애플리케이션을 Graph로 조회한 `id` | 애플리케이션 개체 ID; `agentBlueprintObjectId` |
| **Linked agent identities**에서 선택한 자식의 **Object ID** | `.env: AGENT_IDENTITY_ID`; CLI 생성 상태의 `agenticAppId` |
| Blueprint와 자식의 표시 이름 | `a365.config.json`의 `agentBlueprintDisplayName`와 `agentIdentityDisplayName` |

Blueprint 화면의 Object ID는 **서비스 주체** ID입니다. 애플리케이션 개체 ID로 잘못 복사하지 않습니다. 자식이 해당 Blueprint에 연결되어 있는지도 확인합니다. [Blueprint 화면과 열](https://learn.microsoft.com/en-us/entra/agent-id/manage-agent-blueprint), [자식 Agent ID 조회 화면](https://learn.microsoft.com/en-us/entra/agent-id/manage-agent-identities-admin)

**붙여넣기 예시:**

```dotenv
BLUEPRINT_CLIENT_ID=22222222-2222-4222-8222-222222222222
AGENT_IDENTITY_ID=33333333-3333-4333-8333-333333333333
PURVIEW_APP_ID=33333333-3333-4333-8333-333333333333
APP_NAME=onedrive-purview-agent
```

`PURVIEW_APP_ID`는 이 OBO 흐름에서 **자식 ID**를 사용합니다. 비워 두어도 코드가 `AGENT_IDENTITY_ID`를 사용합니다. Purview 정책의 대상 애플리케이션도 같은 자식이어야 합니다.

**확인:** 아래 5절의 조회가 Blueprint 애플리케이션의 실제 `id`와 `appId`를 출력합니다. 서로 같아 보이더라도 다른 종류의 값이므로 응답 필드에 맞춰 기록합니다. 설치된 a365 1.1.221에는 이름으로 모든 Blueprint/자식 ID를 나열하는 전용 명령이 없습니다. `query-entra instance-scopes`는 설정된 자식의 **권한**을 조회하며 ID를 자동 발견하는 명령이 아닙니다.

Use the blueprint's Application ID for authentication, its principal object ID for consent, and its application object ID for application updates. The child object ID is the agent identity used by this app.

## 4. Blueprint 비밀값 · Blueprint credential

**찾기/생성:** 선택한 Blueprint의 **Developer settings → Credentials → Client secrets → New client secret**에서 개발용 설명과 만료일을 지정하고 추가합니다. 이미 유효한 값을 안전하게 전달받았다면 새로 만들 필요가 없습니다.

**복사:** 추가 직후 나타나는 **Value**를 복사합니다. `Secret ID`, 자격 증명의 `keyId`, Blueprint ID를 복사하는 것이 아닙니다.

**붙여넣기:**

```dotenv
BLUEPRINT_CLIENT_SECRET='PASTE_THE_NEW_SECRET_VALUE_HERE'
```

위 설명 문자열을 실제 값으로 바꿉니다. 값은 페이지를 떠난 뒤 다시 조회할 수 없습니다. 분실했다면 **새 비밀값을 추가**하고 이 파일을 갱신합니다. 공유 Blueprint에서 다른 프로그램이 쓰는 기존 자격 증명을 삭제하거나 교체하지 않습니다. 만료일도 별도로 기록합니다. [Blueprint 자격 증명 생성](https://learn.microsoft.com/en-us/entra/agent-id/manage-agent-blueprint)

**확인:** 로컬 설정 검사는 값의 존재만 확인합니다. 실제 유효성은 로그인 후 OBO 요청으로 확인됩니다. 이 로컬 앱은 두 비밀값을 사용하며, 자식 Agent ID에는 별도 비밀값을 만들지 않습니다.

Copy the newly created secret **Value**, not its ID. Lost secret values cannot be recovered; add a new credential and preserve credentials used by other applications.

<a id="blueprint-scope"></a>
## 5. BLUEPRINT_SCOPE: 노출된 API 범위 · Exposed API scope

`BLUEPRINT_SCOPE`는 임의의 문자열이 아닙니다. Blueprint에 **실제로 활성화된 범위**가 있어야 합니다. 이 앱은 Blueprint를 대상으로 발급된 v2 사용자 토큰을 검증합니다.

**기존 설정 찾기:** 아래 PowerShell 7 예제는 애플리케이션을 client ID로 찾아 `id`, URI, 범위를 조회합니다. Microsoft Graph PowerShell 인증 모듈은 관리 작업을 할 PC에 한 번 설치합니다. 이 조회의 `Application.Read.All`은 관리 도구의 권한이며, 런타임 자식에게 주는 권한이 아닙니다.

`Application.Read.All`은 일반 애플리케이션 조회와 아래 typed Blueprint 조회를 모두 허용하는 권한입니다. typed 조회만 수행할 때의 더 좁은 권한은 `AgentIdentityBlueprint.Read.All`입니다. [Blueprint 조회 권한](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprint-get?view=graph-rest-1.0)

```powershell
Install-Module Microsoft.Graph.Authentication -Scope CurrentUser
$tenantId = '<ENTRA_TENANT_ID>'
$blueprintId = '<BLUEPRINT_CLIENT_ID>'
Connect-MgGraph -TenantId $tenantId -Scopes 'Application.Read.All' -ContextScope Process -NoWelcome
$lookupUri = "https://graph.microsoft.com/v1.0/applications(appId='$blueprintId')"
$agentHeaders = @{ 'OData-Version' = '4.0' }
$blueprint = Invoke-MgGraphRequest -Method GET -Uri $lookupUri -Headers $agentHeaders -OutputType Hashtable -ErrorAction Stop
[pscustomobject]@{ id=$blueprint.id; appId=$blueprint.appId; displayName=$blueprint.displayName; identifierUris=$blueprint.identifierUris } | Format-List
$blueprint.api | ConvertTo-Json -Depth 8
Disconnect-MgGraph
```

**복사:** 이 앱은 `api://<BLUEPRINT_CLIENT_ID>/<범위 이름>` 형식만 받습니다. `identifierUris`에 해당 `api://` URI가 있고, `api.oauth2PermissionScopes`에 `isEnabled=true`인 범위가 있는지 확인합니다. 예를 들어 URI가 `api://22222222-2222-4222-8222-222222222222`이고 범위 값이 `access_agent_as_user`라면 다음과 같습니다. 다른 사용자 지정 URI만 있다면 아래 추가 절차로 필요한 URI를 등록합니다.

```dotenv
BLUEPRINT_SCOPE=api://22222222-2222-4222-8222-222222222222/access_agent_as_user
```

범위 항목의 `id`는 별도의 UUID입니다. 이것은 웹 앱의 `requiredResourceAccess` 설정에 사용하고, `BLUEPRINT_SCOPE`에 넣지 않습니다. `api.requestedAccessTokenVersion`은 `2`여야 합니다. [애플리케이션 ID별 조회](https://learn.microsoft.com/en-us/graph/api/application-get?view=graph-rest-1.0), [Agent OBO의 사용자 토큰 대상](https://learn.microsoft.com/en-us/entra/agent-id/agent-on-behalf-of-oauth-flow)

### 범위가 없다면: 기존 항목을 보존하고 추가 · Add a missing scope

다음은 Blueprint 소유자/관리자가 실행하는 **변경 작업**입니다. 기존 URI, 범위, 다른 API 설정을 유지하면서 필요한 URI/범위를 추가하고 v2로 설정합니다. 공유 Blueprint의 토큰 버전 변경은 다른 클라이언트에도 영향을 줄 수 있으므로 해당 Blueprint 담당자와 맞춰 적용합니다. 이미 설정되었다면 다시 실행할 필요가 없습니다. 범위 설정에 필요한 권한은 `AgentIdentityBlueprint.UpdateAuthProperties.All`입니다. [공식 URI/범위 설정](https://learn.microsoft.com/en-us/entra/agent-id/create-blueprint#configure-identifier-uri-and-scope)

```powershell
$tenantId = '<ENTRA_TENANT_ID>'
$blueprintId = '<BLUEPRINT_CLIENT_ID>'
Connect-MgGraph -TenantId $tenantId -Scopes @(
    'Application.Read.All', 'AgentIdentityBlueprint.UpdateAuthProperties.All'
) -ContextScope Process -NoWelcome
$lookupUri = "https://graph.microsoft.com/v1.0/applications(appId='$blueprintId')"
$agentHeaders = @{ 'OData-Version' = '4.0' }
$blueprint = Invoke-MgGraphRequest -Method GET -Uri $lookupUri -Headers $agentHeaders -OutputType Hashtable -ErrorAction Stop
$blueprintObjectId = $blueprint.id
$typedUri = "https://graph.microsoft.com/v1.0/applications/$blueprintObjectId/microsoft.graph.agentIdentityBlueprint"
# A typed read confirms that this application is a blueprint.
$blueprint = Invoke-MgGraphRequest -Method GET -Uri $typedUri -Headers $agentHeaders -OutputType Hashtable -ErrorAction Stop

$api = @{}
if ($blueprint.api) {
    foreach ($key in $blueprint.api.Keys) { $api[$key] = $blueprint.api[$key] }
}
$scopeName = 'access_agent_as_user'
$scopes = @($api.oauth2PermissionScopes | Where-Object { $null -ne $_ })
$matching = @($scopes | Where-Object { $_.value -eq $scopeName })
if ($matching.Count -gt 1) { throw 'Duplicate scope names need administrator review.' }
if ($matching.Count -eq 1 -and -not $matching[0].isEnabled) {
    throw 'The existing scope is disabled. Ask its owner before changing it.'
}
if ($matching.Count -eq 0) {
    $scopes += @{
        id = [guid]::NewGuid().ToString()
        value = $scopeName
        type = 'Admin'
        isEnabled = $true
        adminConsentDisplayName = 'Invoke the agent as a signed-in user'
        adminConsentDescription = 'Allow the web client to invoke this agent on behalf of the signed-in user.'
    }
}
$identifier = "api://$blueprintId"
$api.oauth2PermissionScopes = $scopes
$api.requestedAccessTokenVersion = 2
$uris = @(@($blueprint.identifierUris) + $identifier | Where-Object { $_ } | Sort-Object -Unique)
$patch = @{ identifierUris = $uris; api = $api }
$null = Invoke-MgGraphRequest -Method PATCH -Uri $typedUri -Headers $agentHeaders -ContentType 'application/json' -Body ($patch | ConvertTo-Json -Depth 20) -ErrorAction Stop

$verified = Invoke-MgGraphRequest -Method GET -Uri $typedUri -Headers $agentHeaders -OutputType Hashtable -ErrorAction Stop
$verifiedScope = @($verified.api.oauth2PermissionScopes | Where-Object { $_.value -eq $scopeName -and $_.isEnabled })
if ($verifiedScope.Count -ne 1 -or $verified.api.requestedAccessTokenVersion -ne 2 -or $identifier -notin $verified.identifierUris) {
    throw 'Blueprint API readback did not match the requested configuration.'
}
[pscustomobject]@{
    BLUEPRINT_CLIENT_ID = $verified.appId
    BLUEPRINT_SCOPE = "$identifier/$scopeName"
    BlueprintApplicationObjectId = $verified.id
    ScopeId = $verifiedScope[0].id
    AccessTokenVersion = $verified.api.requestedAccessTokenVersion
} | Format-List
Disconnect-MgGraph
```

출력의 `BLUEPRINT_SCOPE`를 그대로 `.env`에 복사하고 `ScopeId`를 다음 단계용으로 기록합니다. 비밀값은 이 명령에서 생성하거나 출력하지 않습니다.

Use an enabled scope in the app's required `api://<BLUEPRINT_CLIENT_ID>/<scope-name>` format; do not paste its GUID or `.default` as the scope string. The optional administrator block preserves existing collections, adds the scope if missing, and verifies the resulting v2 API configuration.

<a id="web-client"></a>
## 6. WEB_CLIENT_ID / SECRET: 브라우저 로그인 앱 · Browser sign-in app

Blueprint와 자식은 직접 대화형 로그인을 시작할 수 없습니다. 사용자를 로그인시키는 **일반 Web 앱 등록**이 별도로 필요합니다. [Agent 로그인 제약](https://learn.microsoft.com/en-us/entra/agent-id/agent-on-behalf-of-oauth-flow)

**이미 로그인 앱이 있는데 새 앱을 만들어야 하나요?** 아닙니다. 같은 테넌트의 기존 일반 로그인 앱이 아래 Web callback, 서버용 자격 증명, Blueprint 범위 요청과 사용자 동의를 지원하면 재사용할 수 있습니다. 이 저장소처럼 독립된 로컬 브라우저 앱으로 실행하고 호환되는 로그인 앱이 없을 때만 하나를 만듭니다.

**파일은 누가 읽나요?** `Files.Read`를 가진 **자식 Agent ID**가 사람 사용자의 OBO Graph 토큰으로 읽습니다. 웹 로그인 앱의 역할은 사용자를 로그인시키고 Blueprint를 대상으로 한 사용자 토큰을 받는 것입니다. 웹 앱에 `Files.Read`를 부여할 필요가 없습니다. Blueprint의 자격 증명으로 자식을 인증한 뒤, 자식이 사용자 토큰을 Graph용 토큰으로 교환합니다. 따라서 웹 앱 → Blueprint 범위 동의와 자식 → Graph `Files.Read` 동의는 서로 다른 단계입니다.

Reuse an existing compatible sign-in app; creating a new registration is only needed when this standalone browser app has none. The **child agent** holds `Files.Read` and reads OneDrive through human-user OBO. The web client obtains the user's blueprint-scoped token and does not need a Graph file permission.

**기존 앱 찾기:** Entra ID → **App registrations**에서 이 프로젝트의 웹 앱을 선택합니다. Overview의 **Application (client) ID**를 `WEB_CLIENT_ID`에 넣습니다. 여기의 Object ID나 Enterprise application Object ID를 넣지 않습니다.

**앱이 없다면 생성:**

1. **App registrations → New registration**에서 `onedrive-purview-web` 같은 이름을 정합니다.
2. 이 조직 디렉터리만 사용하는 **Single tenant**를 선택하고 등록합니다.
3. **Authentication → Redirect URI configuration → Add Redirect URI → Web**에 `http://localhost:8000/auth/callback`을 추가합니다.
4. Overview의 Application (client) ID를 복사합니다.

[앱 등록](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app), [Web 리디렉션 URI 설정](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-redirect-uri)

**비밀값 생성:** 웹 앱의 **Certificates & secrets → Client secrets → New client secret**에서 값을 추가합니다. 추가 직후 **Value**를 복사하고 `WEB_CLIENT_SECRET`에 넣습니다. `Secret ID`가 아닙니다. 분실 시 기존 값을 복원할 수 없으므로 새 항목을 추가합니다. [웹 앱 자격 증명](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-credentials)

```dotenv
WEB_CLIENT_ID=44444444-4444-4444-8444-444444444444
WEB_CLIENT_SECRET='PASTE_THE_WEB_SECRET_VALUE_HERE'
REDIRECT_URI=http://localhost:8000/auth/callback
```

**확인:** Web 플랫폼의 URI와 `REDIRECT_URI`가 정확히 일치해야 합니다. 이 앱은 서버 측 authorization-code 흐름을 사용하므로 SPA 등록이나 implicit-flow 설정은 필요하지 않습니다. 아래 API 요청 설정과 동의 두 단계도 완료해야 합니다.

### 웹 앱이 요청할 Blueprint 범위 · Configure the requested permission

웹 앱의 **API permissions → Add a permission → My APIs**에서 Blueprint API가 표시되면 해당 API의 Delegated 범위를 선택해 추가할 수 있습니다. 이것은 요청할 권한의 등록이며, 사용자별 동의 기록을 만드는 작업과는 별도입니다. [웹 API 권한 설정](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-access-web-apis)

Blueprint가 선택 목록에 보이지 않으면 다음 관리자용 Graph 예제를 사용합니다. 기존 다른 API 권한은 유지합니다. `<BLUEPRINT_SCOPE_ID>`는 5절에서 확인한 범위 항목의 UUID입니다.

```powershell
$tenantId = '<ENTRA_TENANT_ID>'
$webClientId = '<WEB_CLIENT_ID>'
$blueprintId = '<BLUEPRINT_CLIENT_ID>'
$scopeId = '<BLUEPRINT_SCOPE_ID>'
Connect-MgGraph -TenantId $tenantId -Scopes 'Application.ReadWrite.All' -ContextScope Process -NoWelcome
$webUri = "https://graph.microsoft.com/v1.0/applications(appId='$webClientId')"
$web = Invoke-MgGraphRequest -Method GET -Uri $webUri -OutputType Hashtable -ErrorAction Stop
$resources = @($web.requiredResourceAccess | Where-Object { $null -ne $_ })
$matching = @($resources | Where-Object { $_.resourceAppId -eq $blueprintId })
if ($matching.Count -gt 1) { throw 'Duplicate API entries need administrator review.' }
if ($matching.Count -eq 0) {
    $resources += @{ resourceAppId = $blueprintId; resourceAccess = @(@{ id = $scopeId; type = 'Scope' }) }
} elseif (-not @($matching[0].resourceAccess | Where-Object { $_.id -eq $scopeId -and $_.type -eq 'Scope' }).Count) {
    $matching[0].resourceAccess = @($matching[0].resourceAccess) + @{ id = $scopeId; type = 'Scope' }
}
$patch = @{ requiredResourceAccess = $resources }
$null = Invoke-MgGraphRequest -Method PATCH -Uri ("https://graph.microsoft.com/v1.0/applications/" + $web.id) -ContentType 'application/json' -Body ($patch | ConvertTo-Json -Depth 12) -ErrorAction Stop
$verifiedWeb = Invoke-MgGraphRequest -Method GET -Uri $webUri -OutputType Hashtable -ErrorAction Stop
$verifiedWeb.requiredResourceAccess | ConvertTo-Json -Depth 12
Disconnect-MgGraph
```

Create or reuse an ordinary single-tenant Web registration. Its client ID, secret Value, and exact callback fill the three web settings. Add the blueprint's delegated scope to its requested API permissions; the next section grants consent.

<a id="consent"></a>
## 7. 사용자별 동의는 두 군데 · Two separate user grants

한 사용자에 대해 다음 두 동의가 필요합니다. `EXPECTED_USER`를 바꾸거나 웹 앱의 API permissions 목록에 추가하는 것만으로 완료되지 않습니다.

| 동의 · Grant | `clientId` | `resourceId` | `scope` |
|---|---|---|---|
| 웹 로그인 앱 → Blueprint API | 웹 앱 **서비스 주체 Object ID** | Blueprint **서비스 주체 Object ID** | `access_agent_as_user` 또는 실제 범위 이름 |
| 자식 에이전트 → Microsoft Graph | 자식 Agent ID | 해당 테넌트의 **Microsoft Graph 서비스 주체 Object ID** | `Files.Read Content.Process.User ProtectionScopes.Compute.User` |

두 행 모두 `consentType=Principal`, `principalId=<테스트 사용자 Object ID>`입니다. 이 프로젝트는 자식에게 직접 권한을 부여하므로 공유 Blueprint에 Graph 권한 상속을 추가할 필요가 없습니다. [Graph 동의 객체의 필드](https://learn.microsoft.com/en-us/graph/api/oauth2permissiongrant-post?view=graph-rest-1.0), [직접 부여와 상속](https://learn.microsoft.com/en-us/entra/agent-id/migrate-custom-app-registrations-to-agent-id)

**ID 찾기:** 아래는 일반 서비스 주체/사용자 메타데이터 조회입니다. 먼저 올바른 테넌트로 Azure CLI에 로그인합니다. `00000003-0000-0000-c000-000000000000`은 Microsoft Graph의 공통 **애플리케이션 ID**이며, 동의 객체의 `resourceId`에는 이 명령이 돌려준 테넌트별 **id**를 사용합니다.

```powershell
az login --tenant "<ENTRA_TENANT_ID>"
az ad user show --id "<TEST_USER_UPN>" --query id -o tsv
az ad sp show --id "<WEB_CLIENT_ID>" --query id -o tsv
az ad sp show --id "00000003-0000-0000-c000-000000000000" --query id -o tsv
```

Blueprint 서비스 주체 ID는 3절의 Blueprint 목록에서 확인합니다. 웹 앱은 포털에서 등록하면 서비스 주체도 생성됩니다. 앱과 서비스 주체의 차이는 [Microsoft Entra 객체 설명](https://learn.microsoft.com/en-us/entra/identity-platform/app-objects-and-service-principals)을 참고하세요.

**권한 부여:** 아래 함수는 동일 사용자의 기존 동의를 찾아 부족한 범위만 합쳐 추가합니다. 기존 범위를 제거하지 않습니다. 별도의 전체 사용자 동의나 상속이 있다면 이 함수가 제거하지 않으므로 접근 범위는 더 넓을 수 있습니다. `DelegatedPermissionGrant.ReadWrite.All`과 해당 동의를 부여할 관리 권한이 있는 사람이 실행합니다. 이 관리 권한을 런타임 자식에게 부여하지 않습니다.

`<BLUEPRINT_SCOPE_NAME>`에는 `.env`의 `BLUEPRINT_SCOPE`에서 마지막 `/` 뒤에 있는 실제 범위 이름을 넣습니다. 예를 들어 `api://<ID>/access_agent_as_user`라면 `access_agent_as_user`입니다. 기존에 다른 이름의 범위를 선택했다면 그 이름을 사용하며, URI 전체나 범위 UUID를 넣지 않습니다.

```powershell
$tenantId = '<ENTRA_TENANT_ID>'
$blueprintScopeName = '<BLUEPRINT_SCOPE_NAME>'
Connect-MgGraph -TenantId $tenantId -Scopes 'DelegatedPermissionGrant.ReadWrite.All' -ContextScope Process -NoWelcome

function Set-UserDelegatedGrant {
    param([string]$ClientSpId, [string]$ResourceSpId, [string]$UserObjectId, [string[]]$Scopes)
    $filter = [Uri]::EscapeDataString("clientId eq '$ClientSpId'")
    $uri = 'https://graph.microsoft.com/v1.0/oauth2PermissionGrants?$filter=' + $filter
    $allGrants = @()
    do {
        $page = Invoke-MgGraphRequest -Method GET -Uri $uri -OutputType Hashtable -ErrorAction Stop
        $allGrants += @($page.value)
        $uri = $page.'@odata.nextLink'
    } while ($uri)
    $existing = @($allGrants | Where-Object {
        $_.resourceId -eq $ResourceSpId -and $_.consentType -eq 'Principal' -and $_.principalId -eq $UserObjectId
    })
    if ($existing.Count -gt 1) { throw 'Duplicate grants need administrator review.' }
    if ($existing.Count -eq 0) {
        $body = @{ clientId=$ClientSpId; resourceId=$ResourceSpId; consentType='Principal'; principalId=$UserObjectId; scope=($Scopes -join ' ') }
        $created = Invoke-MgGraphRequest -Method POST -Uri 'https://graph.microsoft.com/v1.0/oauth2PermissionGrants' -ContentType 'application/json' -Body ($body | ConvertTo-Json) -OutputType Hashtable -ErrorAction Stop
        $grantId = $created.id
    } else {
        $grantId = $existing[0].id
        $missing = @($Scopes | Where-Object { $_ -notin ($existing[0].scope -split ' ') })
        if ($missing.Count -gt 0) {
            $combined = @(($existing[0].scope -split ' ') + $Scopes | Where-Object { $_ } | Sort-Object -Unique)
            $body = @{ scope=($combined -join ' ') }
            $null = Invoke-MgGraphRequest -Method PATCH -Uri ("https://graph.microsoft.com/v1.0/oauth2PermissionGrants/" + $grantId) -ContentType 'application/json' -Body ($body | ConvertTo-Json) -ErrorAction Stop
        }
    }
    if (-not $grantId) { throw 'No grant ID returned.' }
    $verified = Invoke-MgGraphRequest -Method GET -Uri ("https://graph.microsoft.com/v1.0/oauth2PermissionGrants/" + $grantId) -OutputType Hashtable -ErrorAction Stop
    if ($verified.clientId -ne $ClientSpId -or $verified.resourceId -ne $ResourceSpId -or $verified.principalId -ne $UserObjectId -or $verified.consentType -ne 'Principal') {
        throw 'Grant identity readback did not match.'
    }
    if (@($Scopes | Where-Object { $_ -notin ($verified.scope -split ' ') }).Count -gt 0) { throw 'Required scopes were not confirmed.' }
    [pscustomobject]@{ clientId=$verified.clientId; resourceId=$verified.resourceId; principalId=$verified.principalId; scope=$verified.scope }
}

Set-UserDelegatedGrant -ClientSpId '<WEB_SERVICE_PRINCIPAL_OBJECT_ID>' -ResourceSpId '<BLUEPRINT_SERVICE_PRINCIPAL_OBJECT_ID>' -UserObjectId '<TEST_USER_OBJECT_ID>' -Scopes @($blueprintScopeName)
Set-UserDelegatedGrant -ClientSpId '<AGENT_IDENTITY_ID>' -ResourceSpId '<GRAPH_SERVICE_PRINCIPAL_OBJECT_ID>' -UserObjectId '<TEST_USER_OBJECT_ID>' -Scopes @('Files.Read','Content.Process.User','ProtectionScopes.Compute.User')
Disconnect-MgGraph
```

**확인:** 출력의 두 `clientId`와 `resourceId`가 표의 대상과 같고, 필요한 범위가 포함되어야 합니다. 자식의 추가 권한은 프로젝트의 a365 설정 후 `a365 query-entra instance-scopes`로도 확인합니다.

Grant the web client access to the blueprint API and the child access to Graph for the same human user. The function preserves existing scopes and verifies both the identities and scopes after writing.

## 8. Foundry 설정 네 가지와 인증 · Foundry values and authentication

### FOUNDRY_ENDPOINT

**찾기:** [Foundry portal](https://ai.azure.com)에서 모델이 배포된 프로젝트/리소스를 엽니다. 현재 새 화면에서는 **Build → Models → 사용할 배포**로 이동하여 endpoint 또는 Code 예제를 봅니다. 이전 화면의 같은 목록은 **Models + endpoints**로 표시될 수 있습니다. [현재 배포 조회 화면](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/deploy-foundry-models#manage-models)

**복사/붙여넣기:** 이 프로젝트는 코드에서 `/openai/v1/`을 붙입니다. 따라서 `FOUNDRY_ENDPOINT`에는 **리소스 루트**만 넣습니다.

| 포털/코드에서 본 예 · Observed example | 이 프로젝트에 넣을 값 · Paste here |
|---|---|
| `https://example-resource.services.ai.azure.com/openai/v1/` | `https://example-resource.services.ai.azure.com` |
| `https://example-resource.openai.azure.com/openai/v1/` | `https://example-resource.openai.azure.com` |
| `.../api/projects/example-project` | 프로젝트 관리 주소입니다. 모델 배포의 OpenAI endpoint를 다시 찾습니다. / Find the model endpoint instead. |

`/models`, `/openai/v1/`, `/deployments/...`, 쿼리 문자열을 붙이지 않습니다. 이 앱은 **Responses API와 도구 호출**을 지원하는 배포를 사용합니다. [Foundry endpoint와 배포 이름](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints)

### FOUNDRY_DEPLOYMENT

**찾기:** 같은 배포 목록/상세 화면의 **배포 이름**을 복사합니다. 카탈로그의 기본 모델 이름이 아니라 사용자가 배포에 붙인 이름입니다. 예를 들어 모델이 `gpt-4.1`이고 배포 이름이 `summary-demo`라면 다음을 넣습니다.

```dotenv
FOUNDRY_ENDPOINT=https://example-resource.services.ai.azure.com
FOUNDRY_DEPLOYMENT=summary-demo
```

**확인용 조회:** 리소스 이름과 리소스 그룹은 Azure portal의 해당 Foundry/Azure OpenAI 리소스 Overview에서 확인합니다.

```powershell
az cognitiveservices account show --name "<FOUNDRY_RESOURCE_NAME>" --resource-group "<RESOURCE_GROUP>" --query properties.endpoint -o tsv
az cognitiveservices account deployment list --name "<FOUNDRY_RESOURCE_NAME>" --resource-group "<RESOURCE_GROUP>" --query "[].{deployment:name,model:properties.model.name}" -o table
```

일반 리소스 조회의 endpoint와 모델 배포의 OpenAI 코드 예제가 다른 주소를 표시한다면, **사용할 배포의 OpenAI v1 코드 예제**에서 리소스 루트를 확인합니다. 프로젝트 관리용 URL이나 다른 API용 주소를 대신 넣지 않습니다.

### FOUNDRY_TENANT_ID / AUTH_MODE / API_KEY

**찾기:** 모델 리소스가 속한 디렉터리의 Tenant ID를 확인합니다. Microsoft 365 테넌트와 같을 수도, 다를 수도 있습니다. 이 앱의 설정 검사에서는 API key 방식이어도 `FOUNDRY_TENANT_ID`를 입력합니다.

기본값인 `azure_cli`에서는 모델 호출 권한이 있는 계정으로 해당 테넌트에 로그인합니다. `FOUNDRY_API_KEY`는 비워 둡니다.

```dotenv
FOUNDRY_TENANT_ID=11111111-1111-4111-8111-111111111111
FOUNDRY_AUTH_MODE=azure_cli
FOUNDRY_API_KEY=
```

```powershell
az login --tenant "<FOUNDRY_TENANT_ID>"
az account show --query tenantId -o tsv
```

키 방식이 필요한 경우에만 `FOUNDRY_AUTH_MODE=api_key`로 변경하고, 배포 상세 화면의 키 또는 Azure portal 해당 리소스의 **Keys and Endpoint**에서 허용된 키를 `FOUNDRY_API_KEY`에 넣습니다. Azure CLI로 로그인했다는 사실만으로 모델의 데이터 접근 권한이 부여되지는 않습니다. 리소스 관리자가 필요한 모델 호출 RBAC를 부여해야 합니다. [키 없는 모델 인증](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints#use-keyless-authentication)

**Azure OpenAI 배포의 권한 요청 예:** 모델 리소스의 **Access control (IAM) → Add role assignment**에서 로컬 PC의 `az login`에 사용할 계정에 **Cognitive Services OpenAI User**를 부여하도록 요청합니다. 이 역할은 Entra ID로 모델을 호출할 수 있으며 모델 생성·키 조회 권한은 포함하지 않습니다. OneDrive에 로그인하는 사용자와 모델 호출 계정은 서로 다를 수 있습니다. 다른 모델 종류는 해당 배포에서 지원하는 데이터 호출 역할을 확인합니다. [Azure OpenAI 역할과 부여 위치](https://learn.microsoft.com/en-us/azure/foundry-classic/openai/how-to/role-based-access-control)

For an Azure OpenAI deployment, ask the resource administrator to assign **Cognitive Services OpenAI User** on the model resource to the account used by local Azure CLI. This model caller is independent of the OneDrive user. Other deployment types require their supported inference role.

Use a model resource root URL and your deployment's assigned name. Set the model tenant independently. Azure CLI authentication needs an authorized model caller; API-key mode instead needs a valid key stored only in `.env`.

## 9. a365 CLI 설정값 · CLI configuration values

`clientAppId`는 `WEB_CLIENT_ID`나 Blueprint ID가 아닙니다. **CLI를 사용하는 관리자가 로그인할 앱**의 Application (client) ID입니다.

**기존 CLI 앱 찾기:** Entra ID의 Enterprise applications에서 조직이 사용하는 Agent 365 CLI 앱을 확인하거나 관리자에게 해당 **Application ID**를 받습니다. 조직 소유 앱은 App registrations의 Overview에서도 client ID를 확인할 수 있습니다. Microsoft 관리형 CLI 앱을 사용하는 테넌트도 있습니다. 설치된 버전의 동작은 아래 help로 먼저 확인합니다. [CLI 앱 선택](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/reference/cli/setup)

기존에 설정한 CLI 프로젝트가 있다면 그 로컬 `a365.config.json`의 `clientAppId`도 확인할 수 있습니다. 기본 이름의 조직 소유 앱을 조회하려면 다음을 실행합니다. 결과가 여러 개면 사용할 앱의 소유자와 권한을 확인한 뒤 선택합니다.

```powershell
az ad app list --display-name "Agent 365 CLI" --query "[].{name:displayName,clientAppId:appId}" -o table
```

**조직 소유 CLI 앱이 없다면:** 다음 순서로 만들 수 있습니다. Microsoft 관리형 CLI 앱을 이미 사용할 수 있다면 조직 소유 앱을 추가할 필요가 없습니다.

1. App registrations → New registration에서 이름을 `Agent 365 CLI`, 계정 유형을 Single tenant로 지정합니다.
2. **Public client/native** 리디렉션 URI로 `http://localhost:8400/`를 지정하고 등록합니다.
3. Overview의 **Application (client) ID**를 복사하여 `a365.config.json`의 `clientAppId`에 붙여넣습니다.
4. Authentication의 Mobile and desktop 설정에 `http://localhost` 및 `ms-appx-web://Microsoft.AAD.BrokerPlugin/<CLIENT_ID>`도 등록하고, public client 흐름 허용 설정을 적용합니다.
5. API permissions에서 CLI 버전이 요구하는 **Delegated permissions**와 관리자 동의를 설정합니다. 공식 절차는 `AgentIdentityBlueprint.ReadWrite.All`, `AgentIdentityBlueprintPrincipal.Create`, `AgentIdentity.Read.All`, `AgentIdentity.DeleteRestore.All`, `AgentRegistration.ReadWrite.All`, `Application.Read.All`, `User.Read`를 설명합니다. 항목이 포털에 없으면 공식 문서의 Graph 방식으로 설정합니다.
6. Token configuration → Add optional claim에서 Access 토큰의 `wids`를 추가합니다.
7. 아래 `a365 setup requirements`로 도구 앱 설정을 확인합니다. 실제 작업 권한은 로그인한 관리자의 역할에도 달려 있습니다.

[공식 custom client 등록 절차](https://learn.microsoft.com/en-us/microsoft-agent-365/developer/custom-client-app-registration)의 버전별 요구 사항을 함께 확인합니다. 이 구성은 **관리 도구 앱**의 권한이며 자식의 세 가지 런타임 Graph 권한과 별도입니다. 이 CLI 앱에는 로컬 Web 앱의 비밀값을 넣지 않습니다. README의 원시 토큰 방식으로 자식 생성·동의 부여까지 수행하려면 해당 CLI 앱의 사전 동의에 그 작업의 `AgentIdentity.Create.All` 및 `DelegatedPermissionGrant.ReadWrite.All`도 있어야 합니다. 이 문서의 5~7절은 대신 `Connect-MgGraph`에서 각 작업 권한을 명시합니다.

```json
{
  "tenantId": "<ENTRA_TENANT_ID>",
  "clientAppId": "<CLI_CLIENT_APP_ID>",
  "agentIdentityDisplayName": "<EXACT_CHILD_DISPLAY_NAME>",
  "agentBlueprintDisplayName": "<EXACT_BLUEPRINT_DISPLAY_NAME>",
  "aiTeammate": false,
  "useBlueprint": true,
  "authMode": "obo"
}
```

| 항목 · Setting | 실제로 넣을 값 · What to enter |
|---|---|
| `tenantId` | `.env`의 실제 `ENTRA_TENANT_ID`와 동일 |
| `clientAppId` | 위에서 찾거나 만든 CLI 인증 앱의 Application ID |
| `agentIdentityDisplayName` | 사용할 기존 자식의 정확한 표시 이름 |
| `agentBlueprintDisplayName` | 해당 자식의 부모 Blueprint 표시 이름 |
| `aiTeammate` | `false` 유지; 이 앱은 사람 사용자의 OBO 흐름 |
| `useBlueprint` | `true` 유지 |
| `authMode` | `"obo"` 유지 |

**생성 상태 복원:** 공개 저장소에는 실제 `a365.generated.config.json`이 없습니다. [온보딩 문서](onboarding.md)의 복원 절차로 `agentBlueprintId`, `agentBlueprintObjectId`, `agentBlueprintServicePrincipalObjectId`, `agenticAppId`를 실제 값으로 채웁니다. `agentRegistrationId`는 해당 자식의 **이미 존재하는 Agent 365 등록 결과**를 알고 있을 때만 넣습니다. 기존 등록 여부를 모르면 관리자의 등록 기록을 먼저 확인하고 임의의 UUID나 다른 자식의 값을 넣지 않습니다.

```powershell
a365 --version
a365 setup requirements --help
a365 setup requirements
a365 query-entra instance-scopes
```

`a365 setup requirements`는 버전에 따라 도구 앱 설정 변경을 제안할 수 있습니다. `--help` 자체는 사용법만 표시합니다. 설치된 1.1.221 도움말에는 `--yes`가 없으므로 다른 버전 문서의 옵션을 그대로 복사하지 않습니다.

**등록이 필요한 자식에만** 다음을 실행합니다. 등록 전용은 자식 생성이나 권한 부여를 대신하지 않습니다. 이 프로젝트에서 전체 `a365 setup all` 또는 Blueprint 권한 상속 명령을 실행하지 않습니다.

```powershell
a365 setup all --agent-registration-only --dry-run
a365 setup all --agent-registration-only
```

The CLI authentication app is a separate public client. Copy its client ID into `clientAppId`, use exact existing names, and restore generated identity metadata before querying/registering. Do not invent a registration ID or run full setup on a shared blueprint.

## 10. 나머지 .env 항목 · Remaining environment settings

| 항목 · Setting | 무엇을 넣나요? · Value and purpose | 확인 · Verify |
|---|---|---|
| `APP_NAME` | 표시 이름. 기본 `onedrive-purview-agent` 또는 사용할 이름 | 화면의 앱 이름 확인 |
| `REDIRECT_URI` | 기본 `http://localhost:8000/auth/callback` 유지 | 웹 앱의 Web URI와 일치 |
| `EXPECTED_USER` | 특정 테스트 계정의 실제 UPN, 또는 빈칸 | 다른 UPN 제한이 필요한 경우만 설정 |
| `PURVIEW_APP_ID` | 자식 ID, 또는 빈칸으로 자동 기본값 사용 | DLP application location이 같은 자식을 대상 |
| `REQUIRE_INLINE_OUTPUT` | 기본 `false`; `true`는 출력도 inline 검사를 요구 | 정책이 출력 감사만 지원하면 `true`에서 답변 중단 |
| `MAX_FILE_BYTES` | 기본 `131072` = 128 KiB | 초과 파일은 전체 거부 |
| `MAX_TEXT_BYTES` | 기본 `262144` = 256 KiB | `MAX_FILE_BYTES <= MAX_TEXT_BYTES <= 1048576` |
| `TEST_FILE_PATH` | 기본 `test-summary.txt`; 사용자의 OneDrive 루트 기준 경로 | 해당 계정으로 OneDrive에서 파일 확인 |
| `GRAPH_BASE_URL` | 예제에는 없는 선택 항목. 추가하지 않아도 `https://graph.microsoft.com/v1.0` | 이 버전은 global Graph v1.0만 지원 |

파일/텍스트 상한은 애플리케이션의 제한이며 Purview 서비스 상한을 늘리지 않습니다. 파일 전체를 검사할 수 없으면 일부만 검사하지 않고 중단합니다. `TEST_FILE_PATH`는 진단 도구의 대상 파일이며, 일반 채팅의 OneDrive path 입력도 사용자 OneDrive 루트 기준입니다.

These defaults control the local app, not tenant permissions. Keep output enforcement compatible with your policy and use a complete UTF-8 `.txt` test file in the signed-in user's OneDrive.

## 11. 값 입력을 마쳤을 때 · Verify the completed configuration

```powershell
.\.venv\Scripts\python.exe scripts/check_setup.py
```

필수 값이 빠지면 다음처럼 **항목 이름**이 나옵니다. 해당 행을 `.env`에서 채웁니다.

```text
SETUP NEEDED: BLUEPRINT_CLIENT_SECRET, FOUNDRY_ENDPOINT, WEB_CLIENT_ID
```

필수 값이 있으면 다음 문장이 나옵니다.

```text
PASS Required local configuration is present; tenant permissions/policies still need a live test.
```

이 결과는 비밀값 유효성, 사용자 동의, OneDrive 권한, Purview 정책을 증명하지 않습니다. 필요하면 아래 명령으로 **유료일 수 있는 합성 모델 요청 1회**를 실행합니다. OneDrive 문서는 읽지 않습니다.

```powershell
.\.venv\Scripts\python.exe scripts/check_setup.py --check-foundry
```

성공하면 `PASS Foundry connection: completed one synthetic connectivity request.`가 표시됩니다. 그다음 앱을 실행하고 설정한 사용자로 로그인하여 깨끗한 메시지와 테스트 파일을 확인합니다. 정책 대상과 차단 규칙은 [Purview 설정](purview-setup.md), 전체 실행 순서는 [README](../README.md)를 따릅니다.

Local preflight checks presence and format, not authorization or DLP enforcement. The optional Foundry check makes one synthetic model call. Browser sign-in and a real OneDrive/Purview test verify the remaining integration.
