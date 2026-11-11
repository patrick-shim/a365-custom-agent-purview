#requires -Version 7.0
<#
.SYNOPSIS
    Offline behavior checks for the Purview Agent GUI. No tenant is contacted.
.DESCRIPTION
    Service commands are replaced with local functions before the script is loaded.
    Run in a fresh process: pwsh -NoProfile -File tests/test_purview_agent_gui.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$script:GuiPassed = 0
$script:GuiFailures = [Collections.Generic.List[string]]::new()
$script:GuiPolicyId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
$script:GuiRuleId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
$script:GuiOldAppId = '11111111-1111-4111-8111-111111111111'
$script:GuiNewAppId = '22222222-2222-4222-8222-222222222222'

function Copy-GuiFixture($Value) {
    return ($Value | ConvertTo-Json -Depth 30 | ConvertFrom-Json)
}
function New-GuiLocation([string]$Id, [string]$Name = 'Approved app') {
    return @{
        Workload = 'Applications'; Location = $Id; LocationDisplayName = $Name
        LocationSource = 'Entra'; LocationType = 'Individual'
        Inclusions = @(@{Type = 'Tenant'; Identity = 'All'})
    }
}
function Reset-GuiFake {
    $script:AgentDlpDemoMode = $false
    $script:GuiState = @{
        Scenario = ''; Calls = [Collections.Generic.List[string]]::new()
        Writes = [Collections.Generic.List[object]]::new()
        Policy = [pscustomobject]@{
            Guid = $script:GuiPolicyId; Name = 'Existing app policy'; Mode = 'Enable'
            EnforcementPlanes = @('Application'); DistributionStatus = 'Success'
            Locations = ConvertTo-Json -InputObject @(New-GuiLocation $script:GuiOldAppId) -Depth 20 -Compress
        }
        Rules = @([pscustomobject]@{
            Guid = $script:GuiRuleId; Name = 'Credit card block'; Policy = $script:GuiPolicyId
            Disabled = $false; ContentContainsSensitiveInformation = @(@{Name='Credit Card Number';mincount='1'})
            RestrictAccess = @(@{Setting='UploadText';Value='Block'}); StopPolicyProcessing=$false
        })
    }
}

