#requires -Version 7.0
<#
.SYNOPSIS
    Preview or create a separate Purview Application DLP policy for UploadText.
.DESCRIPTION
    Repository adaptation of the supplied example, checked against Microsoft Learn.
    Default: offline JSON preview only. -Apply requires an already connected,
    authorized Security & Compliance PowerShell session. No automatic connection,
    module installation, existing-policy update, or credential storage is performed.
    Creates a DISABLED policy, creates and checks its rule, then sets the chosen mode.
    Only UploadText=Block is included. No DownloadText-block or Audit-action guarantee.
.PARAMETER ConfigPath
    PowerShell data file copied from purview_app_policy.example.psd1.
.PARAMETER Apply
    Create the reviewed policy and rule in the currently connected tenant.
    Omit this switch to preview; Security & Compliance cmdlets do not support WhatIf.
.LINK
    https://learn.microsoft.com/en-us/purview/developer/configurepurview
.LINK
    https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/new-dlpcompliancerule?view=exchange-ps#example-4
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'purview_app_policy.example.psd1'),
    [switch]$Apply
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Keys($Value, [string[]]$Keys, [string]$Label) {
    if ($Value -isnot [System.Collections.IDictionary]) { throw "$Label must be a hashtable." }
    foreach ($key in $Keys) {
        if (-not $Value.Contains($key)) { throw "$Label is missing '$key'." }
    }
    foreach ($key in $Value.Keys) {
        if ($key -notin $Keys) { throw "$Label has an unsupported setting '$key'." }
    }
}
function Assert-Text($Value, [string]$Label) {
    if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace($Value) -or
        $Value -ne $Value.Trim() -or $Value -match '[<>\r\n]' -or
        $Value -match '^(YOUR_|REPLACE_)') { throw "Replace $Label with a nonempty actual value." }
}
function Assert-Strings($Value, [string]$Label, [string[]]$Special = @()) {
    if ($Value -isnot [array]) { throw "$Label must be an array, for example @('user@example.com')." }
    $seen = @{}
    foreach ($item in $Value) {
        Assert-Text $item $Label
        if ($item -notin $Special -and $item -notmatch '^[^\s@*]+@[^\s@*]+\.[^\s@*]+$') {
            throw "$Label requires explicit email addresses or a supported recipient token."
        }
        if ($seen.ContainsKey($item)) { throw "$Label contains a duplicate entry." }
        $seen[$item] = $true
    }
}
function Assert-Integer($Value, [string]$Label) {
    if ($Value -isnot [int] -and $Value -isnot [long]) { throw "$Label must be an integer." }
    if ($Value -lt [int]::MinValue -or $Value -gt [int]::MaxValue) { throw "$Label is out of range." }
}

$resolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).ProviderPath
if ([IO.Path]::GetExtension($resolvedConfig) -ine '.psd1') { throw 'ConfigPath must be a .psd1 data file.' }
$config = Import-PowerShellDataFile -LiteralPath $resolvedConfig
Assert-Keys $config @('PolicyName', 'RuleName', 'Mode', 'Applications', 'TestUsers', 'AllUsers',
    'SensitiveTypes', 'AlertRecipients', 'IncidentRecipients', 'NotifyRecipients',
    'IncidentReportContent', 'ReportSeverityLevel') 'Configuration'
