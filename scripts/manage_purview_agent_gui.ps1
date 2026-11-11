#requires -Version 7.0
<#
.SYNOPSIS
    List tenant DLP policies and add an Agent/App ID to a selected application policy.
.DESCRIPTION
    Windows GUI. Connect explicitly, choose an existing enabled Application policy,
    and add the agent for all users of that app. Existing rules and modes are not edited.
    -Demo shows local fixtures and disables all service operations. -NoGui loads functions.
.EXAMPLE
    pwsh -NoProfile -STA -File .\scripts\manage_purview_agent_gui.ps1
.LINK
    https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/set-dlpcompliancepolicy#-locations
#>
[CmdletBinding()]
param([switch]$NoGui, [switch]$Demo)

$script:AgentDlpDemoMode = [bool]$Demo
$script:AgentDlpUi = $null

function Get-AgentDlpField($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    if ($Object -is [Collections.IDictionary]) {
        foreach ($key in $Object.Keys) { if ([string]$key -ieq $Name) { return $Object[$key] } }
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    return $null
}

function ConvertTo-AgentDlpCanonicalJson($Value) {
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [Collections.IDictionary] -or $Value -is [pscustomobject]) {
        $keys = if ($Value -is [Collections.IDictionary]) { @($Value.Keys) } else { @($Value.PSObject.Properties.Name) }
        $parts = foreach ($key in @($keys | Sort-Object)) {
            (ConvertTo-Json -InputObject ([string]$key).ToLowerInvariant() -Compress) + ':' +
                (ConvertTo-AgentDlpCanonicalJson (Get-AgentDlpField $Value $key))
        }
        return '{' + ($parts -join ',') + '}'
    }
    if ($Value -is [Collections.IEnumerable] -and $Value -isnot [string]) {
        $parts = @(foreach ($item in $Value) { ConvertTo-AgentDlpCanonicalJson $item })
        return '[' + ((@($parts | Sort-Object)) -join ',') + ']'
    }
    return ConvertTo-Json -InputObject $Value -Depth 30 -Compress
}

function Assert-AgentDlpGuid([string]$Value, [string]$Label) {
    $parsed = [guid]::Empty
    if (-not [guid]::TryParse($Value, [ref]$parsed) -or $parsed -eq [guid]::Empty) {
        throw "$Label 에 실제 GUID를 입력하세요. / Enter a nonempty GUID."
    }
    return $parsed.ToString()
}

function Get-AgentDlpLocations($Policy) {
    $raw = Get-AgentDlpField $Policy 'Locations'
    if ($null -eq $raw -or ($raw -is [string] -and [string]::IsNullOrWhiteSpace($raw))) { return }
    if ($raw -is [string]) { $raw = ConvertFrom-Json -InputObject $raw -AsHashtable -Depth 100 -ErrorAction Stop }
    foreach ($location in @($raw)) {
        if ($location -isnot [Collections.IDictionary] -and $location -isnot [pscustomobject]) {
            throw '정책 Locations 형식을 확인할 수 없습니다. / Unsupported location response.'
        }
        $location
    }
}

function Get-AgentDlpRules([string]$PolicyId) {
    if ($script:AgentDlpDemoMode) { throw '데모 화면은 테넌트를 조회하지 않습니다. / Demo uses local data only.' }
    $id = Assert-AgentDlpGuid $PolicyId 'Policy ID'
    Get-DlpComplianceRule -Policy $id -ErrorAction Stop
}

function Get-AgentDlpPolicies {
    if ($script:AgentDlpDemoMode) { throw '데모 화면은 테넌트를 조회하지 않습니다. / Demo uses local data only.' }
    Get-DlpCompliancePolicy -ErrorAction Stop | Sort-Object Name
}