# These functions are deliberately local substitutes, never forwarded to a module.
function Import-Module { throw 'Unexpected module import in an offline test.' }
function Connect-IPPSSession { throw 'Unexpected tenant connection in an offline test.' }
function Get-DlpCompliancePolicy {
    [CmdletBinding()] param([string]$Identity, [switch]$DistributionDetail)
    $script:GuiState.Calls.Add('GetPolicy')
    if ($script:GuiState.Scenario -eq 'LookupDenied') { throw 'Fake policy lookup denied.' }
    if (-not $Identity) {
        Copy-GuiFixture $script:GuiState.Policy
        $other = Copy-GuiFixture $script:GuiState.Policy
        $other.Guid = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'; $other.Name = 'Ordinary OneDrive policy'
        $other.EnforcementPlanes = @('Exchange', 'SharePoint'); $other.Locations = '[]'
        $other
        $disabled = Copy-GuiFixture $script:GuiState.Policy
        $disabled.Guid = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'; $disabled.Name = 'Disabled app policy'; $disabled.Mode = 'Disable'
        $disabled
        return
    }
    if ($Identity -ne $script:GuiPolicyId) { throw 'Unexpected policy identity requested.' }
    $copy = Copy-GuiFixture $script:GuiState.Policy
    if ($script:GuiState.Scenario -eq 'WrongPolicyIdentity') { $copy.Guid = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee' }
    if ($script:GuiState.Writes.Count -gt 0) {
        $locations = @($copy.Locations | ConvertFrom-Json -AsHashtable)
        switch ($script:GuiState.Scenario) {
            'LostOldLocation' { $locations = @($locations | Where-Object Location -ne $script:GuiOldAppId) }
            'ChangedOldScope' { $locations[0].Inclusions = @(@{Type='IndividualResource';Identity='unapproved@example.com'}) }
            'MissingNewLocation' { $locations = @($locations | Where-Object Location -ne $script:GuiNewAppId) }
            'WrongNewScope' { $locations[-1].Inclusions = @(@{Type='IndividualResource';Identity='unapproved@example.com'}) }
            'ChangedMode' { $copy.Mode = 'Disable' }
            'ChangedPlanes' { $copy.EnforcementPlanes = @('Application','SharePoint') }
            'ReorderedProperties' {
                $old = $locations[0]
                $locations[0] = [ordered]@{
                    Inclusions=$old.Inclusions; LocationType=$old.LocationType; LocationSource=$old.LocationSource
                    LocationDisplayName=$old.LocationDisplayName; Location=$old.Location; Workload=$old.Workload
                }
            }
        }
        $copy.Locations = ConvertTo-Json -InputObject $locations -Depth 20 -Compress
    }
    return $copy
}
function Get-DlpComplianceRule {
    [CmdletBinding()] param([string]$Policy, [string]$Identity)
    $script:GuiState.Calls.Add('GetRules')
    if ($script:GuiState.Scenario -eq 'RulesLookupDenied') { throw 'Fake rule lookup denied.' }
    if ($Policy -and $Policy -ne $script:GuiPolicyId) { return }
    $rules = @(Copy-GuiFixture $script:GuiState.Rules)
    if ($script:GuiState.Writes.Count -gt 0 -and $script:GuiState.Scenario -eq 'ChangedRules') {
        $rules[0].ContentContainsSensitiveInformation[0].mincount = '2'
    }
    return $rules
}
function Set-DlpCompliancePolicy {
    [CmdletBinding()] param([string]$Identity, [string]$Locations, [switch]$Confirm)
    $script:GuiState.Calls.Add('SetPolicy')
    $script:GuiState.Writes.Add(@{} + $PSBoundParameters)
    if ($Identity -ne $script:GuiPolicyId) { throw 'The target attempted to change another policy.' }
    if ($script:GuiState.Scenario -eq 'WriteDenied') { throw 'Fake policy update denied.' }
    $old = @($script:GuiState.Policy.Locations | ConvertFrom-Json -AsHashtable)
    $delta = @($Locations | ConvertFrom-Json -AsHashtable)
    foreach ($entry in $delta) {
        $old += @{
            Workload=$entry.Workload; Location=$entry.Location; LocationDisplayName=$entry.LocationDisplayName
            LocationSource=$entry.LocationSource; LocationType=$entry.LocationType; Inclusions=$entry.AddInclusions
        }
    }
    $script:GuiState.Policy.Locations = ConvertTo-Json -InputObject $old -Depth 20 -Compress
}
function New-DlpCompliancePolicy { throw 'Forbidden policy creation in an assignment-only GUI.' }
function New-DlpComplianceRule { throw 'Forbidden rule creation in an assignment-only GUI.' }
function Set-DlpComplianceRule { throw 'Forbidden rule update in an assignment-only GUI.' }
function Remove-DlpCompliancePolicy { throw 'Forbidden policy deletion in an assignment-only GUI.' }

Reset-GuiFake
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/manage_purview_agent_gui.ps1') -NoGui

function Assert-GuiTest($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Invoke-GuiAdd {
    Add-AgentToDlpPolicy -PolicyId $script:GuiPolicyId -AppId $script:GuiNewAppId -AppName 'New test agent'
}
function Assert-GuiReject([scriptblock]$Action, [string]$ExpectedError, [switch]$AfterWrite) {
    $message = $null
    try { $null = & $Action } catch { $message = $_.Exception.Message }
    Assert-GuiTest (-not [string]::IsNullOrEmpty($message)) 'Expected rejection, but the operation succeeded.'
    if ($ExpectedError) {
        Assert-GuiTest ($message -match $ExpectedError) ('Unexpected error: ' + $message)
    }
    if (-not $AfterWrite) { Assert-GuiTest ($script:GuiState.Writes.Count -eq 0) 'Rejected input performed a cloud write.' }
}
function Test-GuiCase([string]$Name, [scriptblock]$Body) {
    Reset-GuiFake
    try { & $Body; $script:GuiPassed++; Write-Host ('PASS ' + $Name) }
    catch { $script:GuiFailures.Add($Name + ': ' + $_.Exception.Message); Write-Host ('FAIL ' + $Name) }
}

Test-GuiCase 'list includes incompatible and disabled policies for administrator visibility' {
    $policies = @(Get-AgentDlpPolicies)
    Assert-GuiTest ($policies.Count -eq 3) 'The tenant list hid existing policies.'
    Assert-GuiTest ($script:GuiState.Writes.Count -eq 0) 'Listing policies changed a policy.'
}
Test-GuiCase 'enabled application policy with SIT and UploadText block is eligible' {
    $result = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiTest $result.Eligible 'A compatible blocking policy was rejected.'
    Assert-GuiTest (@($result.MatchingRules).Count -eq 1) 'The matching rule was not reported.'
}
foreach ($mode in @('Disable','TestWithNotifications','TestWithoutNotifications')) {
    Test-GuiCase ("policy mode $mode cannot claim live enforcement") {
        $script:GuiState.Policy.Mode = $mode
        $result = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
        Assert-GuiTest (-not $result.Eligible -and $result.Reason) 'A non-enforcing policy was eligible.'
        Assert-GuiReject { Invoke-GuiAdd } ([regex]::Escape($result.Reason))
    }
}
Test-GuiCase 'ordinary SharePoint policy is not silently converted to an application policy' {
    $script:GuiState.Policy.EnforcementPlanes = @('SharePoint')
    $result = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiTest (-not $result.Eligible) 'An ordinary policy was eligible.'
    Assert-GuiReject { Invoke-GuiAdd } ([regex]::Escape($result.Reason))
}
Test-GuiCase 'disabled blocking rule does not establish enforcement' {
    $script:GuiState.Rules[0].Disabled = $true
    $r = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiTest (-not $r.Eligible) 'A disabled rule was treated as active.'
    Assert-GuiReject { Invoke-GuiAdd } ([regex]::Escape($r.Reason))
}
Test-GuiCase 'a policy without a SIT condition is ineligible' {
    $script:GuiState.Rules[0].ContentContainsSensitiveInformation = @()
    $r = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiTest (-not $r.Eligible) 'A rule without SITs was eligible.'
    Assert-GuiReject { Invoke-GuiAdd } ([regex]::Escape($r.Reason))
}
Test-GuiCase 'DownloadText alone is not accepted as UploadText protection' {
    $script:GuiState.Rules[0].RestrictAccess = @(@{Setting='DownloadText';Value='Block'})
    $r = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiTest (-not $r.Eligible) 'A different activity was accepted.'
    Assert-GuiReject { Invoke-GuiAdd } ([regex]::Escape($r.Reason))
}
Test-GuiCase 'non-block action does not establish block protection' {
    $script:GuiState.Rules[0].RestrictAccess = @(@{Setting='UploadText';Value='Audit'})
    $r = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiTest (-not $r.Eligible) 'An audit action was accepted as a block.'
}
Test-GuiCase 'a rule belonging to a different policy cannot authorize assignment' {
    $script:GuiState.Rules[0].Policy = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
    $r = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiTest (-not $r.Eligible -and $r.Reason -match 'parent|다른 규칙') 'A rule from another policy was accepted.'
    Assert-GuiReject { Invoke-GuiAdd } ([regex]::Escape($r.Reason))
}
Test-GuiCase 'placeholder App ID is rejected before service operations' {
    Assert-GuiReject { Add-AgentToDlpPolicy -PolicyId $script:GuiPolicyId -AppId '<APP_ID>' -AppName 'Test' } 'App|GUID|ID'
    Assert-GuiTest ($script:GuiState.Calls.Count -eq 0) 'Invalid input reached a service lookup.'
}
Test-GuiCase 'empty App ID is rejected' {
    Assert-GuiReject { New-AgentDlpLocationDelta -AppId ([guid]::Empty.ToString()) -AppName 'Test' } 'App|GUID|ID'
}
Test-GuiCase 'empty display name is rejected' {
    Assert-GuiReject { New-AgentDlpLocationDelta -AppId $script:GuiNewAppId -AppName ' ' } 'name|이름'
}
Test-GuiCase 'delta is an array and adds only the requested application with explicit Tenant All' {
    $json = New-AgentDlpLocationDelta -AppId $script:GuiNewAppId -AppName 'New test agent'
    Assert-GuiTest ($json.TrimStart().StartsWith('[')) 'One app lost the JSON array envelope.'
    $delta = @($json | ConvertFrom-Json -AsHashtable)
    Assert-GuiTest ($delta.Count -eq 1 -and $delta[0].Location -eq $script:GuiNewAppId) 'Delta included unrelated locations.'
    Assert-GuiTest ($delta[0].LocationSource -eq 'Entra' -and $delta[0].LocationType -eq 'Individual') 'Wrong location source/type.'
    Assert-GuiTest ($delta[0].AddInclusions.Count -eq 1 -and $delta[0].AddInclusions[0].Type -eq 'Tenant' -and $delta[0].AddInclusions[0].Identity -eq 'All') 'All-user application scope was not explicit.'
    Assert-GuiTest (-not $delta[0].ContainsKey('Inclusions') -and -not $delta[0].ContainsKey('RemoveInclusions')) 'Creation or removal schema leaked into the update.'
    Assert-GuiTest ($script:GuiState.Calls.Count -eq 0) 'Building a delta contacted the service.'
}
Test-GuiCase 'successful assignment preserves existing scopes and does not alter policy mode or rules' {
    $before = $script:GuiState.Policy.Locations
    $result = Invoke-GuiAdd
    Assert-GuiTest ($result.Status -eq 'Configured' -and $result.PreviousLocationsPreserved) 'Successful verified assignment was not reported.'
    Assert-GuiTest ($result.RuntimeEnforcementVerified -eq $false) 'Readback was incorrectly claimed as runtime proof.'
    Assert-GuiTest ($script:GuiState.Writes.Count -eq 1) 'Assignment performed more than one mutation.'
    $params = $script:GuiState.Writes[0]
    Assert-GuiTest ($params.Identity -eq $script:GuiPolicyId) 'Assignment targeted a different policy.'
    foreach ($name in $params.Keys) { Assert-GuiTest ($name -in @('Identity','Locations','Confirm','ErrorAction')) ('Unexpected mutable setting: ' + $name) }
    $locations = @($script:GuiState.Policy.Locations | ConvertFrom-Json -AsHashtable)
    Assert-GuiTest ($locations.Count -eq 2) 'An existing scope was removed or extra scope added.'
    Assert-GuiTest ($locations[0].Location -eq $script:GuiOldAppId) 'Existing app was not preserved.'
    Assert-GuiTest (($script:GuiState.Calls -join ',') -match '^GetPolicy,GetRules,SetPolicy,GetPolicy,GetRules$') 'Assignment did not perform fresh reads and post-write verification.'
}
Test-GuiCase 'existing full app scope is idempotent and performs no mutation' {
    $script:GuiState.Policy.Locations = ConvertTo-Json -InputObject @((New-GuiLocation $script:GuiOldAppId),(New-GuiLocation $script:GuiNewAppId)) -Depth 20 -Compress
    $result = Invoke-GuiAdd
    Assert-GuiTest ($result.Status -eq 'AlreadyConfigured') 'Existing scope was not recognized.'
    Assert-GuiTest ($script:GuiState.Writes.Count -eq 0) 'Existing scope was rewritten.'
}
Test-GuiCase 'existing user-limited app scope is never broadened to all users' {
    $location = New-GuiLocation $script:GuiNewAppId
    $location.Inclusions = @(@{Type='IndividualResource';Identity='tester@example.com'})
    $script:GuiState.Policy.Locations = ConvertTo-Json -InputObject @($location) -Depth 20 -Compress
    Assert-GuiReject { Invoke-GuiAdd } 'scope|범위|사용자|이미'
}
Test-GuiCase 'existing app exclusions are not removed' {
    $location = New-GuiLocation $script:GuiNewAppId
    $location.Exclusions = @(@{Type='IndividualResource';Identity='excluded@example.com'})
    $script:GuiState.Policy.Locations = ConvertTo-Json -InputObject @($location) -Depth 20 -Compress
    Assert-GuiReject { Invoke-GuiAdd } 'scope|범위|제외|이미'
}
Test-GuiCase 'fresh policy state is checked after an earlier eligible selection' {
    $earlier = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiTest $earlier.Eligible 'Fixture must start eligible.'
    $script:GuiState.Policy.Mode = 'Disable'
    $now = Get-AgentDlpEligibility -Policy $script:GuiState.Policy -Rules $script:GuiState.Rules
    Assert-GuiReject { Invoke-GuiAdd } ([regex]::Escape($now.Reason))
}
Test-GuiCase 'policy lookup failures cannot be treated as permission to write' {
    $script:GuiState.Scenario = 'LookupDenied'
    Assert-GuiReject { Invoke-GuiAdd } 'Fake policy lookup denied'
}
Test-GuiCase 'rule lookup failures prevent changes' {
    $script:GuiState.Scenario = 'RulesLookupDenied'
    Assert-GuiReject { Invoke-GuiAdd } 'Fake rule lookup denied'
}
Test-GuiCase 'wrong resolved policy identity prevents changes' {
    $script:GuiState.Scenario = 'WrongPolicyIdentity'
    Assert-GuiReject { Invoke-GuiAdd } 'identity|정책|GUID|ID'
}
Test-GuiCase 'service write failure is surfaced without a success receipt' {
    $script:GuiState.Scenario = 'WriteDenied'
    Assert-GuiReject { Invoke-GuiAdd } 'Fake policy update denied' -AfterWrite
    Assert-GuiTest ($script:GuiState.Writes.Count -eq 1) 'Failed write was retried automatically.'
}
foreach ($scenario in @('LostOldLocation','ChangedOldScope','MissingNewLocation','WrongNewScope','ChangedMode','ChangedPlanes','ChangedRules')) {
    Test-GuiCase ("readback mismatch $scenario never reports success") {
        $script:GuiState.Scenario = $scenario
        Assert-GuiReject { Invoke-GuiAdd } 'readback|검증|변경|범위|규칙|mode|scope|location|policy|rule|plane' -AfterWrite
        Assert-GuiTest ($script:GuiState.Writes.Count -eq 1) 'A readback mismatch caused another mutation.'
    }
}
Test-GuiCase 'harmless object property order changes do not fail verification' {
    $script:GuiState.Scenario = 'ReorderedProperties'
    $result = Invoke-GuiAdd
    Assert-GuiTest ($result.Status -eq 'Configured') 'Property order was mistaken for a changed scope.'
}
Test-GuiCase 'demo mode cannot perform even a service lookup during assignment' {
    $script:AgentDlpDemoMode = $true
    Assert-GuiReject { Invoke-GuiAdd } 'Demo|데모'
    Assert-GuiTest ($script:GuiState.Calls.Count -eq 0) 'Demo assignment reached a service.'
}
Test-GuiCase 'demo mode policy listing cannot contact a service' {
    $script:AgentDlpDemoMode = $true
    Assert-GuiReject { Get-AgentDlpPolicies } 'Demo|데모'
    Assert-GuiTest ($script:GuiState.Calls.Count -eq 0) 'Demo policy listing reached a service.'
}
Test-GuiCase 'demo mode rule lookup cannot contact a service' {
    $script:AgentDlpDemoMode = $true
    Assert-GuiReject { Get-AgentDlpRules -PolicyId $script:GuiPolicyId } 'Demo|데모'
    Assert-GuiTest ($script:GuiState.Calls.Count -eq 0) 'Demo rule lookup reached a service.'
}

Write-Host ("Offline GUI checks: {0} passed, {1} failed; no tenant contacted." -f $script:GuiPassed, $script:GuiFailures.Count)
if ($script:GuiFailures.Count) { $script:GuiFailures | Write-Output; exit 1 }