Assert-Text $config.PolicyName 'PolicyName'
Assert-Text $config.RuleName 'RuleName'
Assert-Text $config.Mode 'Mode'
if ($config.Mode -notin @('Enable', 'Disable', 'TestWithNotifications', 'TestWithoutNotifications')) {
    throw 'Mode must be Enable, Disable, TestWithNotifications, or TestWithoutNotifications.'
}
if ($config.AllUsers -isnot [bool]) { throw 'AllUsers must be $true or $false.' }
if ($config.TestUsers -isnot [array]) { throw 'TestUsers must be an array of @{Upn; ObjectId} entries.' }
if (($config.AllUsers -and $config.TestUsers.Count -ne 0) -or
    (-not $config.AllUsers -and $config.TestUsers.Count -eq 0)) {
    throw 'Choose explicit TestUsers, or set AllUsers=$true with TestUsers=@().'
}
$userUpns = @{}
$userIds = @{}
$verifiedUsers = @(foreach ($user in $config.TestUsers) {
    Assert-Keys $user @('Upn', 'ObjectId') 'TestUser'
    Assert-Text $user.Upn 'TestUser.Upn'
    Assert-Strings @($user.Upn) 'TestUser.Upn'
    Assert-Text $user.ObjectId 'TestUser.ObjectId'
    $parsedUserId = [guid]::Empty
    if (-not [guid]::TryParse($user.ObjectId, [ref]$parsedUserId) -or $parsedUserId -eq [guid]::Empty) {
        throw 'TestUser.ObjectId must be the nonempty GUID of that user in the target tenant.'
    }
    $userId = $parsedUserId.ToString()
    if ($userUpns.ContainsKey($user.Upn) -or $userIds.ContainsKey($userId)) { throw 'TestUsers contains a duplicate UPN or ObjectId.' }
    $userUpns[$user.Upn] = $true
    $userIds[$userId] = $true
    @{ Upn = $user.Upn; ObjectId = $userId }
})
if ($config.Applications -isnot [array] -or $config.Applications.Count -eq 0) {
    throw 'Applications must contain at least one application hashtable.'
}
$appIds = @{}
$locations = @(foreach ($app in $config.Applications) {
    Assert-Keys $app @('AppId', 'AppName') 'Application'
    Assert-Text $app.AppId 'AppId'
    Assert-Text $app.AppName 'AppName'
    $parsedId = [guid]::Empty
    if (-not [guid]::TryParse($app.AppId, [ref]$parsedId) -or $parsedId -eq [guid]::Empty) {
        throw 'AppId must be a nonempty application/child-agent GUID.'
    }
    $appId = $parsedId.ToString()
    if ($appIds.ContainsKey($appId)) { throw 'Applications contains a duplicate AppId.' }
    $appIds[$appId] = $true
    $inclusions = if ($config.AllUsers) { @(@{ Type = 'Tenant'; Identity = 'All' }) }
        else { @($verifiedUsers | ForEach-Object { @{ Type = 'IndividualResource'; Identity = $_.Upn } }) }
    @{
        Workload = 'Applications'; Location = $appId; LocationDisplayName = $app.AppName
        LocationSource = 'Entra'; LocationType = 'Individual'; Inclusions = @($inclusions)
    }
})
if ($config.SensitiveTypes -isnot [array] -or $config.SensitiveTypes.Count -eq 0) {
    throw 'SensitiveTypes must contain at least one SIT condition.'
}
$sitNames = @{}
$conditions = @(foreach ($sit in $config.SensitiveTypes) {
    Assert-Keys $sit @('Name', 'MinConfidence', 'MaxConfidence', 'MinCount', 'MaxCount') 'SensitiveType'
    Assert-Text $sit.Name 'SensitiveType.Name'
    if ($sitNames.ContainsKey($sit.Name)) { throw 'SensitiveTypes contains a duplicate Name.' }
    $sitNames[$sit.Name] = $true
    foreach ($key in @('MinConfidence', 'MaxConfidence', 'MinCount', 'MaxCount')) {
        Assert-Integer $sit[$key] "SensitiveType.$key"
    }
    if ($sit.MinConfidence -lt 1 -or $sit.MaxConfidence -gt 100 -or $sit.MinConfidence -gt $sit.MaxConfidence) {
        throw 'SIT confidence must satisfy 1 <= MinConfidence <= MaxConfidence <= 100.'
    }
    if ($sit.MinCount -lt 1 -or ($sit.MaxCount -ne -1 -and $sit.MaxCount -lt $sit.MinCount)) {
        throw 'SIT counts require MinCount >= 1 and MaxCount = -1 or MaxCount >= MinCount.'
    }
    @{
        Name = $sit.Name; minconfidence = [string]$sit.MinConfidence; maxconfidence = [string]$sit.MaxConfidence
        mincount = [string]$sit.MinCount; maxcount = [string]$sit.MaxCount
    }
})
Assert-Strings $config.AlertRecipients 'AlertRecipients' @('SiteAdmin')
Assert-Strings $config.IncidentRecipients 'IncidentRecipients' @('SiteAdmin')
Assert-Strings $config.NotifyRecipients 'NotifyRecipients' @('SiteAdmin', 'Owner', 'LastModifier')
Assert-Text $config.ReportSeverityLevel 'ReportSeverityLevel'
if ($config.ReportSeverityLevel -notin @('Low', 'Medium', 'High')) { throw 'Invalid ReportSeverityLevel.' }
$validReportFields = @('All', 'Default', 'DetectionDetails', 'Detections', 'DocumentAuthor',
    'DocumentLastModifier', 'MatchedItem', 'OriginalContent', 'RulesMatched', 'Service', 'Severity', 'Title')