function Get-AgentDlpEligibility($Policy, [object[]]$Rules) {
    $mode = [string](Get-AgentDlpField $Policy 'Mode')
    $planes = @(Get-AgentDlpField $Policy 'EnforcementPlanes')
    $policyId = [string](Get-AgentDlpField $Policy 'Guid')
    $policyName = [string](Get-AgentDlpField $Policy 'Name')
    $reason = ''
    $matched = @()
    if ($mode -ine 'Enable') { $reason = "정책이 활성 상태가 아닙니다 ($mode). / Policy must be Enable." }
    elseif ($planes -notcontains 'Application') { $reason = 'Application 적용 정책이 아닙니다. / Application enforcement plane required.' }
    else {
        foreach ($rule in @($Rules)) {
            $parent = [string](Get-AgentDlpField $rule 'Policy')
            if ([string]::IsNullOrWhiteSpace($parent) -or $parent -notin @($policyId, $policyName)) {
                $reason = '선택한 정책과 다른 규칙이 조회되었습니다. / Rule parent mismatch.'
                break
            }
            $isEnabled = [string](Get-AgentDlpField $rule 'Disabled') -ieq 'False'
            $sits = @(Get-AgentDlpField $rule 'ContentContainsSensitiveInformation') | Where-Object { $null -ne $_ }
            $blocks = @(Get-AgentDlpField $rule 'RestrictAccess') | Where-Object {
                [string](Get-AgentDlpField $_ 'Setting') -ieq 'UploadText' -and
                [string](Get-AgentDlpField $_ 'Value') -ieq 'Block'
            }
            if ($isEnabled -and @($sits).Count -gt 0 -and @($blocks).Count -gt 0) { $matched += $rule }
        }
        if (-not $reason -and $matched.Count -eq 0) {
            $reason = '활성 SIT + UploadText Block 규칙이 없습니다. / Enabled SIT/UploadText Block rule required.'
        }
    }
    [pscustomobject]@{ Eligible = [string]::IsNullOrEmpty($reason); Reason = $reason; MatchingRules = @($matched) }
}

function New-AgentDlpLocationDelta([string]$AppId, [string]$AppName) {
    $id = Assert-AgentDlpGuid $AppId 'Agent / App ID'
    if ([string]::IsNullOrWhiteSpace($AppName) -or $AppName -match '[\r\n<>]') {
        throw 'Agent 이름을 입력하세요. / Enter an agent display name.'
    }
    $delta = @(@{
        Workload = 'Applications'; Location = $id; LocationDisplayName = $AppName.Trim()
        LocationSource = 'Entra'; LocationType = 'Individual'
        AddInclusions = @(@{ Type = 'Tenant'; Identity = 'All' })
    })
    ConvertTo-Json -InputObject $delta -Depth 20 -Compress
}

function Test-AgentDlpAllUserLocation($Location) {
    $included = @(Get-AgentDlpField $Location 'Inclusions') | Where-Object { $null -ne $_ }
    $excluded = @(Get-AgentDlpField $Location 'Exclusions') | Where-Object { $null -ne $_ }
    return (
        [string](Get-AgentDlpField $Location 'Workload') -ieq 'Applications' -and
        [string](Get-AgentDlpField $Location 'LocationSource') -ieq 'Entra' -and
        [string](Get-AgentDlpField $Location 'LocationType') -ieq 'Individual' -and
        @($included).Count -eq 1 -and @($excluded).Count -eq 0 -and
        [string](Get-AgentDlpField @($included)[0] 'Type') -ieq 'Tenant' -and
        [string](Get-AgentDlpField @($included)[0] 'Identity') -ieq 'All'
    )
}

function Get-AgentDlpRuleSnapshot([object[]]$Rules) {
    $fields = @('Guid', 'Name', 'Policy', 'Disabled', 'Priority', 'ContentContainsSensitiveInformation',
        'RestrictAccess', 'StopPolicyProcessing', 'AdvancedRule', 'GenerateAlert', 'GenerateIncidentReport',
        'NotifyUser', 'IncidentReportContent', 'ReportSeverityLevel')
    $snapshot = @(foreach ($rule in @($Rules)) {
        $item = @{}
        foreach ($field in $fields) { $item[$field] = Get-AgentDlpField $rule $field }
        $item
    })
    ConvertTo-AgentDlpCanonicalJson $snapshot
}

