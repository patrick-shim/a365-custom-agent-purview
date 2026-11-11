# 공식 가이드 기반 새 DLP 정책 만들기 · New DLP policy script

**상위 부서의 Purview 정책 담당자가 사용하는 설정 예제입니다.** 고객 PC의 Python 실행에 필요한 파일은 아닙니다. 기존 `.local/include_demo_in_dlp.ps1`와 Python 에이전트 코드는 변경하지 않습니다. 기존 정책을 그대로 쓸 수 있다면 새 정책을 만들 필요도 없습니다.

사용자가 전달한 예제를 출발점으로 [Microsoft Purview 구성 안내](https://learn.microsoft.com/en-us/purview/developer/configurepurview)와 [New-DlpComplianceRule의 Entra 앱 예제](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancerule?view=exchange-ps#example-4)를 확인하여 작성했습니다. **Microsoft가 배포한 원본 스크립트가 아니라, 공식 가이드를 참고한 이 프로젝트의 예제**입니다.

**English:** This administrator-only sample adapts the supplied example using Microsoft Learn's custom-app guidance. It is a project-maintained adaptation, not an original Microsoft-distributed script. Existing runtime code and the local demo inclusion script remain unchanged. Reuse an approved existing policy when possible.

## 1. 파일과 처리 범위 · Files and behavior

| 파일 · File | 용도 · Purpose |
|---|---|
| [new_purview_app_policy.ps1](../scripts/new_purview_app_policy.ps1) | 설정 검사·미리보기, 또는 명시적으로 선택한 새 정책 생성 / Validate, preview, or explicitly create a new policy |
| [purview_app_policy.example.psd1](../scripts/purview_app_policy.example.psd1) | 이름·앱·사용자·SIT·알림을 입력하는 설정 예제 / Editable configuration template |
| `.local/purview-app-policy.psd1` | 위 예제를 복사한 고객 환경 설정. Git 제외 / Local configuration, ignored by Git |

이 스크립트는 **새 정책과 새 규칙만 생성**합니다. 같은 이름의 정책이나 규칙이 이미 있으면 중단하며, 기존 정책의 위치·SIT·규칙을 덮어쓰지 않습니다. 기존 정책 대상에 앱·사용자를 추가하는 작업은 [기존 정책 안내의 4A절](purview-setup.md)을 사용합니다.

실제 적용 순서는 **기존 이름·SIT 확인 → 정책을 Disable로 생성 → 규칙 생성 → 조회 확인 → 지정한 Mode 적용**입니다. 규칙 생성이나 활성화 전 검증에 실패하면 자동 삭제하지 않습니다. 부분 생성된 비활성 정책을 담당자가 확인해야 하므로 이름을 바꾸어 무조건 다시 실행하지 않습니다.

**English:** Creation only; existing names stop the run. The policy starts disabled, receives its rule, is read back, then receives the requested mode. Failures are not silently retried or cleaned up. Readback does not prove service propagation, inline evaluation, or portal alert delivery.

## 2. 어디서 실행하나요? · Execution environment

- 상위 부서가 승인한 **Windows 관리 PC**를 사용합니다. 최신 `ExchangeOnlineManagement` 3.10.0 이상을 설치한다면 **PowerShell 7.6 이상**이 필요합니다. 승인된 기존 모듈을 쓰는 경우 [공식 버전 호환표](https://learn.microsoft.com/en-us/powershell/exchange/exchange-online-powershell-v2?view=exchange-ps#supported-operating-systems-for-the-exchange-online-powershell-module)를 먼저 확인합니다.
- 실제 적용에는 `ExchangeOnlineManagement` 모듈, Security & Compliance 연결, 해당 정책을 관리할 권한이 필요합니다.
- 고객의 실행 PC에 .NET/a365 CLI나 관리 모듈을 설치할 필요는 없습니다.
- **기본 미리보기는 로그인·모듈 설치·정책 조회·정책 변경을 하지 않습니다.** 오프라인 미리보기만 사용할 때는 PowerShell 7.0 이상이면 됩니다.

**English:** Use an approved Windows administrative machine. ExchangeOnlineManagement 3.10.0+ requires PowerShell 7.6+. Apply requires an authorized Security & Compliance session. Offline preview needs PowerShell 7.0+ but no Exchange module or tenant connection. This tool does not install software or create Entra consent.

## 3. 설정 파일 복사 · Copy configuration

프로젝트 폴더에서 실행합니다. 기존 설정 파일은 덮어쓰지 않습니다.

```powershell
New-Item -ItemType Directory -Path .local -Force | Out-Null
if (-not (Test-Path -LiteralPath .local/purview-app-policy.psd1)) {
    Copy-Item -LiteralPath scripts/purview_app_policy.example.psd1 -Destination .local/purview-app-policy.psd1
}
notepad .local/purview-app-policy.psd1
```

`.psd1`은 PowerShell 데이터 파일입니다. 예제의 따옴표·괄호 구조를 유지하고 `<...>` 자리만 실제 값으로 바꿉니다. **Secret·API Key·비밀번호는 이 설정에 필요하지 않습니다.**

## 4. 어떤 값을 바꾸나요? · Fill in these values

| 설정 · Setting | 입력할 값과 찾는 곳 · What to enter |
|---|---|
| `PolicyName` | 새 정책에 붙일 고유한 이름. 기존 공유 정책의 이름을 넣지 않습니다. |
| `RuleName` | 새 규칙에 붙일 고유한 이름. 기존 규칙 이름을 재사용하지 않습니다. |
| `Applications[].AppId` | 정책이 보호할 실제 앱 ID. **이 저장소의 OBO 데모는 `.env`의 `PURVIEW_APP_ID`, 즉 테스트한 자식 Agent ID**와 맞춥니다. Blueprint ID나 웹 로그인 앱 ID를 대신 넣지 않습니다. 일반 Entra 앱은 해당 앱의 Application/Client ID를 사용합니다. |
| `Applications[].AppName` | 해당 앱의 알아보기 쉬운 표시 이름. 여러 앱은 같은 형식의 항목을 추가합니다. |
| `TestUsers` | 정책에 포함할 사용자별 `Upn`과 `ObjectId`를 입력합니다. 아래 예제를 참고합니다. |
| `AllUsers` | 기본 `$false`. 전사 범위가 승인된 경우에만 `$true`로 하고 `TestUsers=@()`로 비웁니다. 두 범위를 동시에 지정하지 않습니다. |
| `Mode` | 파일 차단 검증은 `Enable`. 아래 모드 차이를 먼저 확인합니다. |
| `SensitiveTypes` | 기본 `Credit Card Number`. 실제 테넌트의 정확한 SIT 이름 또는 ID와 일치 조건을 사용합니다. |
| `MinConfidence` / `MaxConfidence` | 예제는 85 / 100. 고객 정책의 승인된 범위로 조정합니다. |
| `MinCount` / `MaxCount` | 예제는 1 / -1. 최소 1개이며 -1은 개수 상한 없음입니다. |
| `AlertRecipients`, `IncidentRecipients`, `NotifyRecipients` | 기본 빈 배열이며 알림 액션을 추가하지 않습니다. 별도 승인한 수신자가 있을 때만 실제 이메일 주소를 넣습니다. |
| `IncidentReportContent` | 사건 보고서를 설정했을 때 포함할 항목. 기본은 규칙·서비스·심각도·제목이며 내용 원문을 추가하지 않습니다. `Default` 또는 `All`을 사용하면 다른 값과 섞지 않습니다. |
| `ReportSeverityLevel` | `Low`, `Medium`, `High` 중 선택합니다. 예제는 `High`입니다. |

정책의 테스트 사용자와 에이전트에 로그인하는 사용자를 맞춥니다. **정책에 사용자를 포함해도 Graph 위임 동의나 OneDrive 접근 권한이 생기는 것은 아닙니다.** 신원·동의는 [환경값 안내](environment-values.md)의 별도 준비 사항입니다.

사용자 정보는 고객 테넌트의 **Microsoft Entra 관리 센터 → ID → 사용자 → 모든 사용자 → 테스트 사용자 → 개요/속성**에서 확인합니다. 화면에서 **사용자 계정 이름(User principal name)**과 **개체 ID(Object ID)**를 복사합니다. 조회 권한이 없다면 상위 부서에 같은 사용자의 두 값을 요청합니다. 앱의 Object ID나 Tenant ID를 넣으면 안 됩니다.

```text
TestUsers = @(
    @{
        Upn = '<테스트 사용자의 User principal name>'
        ObjectId = '<같은 사용자의 Object ID>'
    }
)
```

이 블록은 설정 파일 안의 `TestUsers`를 바꾸는 예제입니다. 명령창에서 따로 실행하지 않습니다. 여러 사용자가 필요하면 같은 형식의 `@{ ... }` 항목을 추가합니다. 실제 테넌트에서 UPN으로 제출한 사용자가 조회 시 Object ID로 반환되는 경우를 확인했으므로, 두 값을 함께 사용하여 승인된 사용자 범위인지 검증합니다. 다른 사용자 ID나 넓어진 범위가 반환되면 활성화 전에 중단합니다. 입력한 두 값이 같은 사용자를 가리키는지는 관리자가 Entra에서 확인해야 합니다.

SIT의 이름은 [Get-DlpSensitiveInformationType](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/get-dlpsensitiveinformationtype?view=exchange-ps)으로 확인합니다. `Passport Number`처럼 국가를 구분하지 않은 이름이나 `IBAN` 같은 약어가 테넌트의 실제 SIT 이름이라고 가정하지 않습니다. 적용 단계에서 모든 SIT를 먼저 조회하며 찾지 못하면 정책 생성 전에 중단합니다.

**English:** Fill unused policy/rule names, actual protected app IDs, and exact tenant SIT names/IDs. For each test user, copy both the User principal name and Object ID from Entra → Users → All users → the user's overview/properties. The service may return an Object ID for a submitted UPN, so both are used to check scope. Administrators must verify that each pair belongs to the same user. The demo's application location is the child Agent ID. Scope is user-limited by default; tenant-wide scope requires an explicit configuration choice. No credentials belong in this data file.

### 미리보기와 시뮬레이션은 다릅니다 · Preview versus simulation

| 선택 · Choice | 실제 정책 변경 · Cloud change | 차단 여부 · Enforcement |
|---|---|---|
| 스크립트에서 `-Apply` 생략 | 없음. 로컬 계획만 표시 | 테스트·차단하지 않음 |
| `-Apply`, `Mode='Enable'` | 정책과 규칙 생성 | 정책 조건·범위 및 실제 API 판정에 따라 집행 |
| `-Apply`, `Mode='TestWithoutNotifications'` | 정책과 규칙 생성 | 시뮬레이션. 차단·알림 없음 |
| `-Apply`, `Mode='TestWithNotifications'` | 정책과 규칙 생성 | 시뮬레이션. 차단 없이 구성한 알림 사용 |
| `-Apply`, `Mode='Disable'` | 정책과 규칙 생성 | 비활성 상태로 유지 |

시뮬레이션은 `RestrictAccess`의 값을 `Audit`로 바꾸는 기능이 아닙니다. 이 프로젝트는 입력의 inline 보호가 없으면 중단하므로, **시뮬레이션 정책으로 일반 채팅이 정상 동작하거나 파일 차단이 성공한다고 보장하지 않습니다.** [공식 Mode 정의](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancepolicy?view=exchange-ps#-mode)

## 5. 먼저 오프라인 미리보기 · Offline preview

```powershell
.\scripts\new_purview_app_policy.ps1 -ConfigPath .\.local\purview-app-policy.psd1
```

앱·사용자·SIT·모드·알림 계획을 확인합니다. 자리표시자나 잘못된 값이 있으면 고치고 다시 실행합니다. 미리보기는 **실제 테넌트의 SIT 존재 여부나 관리자 권한까지 검사하지 않습니다.**

Security & Compliance PowerShell에서는 `-WhatIf`가 작동하지 않는다고 명시되어 있습니다. 이 예제는 자체 `-Apply` 분기로 쓰기 경로를 구분합니다. 미리보기에 `-Apply`를 붙이지 마세요. [WhatIf 제한](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancerule?view=exchange-ps#-whatif)

## 6. 승인된 관리 세션에서 적용 · Apply from an approved session

이 단계는 **새 정책 생성을 맡은 담당자만**, 올바른 고객 테넌트의 관리 세션에서 수행합니다. 아래 첫 설치 명령은 모듈이 없고 설치가 승인된 경우에만 사용합니다.

```powershell
# Only if the module is absent and installation is approved.
Install-Module ExchangeOnlineManagement -Scope CurrentUser
Import-Module ExchangeOnlineManagement
Connect-IPPSSession -UserPrincipalName '<고객 테넌트의 정책 관리자 UPN>' -ShowBanner:$false
```

브라우저 로그인에서 계정·테넌트를 확인합니다. 스크립트가 고객 테넌트를 자동 선택하거나 권한을 부여하는 것은 아닙니다. 이미 올바르게 연결된 승인된 관리 세션이 있다면 다시 연결하지 않아도 됩니다. [공식 연결 절차](https://learn.microsoft.com/en-us/powershell/exchange/connect-to-scc-powershell)

미리보기와 같은 설정 파일로 적용합니다.

```powershell
.\scripts\new_purview_app_policy.ps1 -ConfigPath .\.local\purview-app-policy.psd1 -Apply
```

동일 이름이 있다는 오류가 나면 기존 정책을 검토하거나 승인된 새 이름을 사용합니다. 조회 권한 오류를 “정책 없음”으로 간주하지 않습니다. 중간 실패 뒤에는 정책/규칙의 실제 상태부터 확인합니다. 이전 실행에서 생성한 정책을 다시 실행하여 수정하거나 삭제하는 기능은 없습니다.

새 정책의 활성화 시도 이후 검증에 실패하면, **이번 실행에서 만든 정책에만** Disable 요청을 보냅니다. 이 요청도 실패할 수 있으므로 오류 안내가 나오면 담당자가 실제 상태를 확인해야 합니다.

**English:** Apply only from an already authorized session for the intended tenant. The script neither connects automatically nor grants access. Existing names, failed discovery, unknown SITs, or readback mismatches stop the operation. If verification fails after activation is attempted, the script requests Disable for this run's new policy only. Administrators must verify the actual state before retrying.

## 7. 실제 차단 확인 · Verify real enforcement

관리 명령의 성공만으로 검증이 끝나지는 않습니다. [기존 파일 차단 테스트](purview-setup.md)를 따라 깨끗한 TXT와 승인된 SIT 테스트 TXT를 각각 검사합니다.

- 해당 사용자·자식 앱·`uploadText`에 대한 inline 보호 범위가 있어야 합니다.
- 민감 파일은 전체 파일 검사와 `file_content_policy_block`, `content_block_confirmed=true`, `model_boundary_reached=false`를 함께 확인합니다.
- 진단 프로그램은 원래 Foundry를 호출하지 않으므로 `foundry_http_calls=0`만으로 차단 성공을 판단하지 않습니다.
- 정확한 SIT/규칙, Audit 기록, 알림 전달은 담당자가 별도로 확인합니다.

**이 새 정책 스크립트는 응답 내용의 inline 차단을 구현하거나 보장하지 않습니다.** 현재 Python 앱의 응답 평가는 audit-only일 수 있습니다. 질문과 파일의 입력 차단 범위가 이번 설정의 기준입니다.

Audit·KYD/enterprise-app 수집과 Communication Compliance·Insider Risk 등의 구성은 DLP 규칙 생성과 별개입니다. 이 스크립트는 해당 기능을 자동 활성화하지 않습니다. 필요한 솔루션만 상위 부서의 정책에 따라 [공식 구성 안내](https://learn.microsoft.com/en-us/purview/developer/configurepurview)에서 확인합니다.

**English:** Validate the actual protected-user/app/activity path, full-file verdict, and model boundary. Policy creation alone is not proof of runtime enforcement or event delivery. This script does not establish inline response blocking or turn on other Purview solutions automatically.

## 8. 전달받은 예제와 달라진 점 · Adaptation notes

| 첨부 예제 · Supplied sample | 이 프로젝트의 선택 · Adaptation |
|---|---|
| `UploadText`와 `DownloadText`를 모두 `Block/Audit`로 지정 | 공식 Entra 앱 예제에서 확인되는 **`UploadText=Block`**만 제공합니다. 다른 조합은 공식 지원을 확인하지 못했으며 불가능하다고 단정하지도 않습니다. |
| 이름이 있으면 정책·규칙 자동 갱신 | **새 이름만 생성**합니다. 기존 정책 수정의 `Locations`는 `AddInclusions` 등 별도 규격이므로 생성용 JSON을 재사용하지 않습니다. |
| 앱을 Tenant All로 적용 | 명시적 테스트 사용자 목록이 기본이며 전사 범위는 별도 선택입니다. |
| 여러 SIT 이름을 미리 나열 | Credit Card Number 하나부터 시작하고 실제 테넌트의 이름/ID를 조회합니다. |
| `SiteAdmin`을 테넌트 준수 관리자로 설명 | 그 의미로 단정하지 않습니다. 기본 알림은 비워 두고 승인된 실제 수신자를 지정합니다. |
| `IncidentReportContent`에 `Default`와 여러 값을 혼합 | `Default`는 추가 항목을 무시하므로 단독으로 사용하거나 명시적 항목 목록을 사용합니다. |
| `StopPolicyProcessing=$true` | `$false`로 설정하여 이후 규칙 평가를 중단하지 않습니다. |

위 비교는 첨부 예제의 취지를 유지하면서 확인 가능한 명령 규격과 현재 POC의 입력 차단 범위에 맞춘 것입니다. [기존 정책 Locations 수정](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/set-dlpcompliancepolicy?view=exchange-ps#-locations), [보고서 필드 규칙](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancerule?view=exchange-ps#-incidentreportcontent)

설정이 끝나면 사용한 관리 세션을 종료합니다.

```powershell
Disconnect-ExchangeOnline -Confirm:$false
```

## 9. 이 저장소에서 확인한 범위 · Validation scope

테스트는 실제 Microsoft 365 테넌트 대신 로컬 모의 함수를 사용합니다. 미리보기의 외부 호출 없음, 기존 이름의 덮어쓰기 방지, 사용자 범위·SIT·규칙의 조회 검증, 실패 시 활성화 방지를 확인합니다.

```powershell
pwsh -NoProfile -File .\tests\test_purview_policy_script.ps1
```

**이 새 스크립트로 실제 정책을 생성하거나 고객 테넌트에 적용하지는 않았습니다.** 오프라인 검사는 권한·라이선스·서비스 전파·실제 파일 차단·알림 전달을 검증하지 않으므로, 담당자가 7절의 실제 검증을 수행해야 합니다.

**English:** The test harness replaces service commands with local mocks. It tests preview isolation, validation, create-only behavior, scope/readback checks, and failure handling. This new script has not been applied to a live tenant. Permissions, licensing, propagation, actual blocking, and notification delivery require the administrator's live validation.