if ($config.IncidentReportContent -isnot [array] -or $config.IncidentReportContent.Count -eq 0 -or
    @($config.IncidentReportContent | Where-Object { $_ -notin $validReportFields }).Count -gt 0) {
    throw 'IncidentReportContent must be a nonempty array of documented report fields.'
}
if (($config.IncidentReportContent -contains 'All' -or $config.IncidentReportContent -contains 'Default') -and
    $config.IncidentReportContent.Count -ne 1) { throw 'Use All or Default alone in IncidentReportContent.' }
if (@($config.IncidentReportContent | Sort-Object -Unique).Count -ne $config.IncidentReportContent.Count) {
    throw 'IncidentReportContent contains a duplicate field.'
}

$actions = @(@{ setting = 'UploadText'; value = 'Block' })
$plan = [ordered]@{
    PolicyName = $config.PolicyName; RuleName = $config.RuleName; Mode = $config.Mode
    TenantWideScope = $config.AllUsers; TestUsers = $verifiedUsers
    EnforcementPlanes = @('Application'); Locations = $locations
    ContentContainsSensitiveInformation = $conditions; RestrictAccess = $actions
    Notifications = @{
        AlertRecipients = $config.AlertRecipients; IncidentRecipients = $config.IncidentRecipients
        NotifyRecipients = $config.NotifyRecipients; IncidentReportContent = $config.IncidentReportContent
    }
    ReportSeverityLevel = $config.ReportSeverityLevel; StopPolicyProcessing = $false
}
ConvertTo-Json -InputObject $plan -Depth 15
if ($config.Mode -ne 'Enable') { Write-Warning 'This mode does NOT enforce a live content block.' }
if (-not $Apply) {
    Write-Host 'PREVIEW ONLY: no tenant connection, lookup, notification, or policy change was performed.'
    Write-Host 'After review, connect to the intended tenant in Security & Compliance PowerShell and add -Apply.'
    return
}

foreach ($command in @('Get-DlpCompliancePolicy', 'Get-DlpComplianceRule', 'Get-DlpSensitiveInformationType',
    'New-DlpCompliancePolicy', 'New-DlpComplianceRule', 'Set-DlpCompliancePolicy')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing $command. Connect an authorized Security & Compliance PowerShell session first."
    }
}
# A lookup failure is never treated as proof that an object does not exist.
function ConvertTo-FieldMap($Value) {
    $jsonMap = $Value | ConvertTo-Json -Depth 15 | ConvertFrom-Json -AsHashtable
    $result = @{}
    foreach ($entry in $jsonMap.GetEnumerator()) { $result[$entry.Key] = $entry.Value }
    return $result
}
$existingPolicies = @(Get-DlpCompliancePolicy -ErrorAction Stop)
$existingRules = @(Get-DlpComplianceRule -ErrorAction Stop)
if (@($existingPolicies | Where-Object Name -eq $config.PolicyName).Count -gt 0 -or
    @($existingRules | Where-Object Name -eq $config.RuleName).Count -gt 0) {
    throw 'The policy or rule name already exists. This create-only script does not modify existing objects.'
}
$resolvedTypes = @{}
$resolvedIdentities = @{}
foreach ($condition in $conditions) {
    $found = @(Get-DlpSensitiveInformationType -Identity $condition.Name -ErrorAction Stop)
    if ($found.Count -ne 1) { throw "Sensitive information type '$($condition.Name)' did not resolve uniquely." }
    $details = ConvertTo-FieldMap $found[0]
    $identifiers = @(@('Name', 'Id', 'Identity', 'Guid') | ForEach-Object {
        if (-not [string]::IsNullOrWhiteSpace([string]$details[$_])) { [string]$details[$_] }
    } | Sort-Object -Unique)
    if ($condition.Name -notin $identifiers) { throw "Sensitive information type '$($condition.Name)' resolved to a different identity." }
    foreach ($identifier in $identifiers) {
        if ($resolvedIdentities.ContainsKey($identifier)) { throw 'Two SensitiveTypes entries resolve to the same SIT.' }
        $resolvedIdentities[$identifier] = $true
    }
    $resolvedTypes[$condition.Name] = $identifiers
}