function Add-AgentToDlpPolicy([string]$PolicyId, [string]$AppId, [string]$AppName) {
    if ($script:AgentDlpDemoMode) { throw '데모 화면에서는 테넌트를 변경할 수 없습니다. / Demo is read-only.' }
    $id = Assert-AgentDlpGuid $PolicyId 'Policy ID'
    $agentId = Assert-AgentDlpGuid $AppId 'Agent / App ID'
    $delta = New-AgentDlpLocationDelta -AppId $agentId -AppName $AppName
    # Fresh reads prevent the selected row from acting as stale authorization/configuration.
    $found = @(Get-DlpCompliancePolicy -Identity $id -ErrorAction Stop)
    if ($found.Count -ne 1 -or [string](Get-AgentDlpField $found[0] 'Guid') -ine $id) {
        throw '선택한 정책 ID를 정확히 조회하지 못했습니다. / Exact policy lookup failed.'
    }
    $before = $found[0]
    $rulesBefore = @(Get-AgentDlpRules -PolicyId $id)
    $eligibility = Get-AgentDlpEligibility -Policy $before -Rules $rulesBefore
    if (-not $eligibility.Eligible) { throw $eligibility.Reason }
    $locationsBefore = @(Get-AgentDlpLocations $before)
    $existing = @($locationsBefore | Where-Object { [string](Get-AgentDlpField $_ 'Location') -ieq $agentId })
    if ($existing.Count -gt 0) {
        if ($existing.Count -ne 1 -or -not (Test-AgentDlpAllUserLocation $existing[0])) {
            throw '이 앱은 이미 제한된 사용자 범위 또는 다른 설정으로 등록되어 있습니다. 자동으로 넓히지 않습니다. / Existing app scope needs administrator review.'
        }
        return [pscustomobject]@{
            Status = 'AlreadyConfigured'; PolicyId = $id; AppId = $agentId; Mode = [string](Get-AgentDlpField $before 'Mode')
            PreviousLocationsPreserved = $true; RuntimeEnforcementVerified = $false
        }
    }
    $oldLocations = @($locationsBefore | ForEach-Object { ConvertTo-AgentDlpCanonicalJson $_ })
    $oldRules = Get-AgentDlpRuleSnapshot $rulesBefore
    $oldPlanes = ConvertTo-AgentDlpCanonicalJson @(Get-AgentDlpField $before 'EnforcementPlanes')
    $oldMode = [string](Get-AgentDlpField $before 'Mode')
    # Set uses a delta. Never submit an Inclusions snapshot or change mode/rules.
    try {
        Set-DlpCompliancePolicy -Identity $id -Locations $delta -Confirm:$false -ErrorAction Stop | Out-Null
        $readback = @(Get-DlpCompliancePolicy -Identity $id -ErrorAction Stop)
        if ($readback.Count -ne 1 -or [string](Get-AgentDlpField $readback[0] 'Guid') -ine $id) {
            throw '적용 후 정책 ID 조회가 일치하지 않습니다. / Readback policy identity mismatch.'
        }
        $after = $readback[0]
        if ([string](Get-AgentDlpField $after 'Mode') -ine $oldMode -or
            (ConvertTo-AgentDlpCanonicalJson @(Get-AgentDlpField $after 'EnforcementPlanes')) -cne $oldPlanes) {
            throw '정책 모드 또는 적용 영역이 달라졌습니다. / Policy mode or enforcement planes changed.'
        }
        $locationsAfter = @(Get-AgentDlpLocations $after)
        if ($locationsAfter.Count -ne $locationsBefore.Count + 1) { throw '적용 후 앱 범위 개수가 예상과 다릅니다. / Unexpected location count.' }
        $afterSnapshots = @($locationsAfter | ForEach-Object { ConvertTo-AgentDlpCanonicalJson $_ })
        foreach ($old in $oldLocations) {
            if (@($afterSnapshots | Where-Object { $_ -ceq $old }).Count -ne 1) {
                throw '기존 앱 범위 보존을 확인하지 못했습니다. / An existing location changed.'
            }
        }
        $added = @($locationsAfter | Where-Object { [string](Get-AgentDlpField $_ 'Location') -ieq $agentId })
        if ($added.Count -ne 1 -or -not (Test-AgentDlpAllUserLocation $added[0])) {
            throw '추가한 앱의 전체 사용자 범위를 확인하지 못했습니다. / Added app scope differs.'
        }
        $rulesAfter = @(Get-AgentDlpRules -PolicyId $id)
        if ((Get-AgentDlpRuleSnapshot $rulesAfter) -cne $oldRules) { throw '기존 규칙 설정이 달라졌습니다. / Existing rule settings changed.' }
        [pscustomobject]@{
            Status = 'Configured'; PolicyId = $id; AppId = $agentId; Mode = $oldMode
            PreviousLocationsPreserved = $true; RuntimeEnforcementVerified = $false
            DistributionStatus = Get-AgentDlpField $after 'DistributionStatus'
        }
    }
    catch {
        throw ('적용 결과를 확인하지 못했습니다. 요청이 서버에 반영되었을 수 있으므로 목록을 새로 조회하고 관리자와 상태를 확인하세요. 자동 재시도/되돌리기는 하지 않습니다. / The write may have reached the service; refresh and inspect before retrying. ' + $_.Exception.Message)
    }
}

