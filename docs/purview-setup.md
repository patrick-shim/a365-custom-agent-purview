# Purview 설정 실습 가이드 / Purview setup walkthrough

**정책을 수정할 권한이 없는 고객:** 이 문서의 생성·변경 명령은 실행하지 않습니다. [제한 환경 실행 안내](restricted-environment.md)에 따라 상위 부서에 **기존 정책의 자식 앱·사용자·활동 적용 여부**를 확인하고, 고객 PC에서 승인된 테스트를 진행합니다. 적용되는 정책이 없거나 offline 감사만 허용되면 로컬 코드로 inline 차단 정책을 만들 수 없습니다. / Customers without policy administration rights verify existing coverage with upstream IT and use the restricted runbook. Policy creation examples below are for authorized policy administrators.

이 문서는 **SIT 선택 → 앱·사용자 범위 지정 → DLP 차단 규칙 → 실제 파일 테스트** 순서로 진행합니다. 한국어 설명 다음에 영어 설명을 함께 제공합니다. 실행 환경과 Agent 365 등록은 [README](../README.md)와 [onboarding](onboarding.md)을 참고하세요.

**English:** Follow the steps to select a sensitive information type (SIT), target the application and user, configure a DLP rule, and verify a real file block. Runtime setup and Agent 365 registration are covered in the linked guides.

**개발 검증 결과:** 자동화 테스트 152개가 통과했으며, 실제 OBO 테스트에서 OneDrive 파일 93바이트 전체를 읽고 Purview의 `restrictAccess / block`을 확인했습니다. 차단 진단의 Foundry 호출은 0회였습니다. 다른 테넌트에서는 아래 설정을 직접 완료해야 합니다. Purview 포털의 이벤트·알림 표시까지 검증한 것은 아닙니다.

**English:** Development validation passed 152 automated tests. A live OBO test inspected all 93 bytes of a fixture, received a Purview content block, and made zero Foundry calls. Configure your own tenant using the steps below. Portal ingestion and alert visibility were not verified.

일반 채팅 앱에서도 깨끗한 질문은 Foundry에서 `READY` 응답을 받았고, 테스트 파일 요약 요청은 파일 단계에서 차단되었습니다. 응답 검사 결과는 offline audit이며, 출력의 inline 차단을 검증했다는 의미는 아닙니다. 환경별 계정·리소스·이벤트 ID는 이 공개 가이드에 포함하지 않습니다.

**English:** The normal app also returned `READY` from Foundry for a clean prompt and blocked a document-summary request at the file stage. Its response check used offline auditing, not verified inline output filtering. Environment-specific account, resource, and event IDs are omitted; local evidence receipts are excluded from Git.

## 1. 어떤 앱 ID와 사용자를 사용할까요? / Choose the app and user

이 OBO 구성에서는 **자식 에이전트 ID**가 Purview 애플리케이션 위치입니다. Blueprint는 인증 흐름과 에이전트의 상위 정의에 사용됩니다. Blueprint ID를 정책에 넣었다고 모든 자식이 자동으로 포함되는 것은 아닙니다. 이 프로젝트는 실제 Graph 보호 범위 응답에 나타난 자식 ID를 `PURVIEW_APP_ID`에도 사용합니다.

**English:** For this verified OBO flow, target the **child agent identity**, which is the application location returned by Graph. The blueprint supports the identity/token flow; it is not a policy wildcard for its children. Keep the policy location and `PURVIEW_APP_ID` aligned.

| 항목 / Item | 입력할 값 또는 예시 / Value to supply or example |
|---|---|
| Tenant | `<tenant-id>` |
| Blueprint | `onedrive-purview-blueprint` — `<blueprint-client-id>` |
| Policy application / child agent | `onedrive-purview-agent` — `<child-agent-id>` |
| Test user | `user@contoso.onmicrosoft.com` — fictional example |
| Test user object ID | `<test-user-object-id>` |
| Existing policy | `<existing-policy-display-name>` |
| Existing policy ID | `<existing-policy-GUID>` — read with `Get-DlpCompliancePolicy` |
| Existing rule | `<existing-rule-display-name>` |
| Existing rule ID | `<existing-rule-GUID>` — read with `Get-DlpComplianceRule` |