function Assert-PolicyReadback($Policy, [string]$ExpectedId, [string]$ExpectedMode) {
    if ([string]$Policy.Guid -ine $ExpectedId -or $Policy.Name -ine $config.PolicyName -or
        [string]$Policy.Mode -ine $ExpectedMode -or @($Policy.EnforcementPlanes).Count -ne 1 -or
        [string]@($Policy.EnforcementPlanes)[0] -ine 'Application') { throw 'Policy identity, mode, or enforcement-plane readback differs.' }
    $rawLocations = if ($Policy.Locations -is [string]) { $Policy.Locations }
        else { ConvertTo-Json -InputObject @($Policy.Locations) -Depth 15 -Compress }
    $actualLocations = @(ConvertFrom-Json -InputObject $rawLocations -AsHashtable)
    if ($actualLocations.Count -ne $locations.Count) { throw 'Policy application scope differs from the plan.' }
    foreach ($expected in $locations) {
        $matching = @($actualLocations | Where-Object Location -eq $expected.Location)
        if ($matching.Count -ne 1 -or $matching[0].Workload -ine 'Applications' -or
            $matching[0].LocationSource -ine 'Entra' -or $matching[0].LocationType -ine 'Individual') {
            throw 'Policy application location differs.'
        }
        $actual = ConvertTo-FieldMap $matching[0]
        $actualUsers = @($actual.Inclusions)
        if ($actualUsers.Count -ne @($expected.Inclusions).Count -or
            ($null -ne $actual['Exclusions'] -and @($actual.Exclusions).Count -gt 0)) {
            throw 'Policy user inclusion/exclusion readback differs from the plan.'
        }
        if ($config.AllUsers) {
            if ($actualUsers[0].Type -ine 'Tenant' -or $actualUsers[0].Identity -ine 'All') {
                throw 'Policy tenant-wide inclusion readback differs from the plan.'
            }
        }
        else {
            foreach ($user in $verifiedUsers) {
                $matchedUsers = @($actualUsers | Where-Object {
                    $_.Type -ieq 'IndividualResource' -and [string]$_.Identity -in @($user.Upn, $user.ObjectId)
                })
                if ($matchedUsers.Count -ne 1) { throw 'Policy user inclusion readback differs from the approved UPN/ObjectId pairs.' }
            }
        }
    }
}
function Assert-RuleReadback($Rule, [string]$ExpectedId, [string]$PolicyId) {
    if ([string]$Rule.Guid -ine $ExpectedId -or $Rule.Name -ine $config.RuleName -or
        [string]$Rule.Policy -notin @($PolicyId, $config.PolicyName) -or [string]$Rule.Disabled -ine 'False' -or
        [string]$Rule.StopPolicyProcessing -ine 'False') {
        throw 'Rule identity, parent policy, or enabled state differs from the plan.'
    }
    if (@($Rule.RestrictAccess).Count -ne 1 -or @($Rule.RestrictAccess)[0].setting -ine 'UploadText' -or
        @($Rule.RestrictAccess)[0].value -ine 'Block') { throw 'Rule UploadText action readback differs.' }
    $actualConditions = @($Rule.ContentContainsSensitiveInformation)
    if ($actualConditions.Count -ne $conditions.Count) { throw 'Rule SIT count differs from the plan.' }
    foreach ($expected in $conditions) {
        $expectedIdentities = $resolvedTypes[$expected.Name]
        $matching = @($actualConditions | Where-Object {
            $item = ConvertTo-FieldMap $_
            $item['name'] -in $expectedIdentities -or $item['id'] -in $expectedIdentities
        })
        if ($matching.Count -ne 1) { throw 'Rule SIT identity readback differs from the plan.' }
        $actual = ConvertTo-FieldMap $matching[0]
        foreach ($field in @('minconfidence', 'maxconfidence', 'mincount', 'maxcount')) {
            if ([string]$actual[$field] -ne [string]$expected[$field]) { throw "Rule SIT $field readback differs." }
        }
    }
}