function Set-AgentDlpUiStatus([string]$Text, [bool]$IsError = $false) {
    $script:AgentDlpUi.Status.Text = $Text
    $script:AgentDlpUi.Status.Foreground = if ($IsError) { '#B42318' } else { '#334155' }
}

function Set-AgentDlpUiBusy([bool]$Busy) {
    $ui = $script:AgentDlpUi
    $ui.Busy = $Busy
    $ui.Connect.IsEnabled = -not $Busy -and -not $ui.Demo
    $ui.Refresh.IsEnabled = -not $Busy -and ($ui.Connected -or $ui.Demo)
    $ui.Policies.IsEnabled = -not $Busy
    $ui.Window.Cursor = if ($Busy) { [Windows.Input.Cursors]::Wait } else { [Windows.Input.Cursors]::Arrow }
    Update-AgentDlpApplyButton
    if ($Busy) { $ui.Window.Dispatcher.Invoke([Action]{}, [Windows.Threading.DispatcherPriority]::Render) }
}

function Update-AgentDlpApplyButton {
    $ui = $script:AgentDlpUi
    $parsed = [guid]::Empty
    $valid = [guid]::TryParse($ui.AppId.Text.Trim(), [ref]$parsed) -and $parsed -ne [guid]::Empty -and
        -not [string]::IsNullOrWhiteSpace($ui.AppName.Text) -and $ui.AppName.Text -notmatch '[\r\n<>]'
    $ui.Apply.IsEnabled = -not $ui.Busy -and -not $ui.Demo -and $ui.Connected -and $ui.Eligible -and $valid
}

