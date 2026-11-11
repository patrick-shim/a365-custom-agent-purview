#requires -Version 7.0
<#
.SYNOPSIS
    Offline checks for the Purview policy creation script. No tenant is contacted.
.DESCRIPTION
    Every Exchange command used by the target is replaced with a local function.
    Run with: pwsh -NoProfile -File tests/test_purview_policy_script.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
# Global state lets mock functions retain their state when called by another script.
# Refuse to overwrite a caller's variable; remove only this test state on exit.
if (Get-Variable PurviewPolicyTestState -Scope Global -ErrorAction SilentlyContinue) { throw 'Test state already exists.' }
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'scripts/new_purview_app_policy.ps1'
$template = Join-Path $root 'scripts/purview_app_policy.example.psd1'
$localRoot = [IO.Path]::GetFullPath((Join-Path $root '.local'))
$testRoot = Join-Path $localRoot ('policy-script-tests-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testRoot -Force
$script:passed = 0
$script:failures = [Collections.Generic.List[string]]::new()

function Reset-Fake {
    $global:PurviewPolicyTestState = @{
        Scenario = ''; Calls = [Collections.Generic.List[string]]::new()
        Writes = [Collections.Generic.List[string]]::new()
        Policy = $null; Rule = $null; RuleArguments = @{}
    }
}
function Get-DlpCompliancePolicy {
    [CmdletBinding()] param([string]$Identity)
    $global:PurviewPolicyTestState.Calls.Add('GetPolicy')
    if ($global:PurviewPolicyTestState.Scenario -eq 'LookupDenied') { throw 'Fake authorization denied.' }
    if (-not $Identity) {
        if ($global:PurviewPolicyTestState.Scenario -eq 'ExistingPolicy') { [pscustomobject]@{Name='Offline policy'} }
        return
    }
    if ($global:PurviewPolicyTestState.Scenario -eq 'WrongScope') {
        $copy = $global:PurviewPolicyTestState.Policy.PSObject.Copy()
        $copy.Locations = '[]'
        return $copy
    }
    if ($global:PurviewPolicyTestState.Scenario -eq 'ActivationReadbackBad' -and $global:PurviewPolicyTestState.Policy.Mode -eq 'Enable') {
        $copy = $global:PurviewPolicyTestState.Policy.PSObject.Copy(); $copy.Mode = 'Disable'; return $copy
    }
    if ($global:PurviewPolicyTestState.Scenario -in @('GuidUserReadback','UnapprovedUserReadback')) {
        $copy = $global:PurviewPolicyTestState.Policy.PSObject.Copy()
        $locations = @($copy.Locations | ConvertFrom-Json -AsHashtable)
        foreach ($location in $locations) {
            foreach ($included in $location.Inclusions) {
                $included.Identity = if ($global:PurviewPolicyTestState.Scenario -eq 'UnapprovedUserReadback') { '99999999-9999-4999-8999-999999999999' }
                    elseif ($included.Identity -eq 'tester@example.com') { '11111111-1111-4111-8111-111111111111' }
                    else { '22222222-2222-4222-8222-222222222222' }
            }
        }
        $copy.Locations = ConvertTo-Json -InputObject $locations -Depth 15 -Compress
        return $copy
    }
    return $global:PurviewPolicyTestState.Policy
}
function Get-DlpComplianceRule {
    [CmdletBinding()] param([string]$Identity)
    $global:PurviewPolicyTestState.Calls.Add('GetRule')
    if ($global:PurviewPolicyTestState.Scenario -eq 'RulesLookupDenied') { throw 'Fake rule lookup denied.' }
    if (-not $Identity) {
        if ($global:PurviewPolicyTestState.Scenario -eq 'ExistingRule') { [pscustomobject]@{Name='Offline rule'} }
        return
    }
    if ($global:PurviewPolicyTestState.Scenario -eq 'WrongParent') {
        $copy = $global:PurviewPolicyTestState.Rule.PSObject.Copy()
        $copy.Policy = 'A different policy'
        return $copy
    }
    if ($global:PurviewPolicyTestState.Scenario -eq 'WrongAction') { $global:PurviewPolicyTestState.Rule.RestrictAccess = @(@{setting='UploadText';value='Allow'}) }
    if ($global:PurviewPolicyTestState.Scenario -eq 'WrongThreshold') { $global:PurviewPolicyTestState.Rule.ContentContainsSensitiveInformation[0].mincount = '99' }
    if ($global:PurviewPolicyTestState.Scenario -eq 'SitIdReadback') {
        $global:PurviewPolicyTestState.Rule.ContentContainsSensitiveInformation[0].Name = '50842eb7-edc8-4019-85dd-5a5c1f2bb085'
    }
    return $global:PurviewPolicyTestState.Rule
}
function Get-DlpSensitiveInformationType {
    [CmdletBinding()] param([string]$Identity)
    $global:PurviewPolicyTestState.Calls.Add('GetSIT')
    if ($global:PurviewPolicyTestState.Scenario -eq 'MissingSIT') { throw 'Fake SIT not found.' }
    if ($global:PurviewPolicyTestState.Scenario -eq 'WrongSIT') {
        return [pscustomobject]@{Name='Different sensitive type';Identity='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'}
    }
    [pscustomobject]@{
        Name=$Identity; Identity='50842eb7-edc8-4019-85dd-5a5c1f2bb085'
        Id='50842eb7-edc8-4019-85dd-5a5c1f2bb085'
    }
}
function New-DlpCompliancePolicy {
    [CmdletBinding()] param($Name, $Mode, $Locations, $EnforcementPlanes, $Comment)
    $global:PurviewPolicyTestState.Writes.Add('NewPolicy:' + $Mode)
    $global:PurviewPolicyTestState.Calls.Add('NewPolicy:' + $Mode)
    $global:PurviewPolicyTestState.Policy = [pscustomobject]@{
        Name=$Name; Guid='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        Identity='cccccccc-cccc-4ccc-8ccc-cccccccccccc'; Mode=$Mode
        Locations=$Locations; EnforcementPlanes=$EnforcementPlanes
    }
    return $global:PurviewPolicyTestState.Policy
}
function New-DlpComplianceRule {
    [CmdletBinding()] param(
        $Name, $Policy, $ContentContainsSensitiveInformation, $RestrictAccess,
        $Disabled, $ReportSeverityLevel, $StopPolicyProcessing, $Comment,
        $GenerateAlert, $GenerateIncidentReport, $NotifyUser, $IncidentReportContent
    )
    $global:PurviewPolicyTestState.Writes.Add('NewRule')
    $global:PurviewPolicyTestState.Calls.Add('NewRule')
    if ($global:PurviewPolicyTestState.Scenario -eq 'RuleFailure') { throw 'Fake rule creation failed.' }
    $global:PurviewPolicyTestState.RuleArguments = @{} + $PSBoundParameters
    $global:PurviewPolicyTestState.Rule = [pscustomobject]@{
        Name=$Name; Guid='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        Identity='dddddddd-dddd-4ddd-8ddd-dddddddddddd'; Policy=$Policy
        Disabled=$Disabled; RestrictAccess=$RestrictAccess; StopPolicyProcessing=$StopPolicyProcessing
        ContentContainsSensitiveInformation=@($ContentContainsSensitiveInformation | ForEach-Object { @{} + $_ })
    }
    return $global:PurviewPolicyTestState.Rule
}
function Set-DlpCompliancePolicy {
    [CmdletBinding()] param($Identity, $Mode)
    if ($Identity -notin @($global:PurviewPolicyTestState.Policy.Guid, $global:PurviewPolicyTestState.Policy.Name)) {
        throw 'The target attempted to change a different policy.'
    }
    $global:PurviewPolicyTestState.Writes.Add('SetMode:' + $Mode)
    $global:PurviewPolicyTestState.Calls.Add('SetMode:' + $Mode)
    $global:PurviewPolicyTestState.Policy.Mode = $Mode
}

function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function New-Config {
    $config = Import-PowerShellDataFile -LiteralPath $template
    $config.PolicyName = 'Offline policy'
    $config.RuleName = 'Offline rule'
    $config.Applications = @(@{AppId='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';AppName='Offline app'})
    $config.TestUsers = @(@{Upn='tester@example.com';ObjectId='11111111-1111-4111-8111-111111111111'})
    return $config
}
function ConvertTo-DataLiteral($Value) {
    if ($Value -is [Collections.IDictionary]) {
        $entries = foreach ($key in $Value.Keys) { (ConvertTo-DataLiteral ([string]$key)) + '=' + (ConvertTo-DataLiteral $Value[$key]) }
        return '@{' + ($entries -join ';') + '}'
    }
    if ($Value -is [bool]) { if ($Value) { return '$true' }; return '$false' }
    if ($Value -is [string]) { return "'" + $Value.Replace("'", "''") + "'" }
    if ($Value -is [Collections.IEnumerable]) {
        $items = foreach ($item in $Value) { ConvertTo-DataLiteral $item }
        return '@(' + ($items -join ';') + ')'
    }
    if ($null -eq $Value) { return '$null' }
    return [Convert]::ToString($Value, [Globalization.CultureInfo]::InvariantCulture)
}
function Invoke-Target($Config, [switch]$Apply) {
    $path = Join-Path $testRoot 'case.psd1'
    Set-Content -LiteralPath $path -Value (ConvertTo-DataLiteral $Config) -Encoding utf8
    $output = @(& $target -ConfigPath $path -Apply:$Apply 6>$null 3>$null)
    if (-not $Apply) { return (($output -join "`n") | ConvertFrom-Json -AsHashtable) }
}
function Assert-Rejected($Config, [switch]$Apply, [switch]$AfterCreate, [string]$ExpectedError) {
    $thrown = $false
    try { $null = Invoke-Target $Config -Apply:$Apply } catch {
        $thrown = $true
        if ($ExpectedError) { Assert-True ($_.Exception.Message -match $ExpectedError) ('Unexpected rejection: ' + $_.Exception.Message) }
    }
    Assert-True $thrown 'Expected rejection, but the operation completed.'
    if (-not $AfterCreate) { Assert-True ($global:PurviewPolicyTestState.Writes.Count -eq 0) 'A rejected operation performed a write.' }
    Assert-True (@($global:PurviewPolicyTestState.Writes | Where-Object { $_ -like 'SetMode:*' }).Count -eq 0) 'A failed operation activated or changed policy mode.'
}
function Test-Case([string]$Name, [scriptblock]$Body) {
    Reset-Fake
    try { & $Body; $script:passed++; Write-Host ('PASS ' + $Name) }
    catch { $script:failures.Add($Name + ': ' + $_.Exception.Message); Write-Host ('FAIL ' + $Name) }
}

try {
    Test-Case 'offline preview preserves one-element location array' {
        $plan = Invoke-Target (New-Config)
        Assert-True ($global:PurviewPolicyTestState.Calls.Count -eq 0 -and $global:PurviewPolicyTestState.Writes.Count -eq 0) 'Preview contacted a service.'
        Assert-True ($plan.Locations -is [array] -and $plan.Locations.Count -eq 1) 'Single application lost array shape.'
        Assert-True ($plan.Locations[0].Inclusions[0].Type -eq 'IndividualResource') 'Preview broadened selected-user scope.'
    }
    Test-Case 'multiple applications retain the selected users' {
        $c = New-Config; $c.Applications += @{AppId='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';AppName='Second app'}
        $c.TestUsers += @{Upn='second@example.com';ObjectId='22222222-2222-4222-8222-222222222222'}; $p = Invoke-Target $c
        Assert-True ($p.Locations.Count -eq 2) 'An application was lost.'
        foreach ($location in $p.Locations) { Assert-True ($location.Inclusions.Count -eq 2) 'User scope differs between applications.' }
    }
    Test-Case 'tenant-wide scope is explicit' {
        $c=New-Config; $c.AllUsers=$true; $c.TestUsers=@(); $p=Invoke-Target $c
        Assert-True ($p.Locations[0].Inclusions[0].Type -eq 'Tenant' -and $p.Locations[0].Inclusions[0].Identity -eq 'All') 'Explicit tenant scope was not represented.'
    }
    Test-Case 'placeholder application rejected' { $c=New-Config; $c.Applications[0].AppId='<AGENT_ID>'; Assert-Rejected $c }
    Test-Case 'empty selected-user scope rejected' { $c=New-Config; $c.TestUsers=@(); Assert-Rejected $c }
    Test-Case 'tenant-wide and selected-user scopes cannot mix' { $c=New-Config; $c.AllUsers=$true; Assert-Rejected $c }
    Test-Case 'unknown policy mode rejected' { $c=New-Config; $c.Mode='Audit'; Assert-Rejected $c }
    Test-Case 'unverified action configuration rejected' { $c=New-Config; $c.RestrictAction='Audit'; Assert-Rejected $c }
    Test-Case 'unverified DownloadText configuration rejected' { $c=New-Config; $c.Activities=@('DownloadText'); Assert-Rejected $c }
    Test-Case 'duplicate application IDs rejected' { $c=New-Config; $c.Applications += $c.Applications[0]; Assert-Rejected $c }
    Test-Case 'duplicate user UPN rejected' { $c=New-Config; $c.TestUsers += @{Upn='tester@example.com';ObjectId='22222222-2222-4222-8222-222222222222'}; Assert-Rejected $c }
    Test-Case 'duplicate user object ID rejected' { $c=New-Config; $c.TestUsers += @{Upn='second@example.com';ObjectId='11111111-1111-4111-8111-111111111111'}; Assert-Rejected $c }
    Test-Case 'report Default cannot be combined with extra fields' { $c=New-Config; $c.IncidentReportContent=@('Default','Detections'); Assert-Rejected $c }
    Test-Case 'existing policy is never overwritten' { $global:PurviewPolicyTestState.Scenario='ExistingPolicy'; Assert-Rejected (New-Config) -Apply -ExpectedError 'name already exists' }
    Test-Case 'existing rule is never overwritten' { $global:PurviewPolicyTestState.Scenario='ExistingRule'; Assert-Rejected (New-Config) -Apply -ExpectedError 'name already exists' }
    Test-Case 'lookup failure is not treated as absence' { $global:PurviewPolicyTestState.Scenario='LookupDenied'; Assert-Rejected (New-Config) -Apply -ExpectedError 'Fake authorization denied' }
    Test-Case 'rule enumeration failure prevents creation' { $global:PurviewPolicyTestState.Scenario='RulesLookupDenied'; Assert-Rejected (New-Config) -Apply -ExpectedError 'Fake rule lookup denied' }
    Test-Case 'invalid SIT prevents policy creation' { $global:PurviewPolicyTestState.Scenario='MissingSIT'; Assert-Rejected (New-Config) -Apply -ExpectedError 'Fake SIT not found' }
    Test-Case 'a differently resolved SIT prevents policy creation' { $global:PurviewPolicyTestState.Scenario='WrongSIT'; Assert-Rejected (New-Config) -Apply -ExpectedError 'different identity' }
    Test-Case 'rule failure leaves new policy disabled' {
        $global:PurviewPolicyTestState.Scenario='RuleFailure'; Assert-Rejected (New-Config) -Apply -AfterCreate -ExpectedError 'Fake rule creation failed'
        Assert-True ($global:PurviewPolicyTestState.Policy.Mode -eq 'Disable') 'Failed rule left policy active.'
    }
    Test-Case 'wrong policy scope prevents activation' {
        $global:PurviewPolicyTestState.Scenario='WrongScope'; Assert-Rejected (New-Config) -Apply -AfterCreate -ExpectedError 'scope differs'
        Assert-True ($global:PurviewPolicyTestState.Policy.Mode -eq 'Disable') 'Wrong readback scope was activated.'
    }
    Test-Case 'wrong rule parent prevents activation' {
        $global:PurviewPolicyTestState.Scenario='WrongParent'; Assert-Rejected (New-Config) -Apply -AfterCreate -ExpectedError 'identity, parent policy'
        Assert-True ($global:PurviewPolicyTestState.Policy.Mode -eq 'Disable') 'Wrong rule parent was activated.'
    }
    Test-Case 'a different block action prevents activation' { $global:PurviewPolicyTestState.Scenario='WrongAction'; Assert-Rejected (New-Config) -Apply -AfterCreate -ExpectedError 'UploadText action' }
    Test-Case 'a different SIT threshold prevents activation' { $global:PurviewPolicyTestState.Scenario='WrongThreshold'; Assert-Rejected (New-Config) -Apply -AfterCreate -ExpectedError 'mincount readback differs' }
    Test-Case 'successful creation enables only after rule verification and sends no notifications by default' {
        Invoke-Target (New-Config) -Apply
        Assert-True (($global:PurviewPolicyTestState.Writes -join ',') -eq 'NewPolicy:Disable,NewRule,SetMode:Enable') 'Unexpected write order or target.'
        Assert-True (($global:PurviewPolicyTestState.Calls -join ',') -eq 'GetPolicy,GetRule,GetSIT,NewPolicy:Disable,NewRule,GetPolicy,GetRule,SetMode:Enable,GetPolicy') 'A write bypassed lookup or readback verification.'
        Assert-True ($global:PurviewPolicyTestState.Policy.Locations.TrimStart().StartsWith('[')) 'Single application Locations was not sent as a JSON array.'
        foreach ($field in @('GenerateAlert','GenerateIncidentReport','NotifyUser')) {
            Assert-True (-not $global:PurviewPolicyTestState.RuleArguments.ContainsKey($field)) ('Unexpected notification setting: ' + $field)
        }
        Assert-True ($global:PurviewPolicyTestState.Rule.RestrictAccess.Count -eq 1 -and $global:PurviewPolicyTestState.Rule.RestrictAccess[0].setting -eq 'UploadText') 'An unverified activity was configured.'
    }
    Test-Case 'resolved SIT ID is accepted in service readback' { $global:PurviewPolicyTestState.Scenario='SitIdReadback'; Invoke-Target (New-Config) -Apply; Assert-True ($global:PurviewPolicyTestState.Policy.Mode -eq 'Enable') 'Verified SIT ID readback was rejected.' }
    Test-Case 'approved user object IDs are accepted in service readback' {
        $global:PurviewPolicyTestState.Scenario='GuidUserReadback'; $c=New-Config
        $c.TestUsers += @{Upn='second@example.com';ObjectId='22222222-2222-4222-8222-222222222222'}
        Invoke-Target $c -Apply; Assert-True ($global:PurviewPolicyTestState.Policy.Mode -eq 'Enable') 'Approved user GUID readback was rejected.'
    }
    Test-Case 'an unapproved user object ID prevents activation' { $global:PurviewPolicyTestState.Scenario='UnapprovedUserReadback'; Assert-Rejected (New-Config) -Apply -AfterCreate -ExpectedError 'approved UPN/ObjectId pairs' }
    Test-Case 'simulation does not silently enable enforcement' {
        $c=New-Config; $c.Mode='TestWithoutNotifications'; Invoke-Target $c -Apply
        Assert-True ($global:PurviewPolicyTestState.Policy.Mode -eq 'TestWithoutNotifications') 'Simulation was enabled as enforcement.'
    }
    Test-Case 'verification failure after activation requests disable of only the new policy' {
        $global:PurviewPolicyTestState.Scenario='ActivationReadbackBad'; $failed=$false
        try { Invoke-Target (New-Config) -Apply } catch { $failed=$true }
        Assert-True $failed 'A mismatched final mode was accepted.'
        Assert-True (($global:PurviewPolicyTestState.Writes -join ',') -eq 'NewPolicy:Disable,NewRule,SetMode:Enable,SetMode:Disable') 'Activation verification did not disable the new policy.'
        Assert-True ($global:PurviewPolicyTestState.Policy.Mode -eq 'Disable') 'The policy remained active after failed verification.'
    }
}
finally {
    Remove-Variable PurviewPolicyTestState -Scope Global -ErrorAction SilentlyContinue
    $resolved = [IO.Path]::GetFullPath($testRoot)
    if ([IO.Path]::GetDirectoryName($resolved) -ne $localRoot -or [IO.Path]::GetFileName($resolved) -notlike 'policy-script-tests-*') {
        throw 'Refusing to remove an unexpected test directory.'
    }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}

Write-Host ("Offline policy-script checks: {0} passed, {1} failed; no tenant contacted." -f $script:passed, $script:failures.Count)
if ($script:failures.Count) { $script:failures | Write-Output; exit 1 }