아래 값은 모두 예시 또는 입력 자리입니다. 실행 전에 본인 환경의 앱 ID, 이름, 사용자, 정책 ID로 바꿉니다. 앱·사용자 ID는 Entra 관리 센터 또는 onboarding 결과에서 확인합니다. 정책·규칙 ID 조회 방법은 4A에 있습니다. Blueprint나 브라우저 로그인 앱 ID를 `$policyAppId`에 대신 넣지 마세요.

**English:** Replace every placeholder and fictional account before running commands. Obtain app/user IDs from Entra or your onboarding output, and policy/rule IDs from step 4A. Use the child application's verified ID for `$policyAppId`, not the blueprint or browser client.

```powershell
$policyAppId = '<child-agent-id>'
$policyAppName = 'onedrive-purview-agent'
$testUserUpn = 'user@contoso.onmicrosoft.com'          # Replace fictional UPN.
$testUserObjectId = '<test-user-object-id>'
$purviewAdminUpn = 'admin@contoso.onmicrosoft.com'     # Replace fictional UPN.
$existingPolicyId = '<existing-policy-GUID>'
$existingRuleId = '<existing-rule-GUID>'
```

Graph 권한과 DLP 정책 범위는 별개입니다. 이 앱의 자식 에이전트에는 선택된 사용자에 대한 위임 권한 `Files.Read`, `ProtectionScopes.Compute.User`, `Content.Process.User`가 필요합니다. 정책에 앱을 추가해도 OneDrive 읽기 권한은 생기지 않습니다. 해당 권한 설정은 [onboarding 가이드](onboarding.md)에 있습니다.

**English:** Delegated Graph consent and DLP policy targeting are separate. The child needs the three scopes above for this user; adding an application to a policy does not grant file access.

## 2. 기본 Credit Card Number SIT 확인 / Inspect the built-in SIT