function Update-AgentDlpSelection {
    $ui = $script:AgentDlpUi
    $ui.Eligible = $false
    Update-AgentDlpApplyButton
    $row = $ui.Policies.SelectedItem
    if ($null -eq $row) { $ui.Details.Text = '정책을 선택하면 SIT와 차단 규칙을 표시합니다. / Select a policy to inspect its rules.'; return }
    try {
        Set-AgentDlpUiBusy $true
        Set-AgentDlpUiStatus '선택한 정책의 규칙을 확인하고 있습니다… / Loading rules…'
        $rules = @(if ($ui.Demo) { $ui.DemoRules[$row.PolicyId] | Where-Object { $null -ne $_ } } else { Get-AgentDlpRules -PolicyId $row.PolicyId })
        $eligibility = Get-AgentDlpEligibility -Policy $row.Policy -Rules $rules
        $ui.Eligible = $eligibility.Eligible
        $summary = [Collections.Generic.List[string]]::new()
        $summary.Add("정책 / Policy: $($row.Name)")
        $summary.Add("Policy ID: $($row.PolicyId)")
        $summary.Add("상태 / Mode: $($row.Mode)    적용 영역 / Plane: $($row.Planes)")
        $summary.Add($(if ($eligibility.Eligible) { '앱 추가 가능 / Ready to add an app. 기존 조건·예외·우선순위는 그대로 적용됩니다.' } else { $eligibility.Reason }))
        $summary.Add('')
        foreach ($rule in $rules) {
            $sitNames = @(@(Get-AgentDlpField $rule 'ContentContainsSensitiveInformation') | ForEach-Object {
                $name = Get-AgentDlpField $_ 'Name'; if (-not $name) { $name = Get-AgentDlpField $_ 'Id' }; [string]$name
            }) -join ', '
            $actions = @(@(Get-AgentDlpField $rule 'RestrictAccess') | ForEach-Object {
                "$(Get-AgentDlpField $_ 'Setting')=$(Get-AgentDlpField $_ 'Value')"
            }) -join ', '
            $summary.Add("규칙 / Rule: $(Get-AgentDlpField $rule 'Name')")
            $summary.Add("  Disabled=$(Get-AgentDlpField $rule 'Disabled') | SIT: $sitNames")
            $summary.Add("  동작 / Actions: $actions")
        }
        if ($rules.Count -eq 0) { $summary.Add('규칙 없음 / No rules found.') }
        $ui.Details.Text = $summary -join [Environment]::NewLine
        Set-AgentDlpUiStatus $(if ($ui.Demo) {
            '데모 화면 · 실제 연결/적용 없음 / Local demo. ' + $(if (-not $eligibility.Eligible) { $eligibility.Reason } else { '앱 추가 가능한 정책 예제입니다. / Eligible policy example.' })
        } elseif ($eligibility.Eligible) { 'Agent ID와 이름을 입력한 후 [선택한 DLP에 Agent 추가]를 누르세요.' } else { $eligibility.Reason })
    }
    catch { Set-AgentDlpUiStatus $_.Exception.Message $true }
    finally { Set-AgentDlpUiBusy $false }
}

function Update-AgentDlpPolicyList {
    $ui = $script:AgentDlpUi
    try {
        Set-AgentDlpUiBusy $true
        $ui.Eligible = $false
        $ui.Policies.SelectedItem = $null
        $ui.Policies.ItemsSource = @()
        Set-AgentDlpUiStatus '테넌트 DLP 목록을 가져오고 있습니다… / Loading DLP policies…'
        $policies = if ($ui.Demo) { $ui.DemoPolicies } else { @(Get-AgentDlpPolicies) }
        $rows = @(foreach ($policy in $policies) {
            $planes = @(Get-AgentDlpField $policy 'EnforcementPlanes')
            $mode = [string](Get-AgentDlpField $policy 'Mode')
            [pscustomobject]@{
                Name = [string](Get-AgentDlpField $policy 'Name'); PolicyId = [string](Get-AgentDlpField $policy 'Guid')
                Mode = $mode; Planes = $planes -join ', '
                Availability = if ($mode -ine 'Enable') { '비활성/시험 · Not active' } elseif ($planes -notcontains 'Application') { '다른 적용 영역 · Other plane' } else { '선택 후 규칙 확인 · Inspect rules' }
                Policy = $policy
            }
        })
        $ui.Policies.ItemsSource = $rows
        Set-AgentDlpUiStatus ("정책 $($rows.Count)개를 조회했습니다. 목록에서 하나를 선택하세요. / Select a policy.")
    }
    catch { Set-AgentDlpUiStatus $_.Exception.Message $true }
    finally { Set-AgentDlpUiBusy $false }
}