$createdPolicyId = $null
$activationAttempted = $false
try {
    $created = @(New-DlpCompliancePolicy -Name $config.PolicyName -Mode Disable -EnforcementPlanes @('Application') `
        -Locations (ConvertTo-Json -InputObject $locations -Depth 15 -Compress) `
        -Comment 'Custom AI application: complete-text UploadText DLP evaluation.' -ErrorAction Stop)
    if ($created.Count -ne 1 -or -not $created[0].Guid) { throw 'No unique policy GUID returned. Inspect the new disabled policy before retrying.' }
    $createdPolicyId = [string]$created[0].Guid
    $ruleParams = @{
        Name = $config.RuleName; Policy = $createdPolicyId; Disabled = $false
        ContentContainsSensitiveInformation = $conditions; RestrictAccess = $actions
        StopPolicyProcessing = $false; ReportSeverityLevel = $config.ReportSeverityLevel
        Comment = 'UploadText content block. Output inline protection requires separate validation.'
        ErrorAction = 'Stop'
    }
    if ($config.AlertRecipients.Count) { $ruleParams.GenerateAlert = $config.AlertRecipients }
    if ($config.IncidentRecipients.Count) {
        $ruleParams.GenerateIncidentReport = $config.IncidentRecipients
        $ruleParams.IncidentReportContent = $config.IncidentReportContent
    }
    if ($config.NotifyRecipients.Count) { $ruleParams.NotifyUser = $config.NotifyRecipients }
    $newRule = @(New-DlpComplianceRule @ruleParams)
    if ($newRule.Count -ne 1 -or -not $newRule[0].Guid) { throw 'No unique rule GUID returned.' }
    $ruleId = [string]$newRule[0].Guid
    $policy = Get-DlpCompliancePolicy -Identity $createdPolicyId -ErrorAction Stop
    $rule = Get-DlpComplianceRule -Identity $ruleId -ErrorAction Stop
    Assert-PolicyReadback $policy $createdPolicyId 'Disable'
    Assert-RuleReadback $rule $ruleId $createdPolicyId
    if ($config.Mode -ne 'Disable') {
        $activationAttempted = $true
        Set-DlpCompliancePolicy -Identity $createdPolicyId -Mode $config.Mode -ErrorAction Stop | Out-Null
    }
    $policy = Get-DlpCompliancePolicy -Identity $createdPolicyId -ErrorAction Stop
    Assert-PolicyReadback $policy $createdPolicyId $config.Mode
    [pscustomobject]@{ Result = 'CreatedAndReadBack'; PolicyId = $createdPolicyId; RuleId = $ruleId; Mode = [string]$policy.Mode }
    Write-Host 'Policy readback succeeded. Distribution, actual inline blocking, and portal alerts still require live validation.'
}
catch {
    if ($activationAttempted -and $createdPolicyId) {
        try {
            Set-DlpCompliancePolicy -Identity $createdPolicyId -Mode Disable -ErrorAction Stop | Out-Null
            Write-Warning 'Verification failed after activation was attempted; a disable request was sent for the newly created policy. Verify its state.'
        }
        catch { Write-Warning 'Could not confirm a disable request. The new policy might be active; its administrator must inspect its state.' }
    }
    elseif ($createdPolicyId) { Write-Warning 'Creation/verification stopped before activation. The newly created policy was created in Disable mode; inspect it before retrying.' }
    throw
}
