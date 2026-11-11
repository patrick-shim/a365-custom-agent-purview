# 공개 설정 예제 / Public configuration template. No passwords, secrets, or tokens.
# Copy this file to .local/purview-app-policy.psd1 and replace the placeholders.
@{
    PolicyName = 'OneDrive Agent - New Credit Card Policy'
    RuleName = 'OneDrive Agent - Block Credit Card UploadText'
    # Enable enforces. Test* modes simulate; Disable does not evaluate.
    Mode = 'Enable'
    Applications = @(
        @{
            # In this project's OBO flow: the CHILD Agent ID, not the blueprint.
            AppId = '<CHILD_AGENT_ID>'
            AppName = 'OneDrive Purview Agent'
        }
    )
    # These users are included for every application listed above.
    # Copy both values from the same user's profile in the target Entra tenant.
    # Purview can return the ObjectId after receiving the UPN.
    TestUsers = @(
        @{ Upn = '<TEST_USER_UPN>'; ObjectId = '<USER_OBJECT_ID>' }
    )
    # Tenant-wide inclusion is explicit: set true AND set TestUsers = @().
    AllUsers = $false
    SensitiveTypes = @(
        @{
            Name = 'Credit Card Number'
            MinConfidence = 85
            MaxConfidence = 100
            MinCount = 1
            MaxCount = -1
        }
    )
    # Optional notifications: leave empty unless approved recipients are required.
    AlertRecipients = @()
    IncidentRecipients = @()
    NotifyRecipients = @()
    # Used only with IncidentRecipients. Default or All must be used alone.
    IncidentReportContent = @('RulesMatched', 'Service', 'Severity', 'Title')
    ReportSeverityLevel = 'High'
}