function Connect-AgentDlpUi {
    $ui = $script:AgentDlpUi
    if ($ui.Demo) { return }
    try {
        Set-AgentDlpUiBusy $true
        $ui.Connected = $false
        $ui.Eligible = $false
        $ui.Policies.SelectedItem = $null
        $ui.Policies.ItemsSource = @()
        $ui.Session.Text = '연결 중 / Connecting…'
        Set-AgentDlpUiStatus 'Microsoft 로그인 창에서 고객 테넌트의 정책 관리자로 로그인하세요. / Sign in to the intended tenant.'
        if (-not (Get-Module -ListAvailable -Name ExchangeOnlineManagement)) {
            throw 'ExchangeOnlineManagement 모듈이 필요합니다. 관리자가 승인한 환경에 설치 후 다시 실행하세요. / Required module is not installed.'
        }
        Import-Module ExchangeOnlineManagement -Global -ErrorAction Stop
        $parameters = @{
            ShowBanner = $false; ErrorAction = 'Stop'
            CommandName = @('Get-DlpCompliancePolicy', 'Get-DlpComplianceRule', 'Set-DlpCompliancePolicy')
        }
        if (-not [string]::IsNullOrWhiteSpace($ui.Admin.Text)) { $parameters.UserPrincipalName = $ui.Admin.Text.Trim() }
        Connect-IPPSSession @parameters
        foreach ($command in @('Get-DlpCompliancePolicy', 'Get-DlpComplianceRule', 'Set-DlpCompliancePolicy')) {
            if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "필요한 명령을 사용할 수 없습니다: $command" }
        }
        $ui.Connected = $true
        $ui.Session.Text = '연결됨 / Connected. 로그인한 테넌트의 정책을 조회합니다.'
        if (Get-Command Get-ConnectionInformation -ErrorAction SilentlyContinue) {
            try {
                $connections = @(Get-ConnectionInformation -ErrorAction Stop)
                $sessionText = @($connections | ForEach-Object {
                    "$(Get-AgentDlpField $_ 'UserPrincipalName') | Tenant: $(Get-AgentDlpField $_ 'TenantID')"
                }) -join '; '
                if ($sessionText) { $ui.Session.Text = $sessionText }
            }
            catch { $ui.Session.Text = '연결됨. 세션 정보는 조회되지 않았습니다. / Connected; session metadata unavailable.' }
        }
        Update-AgentDlpPolicyList
    }
    catch { $ui.Connected = $false; $ui.Session.Text = '연결 실패 / Connection failed'; Set-AgentDlpUiStatus $_.Exception.Message $true }
    finally { Set-AgentDlpUiBusy $false }
}

