# 기존 DLP에 Agent 추가하기 · Add an agent to an existing DLP policy

**목록 조회 → 정책 선택 → Agent ID와 이름 입력 → 앱 추가**를 한 화면에서 수행하는 Windows PowerShell GUI입니다.

파일: [manage_purview_agent_gui.ps1](../scripts/manage_purview_agent_gui.ps1). 별도 설정 파일이나 Agent의 Secret은 필요하지 않습니다.

## 1. 실행할 PC 준비

고객 테넌트에서 DLP 정책을 조회하고 변경할 권한이 있는 담당자가 **Windows 관리 PC**에서 실행합니다. 최신 `ExchangeOnlineManagement` 3.10 이상을 사용한다면 **PowerShell 7.6 이상**이 필요합니다. Python 에이전트를 실행하는 PC에 관리 도구를 설치할 필요는 없습니다. [공식 호환성 안내](https://learn.microsoft.com/en-us/powershell/exchange/exchange-online-powershell-v2?view=exchange-ps)

PowerShell에서 버전을 확인합니다.

```powershell
$PSVersionTable.PSVersion
Get-Module -ListAvailable ExchangeOnlineManagement
```

모듈이 없고 설치가 허용된 관리 PC에서만 아래 명령을 실행합니다.

```powershell
Install-Module ExchangeOnlineManagement -Scope CurrentUser
```

이 GUI에는 a365 CLI나 .NET SDK가 필요하지 않습니다. PowerShell 자체에 필요한 런타임과 설치 허용 여부는 관리 PC의 정책을 따릅니다.

## 2. GUI 열기

이 저장소의 프로젝트 폴더에서 실행합니다.

```powershell
pwsh -NoProfile -STA -File .\scripts\manage_purview_agent_gui.ps1
```

정책을 조회하거나 변경하지 않고 화면만 먼저 보려면 다음 명령을 사용합니다. 데모 모드는 가상 정책을 표시하며 로그인과 실제 적용은 하지 않습니다.

```powershell
pwsh -NoProfile -STA -File .\scripts\manage_purview_agent_gui.ps1 -Demo
```

## 3. 로그인하고 정책 선택하기

1. GUI의 로그인 버튼을 누릅니다. 관리자 계정 입력란은 로그인할 계정의 UPN이며, 비밀번호를 입력하는 곳이 아닙니다.
2. Microsoft 로그인 창에서 **작업할 고객 테넌트의 관리자 계정**으로 로그인합니다.
3. 목록 조회 버튼으로 현재 연결된 테넌트에서 조회 가능한 DLP 정책을 불러옵니다.
4. 원하는 정책을 선택하고 모드, 규칙, SIT, 앱 추가 가능 여부를 확인합니다.

이 도구는 **`Enable` 상태이며 `Application` 검사 영역과 활성 SIT / `UploadText=Block` 규칙을 가진 정책**에 앱을 추가합니다. 일반 OneDrive·Exchange 정책, 비활성 정책, 시뮬레이션 정책은 목록에 표시하되 이 도구에서 자동 변환하거나 활성화하지 않습니다. 적용 불가 사유를 확인하고 정책 담당자에게 필요한 구성을 요청합니다. 이는 이 GUI가 지원하는 범위이며 다른 Purview 정책의 전체 기능을 제한한다는 뜻은 아닙니다. [Microsoft의 Entra 앱 규칙 예제](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancerule?view=exchange-ps#example-4)

## 4. Agent ID와 이름 입력하기

| 입력란 | 넣을 값 |
|---|---|
| Agent ID / App ID | 정책이 보호할 실제 앱의 ID. 이 프로젝트는 `.env`의 `PURVIEW_APP_ID`와 같은 **자식 Agent ID**를 넣습니다. Blueprint ID나 웹 로그인 앱 ID를 넣지 않습니다. 일반 Entra 앱은 Application (client) ID를 사용합니다. |
| Agent 이름 | 정책 대상 앱을 구분할 표시 이름입니다. 예: `my-onedrive-agent`. ID가 실제 대상을 결정하며 이름만 바꿔 다른 앱을 선택할 수는 없습니다. |

새로 추가하는 앱의 범위는 **그 앱을 사용하는 테넌트의 전체 사용자(`Tenant All`)**입니다. 다른 앱을 전부 포함한다는 뜻은 아닙니다. 이 화면에서 사용자별 범위를 새로 지정하지는 않습니다.

선택한 정책과 입력한 앱을 확인한 뒤 앱 추가 버튼을 누릅니다. 앱이 이미 전체 사용자 범위로 등록되어 있으면 중복 추가하지 않습니다. 앱이 일부 사용자 범위로 이미 등록되어 있거나 제외 조건이 있으면 범위를 자동으로 넓히지 않고 안내합니다.

## 5. 결과 확인하기

GUI는 쓰기 직전에 정책·규칙을 다시 조회하고, 해당 앱의 추가 요청만 전송합니다. 적용 후에는 기존 앱 범위와 규칙이 유지되는지, 새 앱이 요청한 범위로 조회되는지 확인합니다. 기존 SIT·차단 동작·정책 모드는 변경하지 않습니다. [기존 정책에 앱 범위를 추가하는 Locations 규격](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/set-dlpcompliancepolicy?view=exchange-ps#-locations)

**앱 추가 결과 확인과 실제 민감 파일 차단 성공은 별개입니다.** 정책 전파 후 에이전트가 `processContent`로 파일 본문을 평가하고, 차단 판정을 받으면 LLM 전송을 중단하는지 [파일 차단 검증 안내](purview-setup.md)를 따라 확인합니다. GUI는 Graph 동의나 OneDrive 권한을 부여하지 않습니다.

오류가 쓰기 이후에 발생했다면 변경이 서버에 반영되었을 수도 있습니다. 자동으로 되돌리거나 계속 재시도하지 말고, 목록을 새로 조회하여 실제 정책 상태를 확인합니다.

## English quick start

Use an authorized Windows administrative machine with PowerShell 7.6+ and a compatible ExchangeOnlineManagement module. Run the command in step 2, sign in to the intended tenant, load policies, select a supported active policy, enter the protected App ID and display name, then add the app.

This project uses the child Agent ID from `PURVIEW_APP_ID`. New app locations include all tenant users of that app. Existing restricted scopes are not broadened. The GUI updates only application locations; it does not change policy modes, SIT conditions, rules, or Graph consent. A successful readback is configuration verification, not proof of live file blocking. `-Demo` uses local sample data without tenant access.

## 검증 · Verification

오프라인 테스트:

```powershell
pwsh -NoProfile -File .\tests\test_purview_agent_gui.ps1
```

자동 테스트는 서비스 명령을 로컬 모의 함수로 대체합니다. 실제 테넌트 변경이나 파일 차단 성공을 검증하는 테스트는 아닙니다. / Tests use local mocks and do not prove live tenant enforcement.