**Credit Card Number는 기본 제공 SIT이므로 새로 만들 필요가 없습니다.** 이 실습은 신뢰도 하한 **85**, 최소 일치 개수 **1**을 사용합니다. 기본 SIT은 그대로 두고 DLP 규칙에서 조건을 선택합니다. [기본 SIT 설명 / Built-in SITs](https://learn.microsoft.com/en-us/purview/sit-sensitive-information-type-learn-about)

**English:** Use the existing **Credit Card Number** SIT with minimum confidence **85** and minimum count **1**. No custom classifier is required.

1. [Microsoft Purview 포털](https://purview.microsoft.com)에 해당 테넌트의 관리자 계정으로 로그인합니다.
2. **솔루션 / Solutions → Information Protection → Classifiers → Sensitive info types**에서 `Credit Card Number`를 찾습니다.
3. SIT를 열고 **Test**를 선택합니다. 승인된 테스트 데이터가 있는 파일과 깨끗한 파일을 각각 테스트합니다.
4. 일치 결과와 신뢰도를 확인합니다. 이 테스트는 업로드한 파일의 SIT 인식 확인이며, 이 에이전트의 OBO·DLP 차단 전체 테스트는 6단계에서 별도로 수행합니다. [SIT 테스트 절차 / SIT testing](https://learn.microsoft.com/en-us/purview/sit-test-a-sit)

**English:** Open the same portal path, select the SIT, and use **Test** on a matching fixture and a clean fixture. Check the match/confidence results. This validates classification; the agent's end-to-end enforcement is tested later.

숫자처럼 보이는 문자열이 모두 일치하지는 않습니다. 이 SIT는 카드 형식과 체크섬을 확인하며, 높은 신뢰도는 주변의 카드 관련 단어나 유효기간 등도 사용합니다. 금융기관이 테스트용으로 예약한 카드 번호는 제외될 수 있습니다. 실제 고객 정보를 넣기보다, 조직에서 승인하고 SIT 테스트에서 확인한 테스트 자료를 사용하세요. [Credit card 정의 / Classifier definition](https://learn.microsoft.com/en-us/purview/sit-defn-credit-card-number)

**English:** Arbitrary digits are insufficient. Format, checksum, and nearby supporting context affect detection; reserved test card numbers can be excluded. Use an approved fixture confirmed by the SIT test, not real customer data.

### 선택 사항: 자체 SIT가 필요한 경우 / Optional custom SIT

사내 식별번호처럼 기본 SIT로 다룰 수 없는 값이 있을 때만 **Create sensitive info type**을 사용합니다. 이름·설명 → 기본 탐지 요소(패턴/키워드) → 보조 요소와 근접 범위 → 신뢰도 순으로 정의한 뒤, 일치·불일치 파일을 모두 테스트합니다. 해당 SIT 이름을 새 DLP 규칙의 `Name`에 사용하면 됩니다. 기존 공유 규칙의 SIT 목록을 덮어쓰지는 마세요. [사용자 지정 SIT 만들기 / Create a custom SIT](https://learn.microsoft.com/en-us/purview/create-a-custom-sensitive-information-type)

**English:** Create a custom SIT only for requirements the built-in classifiers do not cover. Define its primary pattern, supporting evidence/proximity, and confidence; test positive and negative fixtures. Reference its name in the new rule. Preserve existing shared rules.

## 3. 관리자 PowerShell 연결 / Connect administrative PowerShell

이 단계는 Python 가상환경과 별도의 **PowerShell 7** 창에서 실행합니다. Purview 정책을 관리할 권한이 있는 계정과 테넌트의 라이선스·사용량 청구 설정이 준비되어 있어야 합니다. [Purview 통합 전제 조건 / Integration prerequisites](https://learn.microsoft.com/en-us/agent-framework/integrations/use-purview-with-agent-framework-sdk)

**English:** Use PowerShell 7 separately from the Python venv, with an authorized Purview administrator and the required tenant licensing/billing configuration.

```powershell
# Install once if the module is not installed.
Install-Module ExchangeOnlineManagement -Scope CurrentUser
Import-Module ExchangeOnlineManagement
Connect-IPPSSession -UserPrincipalName $purviewAdminUpn -ShowBanner:$false

# Read-only checks. They do not display credentials or tokens.
Get-Command Get-DlpCompliancePolicy, Set-DlpCompliancePolicy,
    New-DlpCompliancePolicy, New-DlpComplianceRule |
    Select-Object Name
Get-DlpSensitiveInformationType -Identity 'Credit Card Number' |
    Select-Object Name, Identity, RecommendedConfidence
```

로그인 창에서 인증을 완료합니다. 필요한 명령이 보이지 않으면 먼저 관리자 역할과 연결한 테넌트를 확인합니다. 스크립트에 암호나 액세스 토큰을 넣지 않습니다. [연결 방법 / Connection](https://learn.microsoft.com/en-us/powershell/exchange/connect-to-scc-powershell?view=exchange-ps), [SIT 조회 / SIT lookup](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/get-dlpsensitiveinformationtype?view=exchange-ps)

**English:** Complete interactive sign-in. Missing commands can indicate insufficient roles or the wrong session/tenant. No password, secret, or token is needed in these scripts.

## 4A. 기존 정책을 사용하는 경우 / Reuse an existing policy

기존 앱 DLP 정책을 재사용한다면 다른 앱·사용자 범위와 규칙을 유지하면서 필요한 자식 앱·테스트 사용자만 추가합니다. 먼저 읽기 전용으로 정책과 규칙을 조회하고, 사용할 ID를 선택하세요. 적합한 기존 정책이 없으면 4B로 이동합니다.

**English:** Preserve existing applications, user scopes, and rules when reusing a policy. List the policies and rules below, then select their exact IDs. If no suitable policy exists, use step 4B.

```powershell
Get-DlpCompliancePolicy | Select-Object Name, Guid, Mode, EnforcementPlanes
$existingPolicyId = '<paste-selected-policy-GUID>'
Get-DlpComplianceRule -Policy $existingPolicyId | Select-Object Name, Guid, Disabled
$existingRuleId = '<paste-selected-rule-GUID>'
```

```powershell
$existingPolicy = Get-DlpCompliancePolicy -Identity $existingPolicyId
$existingPolicy | Select-Object Name, Guid, Mode, EnforcementPlanes
$beforeLocations = @($existingPolicy.Locations | ConvertFrom-Json)
$beforeLocations | Where-Object Location -eq $policyAppId |
    ConvertTo-Json -Depth 15
Get-DlpComplianceRule -Identity $existingRuleId |
    Select-Object Name, Disabled, RestrictAccess, ContentContainsSensitiveInformation |
    ConvertTo-Json -Depth 15
```

확인할 값은 `Mode=Enable`, `EnforcementPlanes=Application`, 선택한 앱/사용자 포함, 규칙 `Disabled=false`, Credit Card Number의 `minconfidence=85`·`mincount=1`, `UploadText=Block`입니다. 공유 규칙에 다른 SIT가 들어 있다면 그대로 유지합니다.

**English:** Verify the enabled Application policy, selected app/user inclusion, enabled rule, credit-card threshold 85/count 1, and `UploadText=Block`. The shared rule also contains other SITs; preserve them.

다른 자식 앱·사용자를 이 정책에 추가할 때만 아래 예제를 사용합니다. **`Set-... -Locations`는 `AddInclusions` 델타를 사용합니다.** 기존 위치 전체를 생성용 `Inclusions` JSON으로 다시 보내지 않습니다. [위치 수정 규격 / Location update contract](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/set-dlpcompliancepolicy?view=exchange-ps#-locations)

**English:** For a future addition, send only an `AddInclusions` delta. Do not replace the shared policy with a creation-style `Inclusions` snapshot.

```powershell
$applyExistingChange = $false # Preview first; change to $true only to apply.
$existingPolicy = Get-DlpCompliancePolicy -Identity $existingPolicyId
if ([string]$existingPolicy.Guid -ne $existingPolicyId -or
    $existingPolicy.Mode -ne 'Enable' -or
    $existingPolicy.EnforcementPlanes -notcontains 'Application') {
    throw 'Review the selected policy identity, mode, and enforcement plane.'
}
$beforeLocations = @($existingPolicy.Locations | ConvertFrom-Json)
$target = @($beforeLocations | Where-Object Location -eq $policyAppId)
if ($target.Count -gt 1) { throw 'Multiple matching locations require review.' }
$alreadyIncluded = @($target.Inclusions | Where-Object {
    $_.Type -eq 'IndividualResource' -and
    $_.Identity -in @($testUserUpn, $testUserObjectId)
}).Count -gt 0
if (@($target.Inclusions | Where-Object Type -eq 'Tenant').Count -gt 0) {
    throw 'This application already has tenant-wide inclusion. Review its scope first.'
}
$locationDelta = @(@{
    Workload = 'Applications'; Location = $policyAppId
    LocationDisplayName = $policyAppName
    LocationSource = 'Entra'; LocationType = 'Individual'
    AddInclusions = @(@{ Type = 'IndividualResource'; Identity = $testUserUpn })
})
$deltaJson = ConvertTo-Json -InputObject $locationDelta -Depth 15 -Compress
[pscustomobject]@{
    PolicyId = $existingPolicyId; Application = $policyAppId
    User = $testUserUpn; AlreadyIncluded = $alreadyIncluded
    Apply = $applyExistingChange; Delta = $deltaJson
} | Format-List

if ($applyExistingChange -and -not $alreadyIncluded) {
    Set-DlpCompliancePolicy -Identity $existingPolicyId -Locations $deltaJson
    $updatedPolicy = Get-DlpCompliancePolicy -Identity $existingPolicyId
    $updatedLocations = @($updatedPolicy.Locations | ConvertFrom-Json)
    $updatedLocations | Where-Object Location -eq $policyAppId |
        ConvertTo-Json -Depth 15
    foreach ($previous in $beforeLocations | Where-Object Location -ne $policyAppId) {
        $preserved = @($updatedLocations | Where-Object Location -eq $previous.Location)
        if ($preserved.Count -ne 1 -or
            ($preserved[0] | ConvertTo-Json -Depth 15 -Compress) -ne
            ($previous | ConvertTo-Json -Depth 15 -Compress)) {
            throw 'An existing location differs from readback. Review; do not overwrite it.'
        }
    }
}
```

위 코드는 `$applyExistingChange=$false`일 때 계획만 표시합니다. 현재 앱·사용자가 이미 있으면 중복 적용하지 않습니다. `-WhatIf`만 믿고 실행하지 마세요. Security & Compliance PowerShell에서는 이 스위치가 동작하지 않는다고 명시되어 있어, 이 가이드는 명시적인 적용 변수로 쓰기 명령을 분리합니다. [WhatIf 제한 / WhatIf limitation](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancerule?view=exchange-ps#-whatif)

**English:** The default flag prints a plan without executing a write. Existing inclusion is detected. `-WhatIf` is not a reliable preview for these Security & Compliance cmdlets; use the explicit apply guard.

## 4B. 별도 환경: 새 정책과 규칙 만들기 / Create a new policy elsewhere

이 단계는 **기존 정책을 재사용하지 않을 때만** 선택합니다. Entra 등록 앱을 위한 DLP 규칙은 현재 Microsoft 안내에 따라 PowerShell로 생성합니다. 일반 DLP 포털 마법사를 사용하는 것만으로 이 앱 대상 규칙이 만들어졌다고 판단하지 않습니다. [Entra 앱 DLP 설정 / App-policy guidance](https://learn.microsoft.com/en-us/purview/developer/use-the-api)

**English:** Use this alternative only when a separate policy is needed. Current Microsoft guidance requires PowerShell for Entra-registered application DLP rules; do not assume a generic portal-created policy covers this app.

생성용 JSON은 `Inclusions`를 사용합니다. 아래 예제는 해당 사용자 1명만 포함하고, 비활성 정책을 만든 후 규칙 생성이 성공하면 활성화합니다. 새 이름을 사용하며 기존 정책을 수정하지 않습니다. [정책 생성 / Policy creation](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancepolicy?view=exchange-ps#-locations)

**English:** Creation uses `Inclusions`. This example targets one user, creates the policy disabled, creates its rule, then enables it. Choose unused names.

```powershell
$applyNewPolicy = $false # Preview first; set $true to create after review.
$newPolicyName = 'OneDrive Agent Credit Card DLP'
$newRuleName = 'OneDrive Agent - Block Credit Card UploadText'
$newLocations = @(@{
    Workload = 'Applications'; Location = $policyAppId
    LocationDisplayName = $policyAppName
    LocationSource = 'Entra'; LocationType = 'Individual'
    Inclusions = @(@{ Type = 'IndividualResource'; Identity = $testUserUpn })
})
$newLocationsJson = ConvertTo-Json -InputObject $newLocations -Depth 15 -Compress
$cardCondition = @(@{
    Name = 'Credit Card Number'
    minConfidence = '85'; maxConfidence = '100'
    minCount = '1'; maxCount = '-1'
})
$uploadBlock = @(@{ setting = 'UploadText'; value = 'Block' })
[pscustomobject]@{
    Policy = $newPolicyName; Rule = $newRuleName; Apply = $applyNewPolicy
    Locations = $newLocations; Condition = $cardCondition; Action = $uploadBlock
} | ConvertTo-Json -Depth 15

if ($applyNewPolicy) {
    $ErrorActionPreference = 'Stop'
    if (Get-DlpCompliancePolicy -Identity $newPolicyName -ErrorAction SilentlyContinue) {
        throw 'The policy exists. Inspect it or choose a new name.'
    }
    New-DlpCompliancePolicy -Name $newPolicyName -Mode Disable `
        -Locations $newLocationsJson -EnforcementPlanes @('Application')
    New-DlpComplianceRule -Name $newRuleName -Policy $newPolicyName `
        -Disabled:$false -ContentContainsSensitiveInformation $cardCondition `
        -RestrictAccess $uploadBlock
    Get-DlpComplianceRule -Identity $newRuleName |
        Select-Object Name, Disabled, RestrictAccess, ContentContainsSensitiveInformation |
        ConvertTo-Json -Depth 15
    Set-DlpCompliancePolicy -Identity $newPolicyName -Mode Enable
    Get-DlpCompliancePolicy -Identity $newPolicyName |
        Select-Object Name, Guid, Mode, EnforcementPlanes, Locations |
        ConvertTo-Json -Depth 15
}
```

이 규칙은 신용카드 SIT 1개 이상이 신뢰도 85 이상으로 일치하면 `UploadText`를 차단합니다. `maxCount=-1`은 개수 상한을 지정하지 않는 설정입니다. 이 샘플은 알림 수신자나 메일 발송 규칙을 추가하지 않습니다. 필요한 알림 경로는 운영자가 별도로 설정합니다. [Entra 앱 규칙 예제와 조건 문법 / Application rule and conditions](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancerule?view=exchange-ps#examples)

**English:** The rule blocks UploadText when at least one credit-card match reaches confidence 85; count has no upper limit. Alert recipients and notifications are separate operational settings.

## 5. 포털에서 보이는 설정 확인 / Check portal visibility

정책·규칙 생성 후 **Purview → DSPM → Collection policies**에서 대상 정책의 표시와 활성 상태를 확인합니다. 테넌트 UI에서 **Solutions → Data Loss Prevention → Policies**가 제공되면 같은 정책 이름으로 조회할 수 있습니다. 메뉴 표시가 달라도 PowerShell의 정책 ID·규칙·위치 readback과 실제 Graph 보호 범위를 함께 기준으로 삼습니다. `evaluateOffline`만 반환되면 앱 대상 DLP 규칙이 올바르게 만들어지고 활성화되었는지 확인합니다. [범위와 실행 모드 확인 / Scope and execution-mode guidance](https://learn.microsoft.com/en-us/purview/developer/use-the-api)

**English:** Check the enabled policy in **DSPM → Collection policies** and, where available, **Data Loss Prevention → Policies**. Use the PowerShell readback and live Graph scope as well as the UI. An offline-only scope is insufficient for this project's input blocking.

Audit와 AI 상호작용 수집은 별도 설정입니다. 필요하면 DSPM의 Audit 및 enterprise AI app 수집 설정을 확인합니다. 수집 기능은 제출한 콘텐츠를 보존할 수 있으며, 차단 응답 1건이 모든 포털 화면이나 경고에 즉시 표시된다고 보장하지 않습니다. [수집·감사 설정 / Collection and auditing](https://learn.microsoft.com/en-us/purview/developer/configurepurview)

**English:** Audit and AI-interaction collection require their own configuration and can retain submitted content. A block response does not prove immediate ingestion into every portal view or generation of an alert.

## 6. OneDrive 전체 파일 차단 테스트 / Test complete-file blocking

이 앱은 OneDrive의 **UTF-8 TXT 전체 내용**을 `processContent`의 **`uploadText`**로 보냅니다. OneDrive 링크만 보내거나 `uploadFile`로 보내는 구현이 아닙니다. 따라서 규칙은 **`UploadText=Block`**이어야 합니다. 파일 크기 제한을 넘으면 일부만 잘라서 허용하지 않고 중단합니다.

**English:** The agent downloads the complete UTF-8 TXT and submits its text as `uploadText`. An uploadFile-only rule will not cover this implementation. Oversized or unsupported files stop rather than being truncated.

`.env`의 ID가 1단계와 일치하는지 확인합니다. 이 파일의 전체 내용이나 비밀 값을 출력할 필요는 없습니다.

**English:** Check these non-secret settings in `.env`; do not print or share the complete file.

```dotenv
PURVIEW_APP_ID=<child-agent-id>
AGENT_IDENTITY_ID=<child-agent-id>
BLUEPRINT_CLIENT_ID=<blueprint-client-id>
EXPECTED_USER=user@contoso.onmicrosoft.com
TEST_FILE_PATH=test-summary.txt
```

1. 선택한 사용자의 OneDrive 루트에 승인된 SIT 테스트 파일 `test-summary.txt`를 둡니다. 동기화 폴더 이름은 보통 `OneDrive - <organization>` 형태이며 환경에 따라 다릅니다. 동기화가 끝나야 Graph에서 읽을 수 있습니다.
2. 일반 앱이 실행 중이면 종료한 후, 프로젝트 폴더의 venv에서 아래 진단 서버를 실행합니다.
3. [localhost:8000](http://localhost:8000)에서 같은 사용자로 로그인하고 메시지를 보냅니다. 진단 모드는 고정된 안전한 프롬프트와 `TEST_FILE_PATH`를 사용하며, Foundry를 호출하지 않습니다.
4. 결과에서 파일 읽기 성공, `file_content_policy_block`, `content_block_confirmed=true`, `foundry_http_calls=0`을 확인합니다.

**English:** Put the approved fixture in the selected user's OneDrive root and wait for sync. Stop the normal app, start the diagnostic below, sign in, and send a message. Verify the content-block result and zero model calls.

```powershell
.\.venv\Scripts\python.exe scripts\check_onedrive_purview.py --mode pipeline
```

일반 채팅도 확인하려면 진단 서버를 종료하고 아래 앱을 실행합니다. 깨끗한 질문은 **OneDrive 경로를 비워서** 테스트하고, 파일 차단은 경로에 `test-summary.txt`를 넣어 테스트합니다. 명시적 파일 경로가 있으면 파일 검사가 첫 Foundry 호출보다 먼저 실행됩니다.

**English:** For normal chat, stop the probe and start the app. Leave the OneDrive path empty for a clean prompt, then specify the fixture path for the block test. An explicit path makes file inspection run before the first Foundry call.

```powershell
.\.venv\Scripts\python.exe app.py
```

## 7. 결과와 로그 읽기 / Interpret the results

| 결과 / Result | 의미와 다음 확인 / Meaning and next check |
|---|---|
| `file_content_policy_block` | 실제 파일 텍스트에 대한 Purview 차단. / Actual content restriction on the file text. |
| `file_scope_policy_block` | 사용자·앱 범위 자체의 제한. SIT 탐지 증명은 아님. / Scope restriction; does not establish a content match. |
| `missing_policy_scope` | 앱·사용자·활동 범위에 맞는 정책이 없음. / No applicable app/user/activity scope. |
| `inline_policy_required` | 입력 보호가 offline뿐이거나 inline 범위가 없음. / Input does not have required inline protection. |
| HTTP 400 / `process_http_error` | 요청·스키마·서비스 오류. SIT 차단 성공으로 세지 않음. / Request/service failure, not a successful SIT block. |
| HTTP 401/403 | 로그인·위임 동의·권한 확인. / Check sign-in and delegated authorization. |
| `file_content_permitted` | 해당 정책이 이 콘텐츠를 허용함. SIT 테스트·신뢰도·범위를 확인. / No block for this content; verify the fixture and policy conditions. |

로컬 `logs/policy-decisions.jsonl`에는 원문·토큰 대신 단계, 결과, 참조 ID 등 결정 메타데이터가 기록됩니다. 진단 결과는 `.local/live-probe.jsonl`에 저장됩니다. `correlation_id`로 같은 실행을 연결하고, Purview 포털에서는 해당 사용자·앱·UTC 시간대와 정책을 함께 확인하세요. 파일 내용 일치 여부와 정확한 SIT·규칙은 포털에서 해당 이벤트를 확인해야 확정할 수 있습니다.

**English:** Correlate local decision metadata using `correlation_id`; the diagnostic evidence is in `.local/live-probe.jsonl`. Match the user, app, UTC time, and policy in Purview. The Graph block response alone does not identify the exact matched SIT/rule or prove portal ingestion.

관리자 설정 작업이 끝났으면 세션을 종료합니다.

**English:** Disconnect the administrative session when finished.

```powershell
Disconnect-ExchangeOnline -Confirm:$false
```