function Show-AgentDlpWindow([switch]$Demo) {
    if (-not $IsWindows) { throw 'Windows에서 실행하세요. / This GUI requires Windows.' }
    if ([Threading.Thread]::CurrentThread.GetApartmentState() -ne 'STA') { throw 'pwsh -NoProfile -STA -File .\scripts\manage_purview_agent_gui.ps1 로 실행하세요.' }
    $script:AgentDlpDemoMode = [bool]$Demo
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
    [xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
 Title="Purview DLP · Agent 연결" Width="1160" Height="850" MinWidth="940" MinHeight="720" WindowStartupLocation="CenterScreen" Background="#F3F6FA" FontFamily="Malgun Gothic, Segoe UI" FontSize="13">
 <Window.Resources>
  <Style TargetType="Button"><Setter Property="Padding" Value="14,8"/><Setter Property="Margin" Value="8,0,0,0"/><Setter Property="MinHeight" Value="36"/></Style>
  <Style TargetType="TextBox"><Setter Property="Padding" Value="9,6"/><Setter Property="VerticalContentAlignment" Value="Center"/></Style>
 </Window.Resources>
 <Grid Margin="24"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
  <StackPanel Grid.Row="0" Margin="0,0,0,18"><TextBlock Text="기존 DLP 정책에 Agent 연결" FontSize="25" FontWeight="SemiBold" Foreground="#172B4D"/><TextBlock Text="Connect an Agent/App ID to an existing Purview application policy" Foreground="#64748B" Margin="0,5,0,0"/></StackPanel>
  <Border Grid.Row="1" Padding="16" Background="White" CornerRadius="8" Margin="0,0,0,14"><Grid><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
   <StackPanel><TextBlock Text="1. 관리자 로그인 · Admin sign-in (UPN은 선택 입력)" FontWeight="SemiBold" Margin="0,0,0,6"/><TextBox x:Name="Admin" ToolTip="고객 테넌트의 Purview 정책 관리자 UPN / Optional admin UPN"/></StackPanel>
   <Button x:Name="Connect" Grid.Column="1" Content="로그인 / Connect" VerticalAlignment="Bottom"/><Button x:Name="Refresh" Grid.Column="2" Content="목록 새로고침 / Refresh" VerticalAlignment="Bottom" IsEnabled="False"/>
   <TextBlock x:Name="Session" Grid.Row="1" Grid.ColumnSpan="3" Text="연결 전 / Not connected" Foreground="#64748B" TextWrapping="Wrap" Margin="0,8,0,0"/>
  </Grid></Border>
  <Grid Grid.Row="2"><Grid.RowDefinitions><RowDefinition Height="0.8*"/><RowDefinition Height="6"/><RowDefinition Height="1.2*"/></Grid.RowDefinitions>
   <Border Grid.Row="0" Background="White" CornerRadius="8" Padding="14"><DockPanel><TextBlock DockPanel.Dock="Top" Text="2. DLP 정책 선택 · Select a policy" FontWeight="SemiBold" Margin="0,0,0,10"/>
    <DataGrid x:Name="Policies" AutoGenerateColumns="False" IsReadOnly="True" SelectionMode="Single" SelectionUnit="FullRow" CanUserAddRows="False" CanUserDeleteRows="False" HeadersVisibility="Column" GridLinesVisibility="Horizontal" BorderBrush="#E2E8F0" RowHeight="34" HorizontalScrollBarVisibility="Auto">
     <DataGrid.Columns><DataGridTextColumn Header="정책 이름 / Policy" Binding="{Binding Name}" Width="*" MinWidth="180"/><DataGridTextColumn Header="모드 / Mode" Binding="{Binding Mode}" Width="165"/><DataGridTextColumn Header="영역 / Plane" Binding="{Binding Planes}" Width="125"/><DataGridTextColumn Header="상태 / Availability" Binding="{Binding Availability}" Width="260"/></DataGrid.Columns>
    </DataGrid>
   </DockPanel></Border>
   <GridSplitter Grid.Row="1" Height="6" HorizontalAlignment="Stretch" Background="Transparent"/>
   <Border Grid.Row="2" Background="White" CornerRadius="8" Padding="14"><DockPanel><TextBlock DockPanel.Dock="Top" Text="선택한 정책의 규칙 · Rules and eligibility" FontWeight="SemiBold" Margin="0,0,0,8"/>
    <TextBox x:Name="Details" IsReadOnly="True" TextWrapping="Wrap" AcceptsReturn="True" VerticalScrollBarVisibility="Auto" BorderThickness="0" Background="#F8FAFC" Text="정책을 선택하면 SIT와 차단 규칙을 표시합니다. / Select a policy to inspect its rules."/>
   </DockPanel></Border>
  </Grid>
  <Border Grid.Row="3" Background="White" CornerRadius="8" Padding="16" Margin="0,14,0,0"><Grid><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="260"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
   <TextBlock Grid.ColumnSpan="3" Text="3. Agent 정보 입력 · Add an agent" FontWeight="SemiBold" Margin="0,0,0,9"/>
   <StackPanel Grid.Row="1" Margin="0,0,12,0"><TextBlock Text="Agent ID / App ID (GUID)" Margin="0,0,0,4"/><TextBox x:Name="AppId"/></StackPanel>
   <StackPanel Grid.Row="1" Grid.Column="1"><TextBlock Text="Agent 이름 / Agent name" Margin="0,0,0,4"/><TextBox x:Name="AppName"/></StackPanel>
   <Button x:Name="Apply" Grid.Row="1" Grid.Column="2" Content="선택한 DLP에 Agent 추가" VerticalAlignment="Bottom" BorderThickness="0" IsEnabled="False">
    <Button.Style><Style TargetType="Button" BasedOn="{StaticResource {x:Type Button}}"><Setter Property="Background" Value="#174EA6"/><Setter Property="Foreground" Value="White"/>
     <Style.Triggers><Trigger Property="IsEnabled" Value="False"><Setter Property="Foreground" Value="#64748B"/><Setter Property="Background" Value="#E2E8F0"/></Trigger></Style.Triggers>
    </Style></Button.Style>
   </Button>
   <TextBlock Grid.Row="2" Grid.ColumnSpan="3" Text="적용 범위: 이 앱을 사용하는 테넌트 전체 사용자 · All users of this app. 기존 SIT·규칙·모드는 유지됩니다." Foreground="#64748B" TextWrapping="Wrap" Margin="0,10,0,0"/>
  </Grid></Border>
  <TextBlock Grid.Row="4" x:Name="Status" Text="관리자로 로그인하여 목록을 가져오세요. / Connect to load policies." TextWrapping="Wrap" Foreground="#334155" Margin="2,14,2,0" MinHeight="38"/>
 </Grid>
</Window>
'@
    $window = [Windows.Markup.XamlReader]::Load([Xml.XmlNodeReader]::new($xaml))
    $ui = @{ Window = $window; Connected = $false; Busy = $false; Eligible = $false; Demo = [bool]$Demo }
    foreach ($name in @('Admin','Connect','Refresh','Session','Policies','Details','AppId','AppName','Apply','Status')) { $ui[$name] = $window.FindName($name) }
    $script:AgentDlpUi = $ui
    $ui.Connect.Add_Click({ Connect-AgentDlpUi })
    $ui.Refresh.Add_Click({ Update-AgentDlpPolicyList })
    $ui.Policies.Add_SelectionChanged({ Update-AgentDlpSelection })
    $ui.AppId.Add_TextChanged({ Update-AgentDlpApplyButton })
    $ui.AppName.Add_TextChanged({ Update-AgentDlpApplyButton })
    $ui.Apply.Add_Click({
        $ui = $script:AgentDlpUi
        try {
            Set-AgentDlpUiBusy $true
            Set-AgentDlpUiStatus '정책을 다시 확인한 후 Agent 적용 범위를 추가하고 있습니다… / Applying and verifying…'
            $result = Add-AgentToDlpPolicy -PolicyId $ui.Policies.SelectedItem.PolicyId -AppId $ui.AppId.Text.Trim() -AppName $ui.AppName.Text.Trim()
            $message = if ($result.Status -eq 'AlreadyConfigured') { '이미 같은 범위로 등록되어 있습니다. 변경하지 않았습니다. / Already configured.' } else { '앱 범위 추가와 기존 설정 보존을 확인했습니다. / App scope added and read back.' }
            Set-AgentDlpUiStatus ($message + ' 실제 차단은 정책 전파 후 processContent로 별도 테스트하세요. / Test runtime enforcement separately.')
        }
        catch { Set-AgentDlpUiStatus $_.Exception.Message $true }
        finally { Set-AgentDlpUiBusy $false }
    })
    if ($Demo) {
        $demoId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        $ui.DemoPolicies = @(
            [pscustomobject]@{Guid=$demoId;Name='Demo · Credit Card protection';Mode='Enable';EnforcementPlanes=@('Application');Locations='[]'},
            [pscustomobject]@{Guid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';Name='Demo · Policy in simulation';Mode='TestWithoutNotifications';EnforcementPlanes=@('Application');Locations='[]'},
            [pscustomobject]@{Guid='cccccccc-cccc-4ccc-8ccc-cccccccccccc';Name='Demo · Exchange email';Mode='Enable';EnforcementPlanes=@('Exchange');Locations='[]'}
        )
        $ui.DemoRules = @{}
        $ui.DemoRules[$demoId] = @([pscustomobject]@{
            Guid='dddddddd-dddd-4ddd-8ddd-dddddddddddd';Name='Block credit card input';Policy=$demoId;Disabled=$false
            ContentContainsSensitiveInformation=@(@{Name='Credit Card Number';mincount='1';minconfidence='85'})
            RestrictAccess=@(@{Setting='UploadText';Value='Block'})
        })
        $ui.AppId.Text = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
        $ui.AppName.Text = 'Demo Agent'
        $ui.Session.Text = '로컬 데모 데이터 / Local sample data · 테넌트 연결 없음 / No tenant connection'
        $ui.Connect.IsEnabled = $false
        Update-AgentDlpPolicyList
        $ui.Policies.SelectedIndex = 0
    }
    $null = $window.ShowDialog()
}

if (-not $NoGui) { Show-AgentDlpWindow -Demo:$Demo }
