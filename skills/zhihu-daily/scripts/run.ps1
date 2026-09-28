param(
    [Parameter(Mandatory=$true, Position=0)][string]$Action,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest
)
$ErrorActionPreference = 'Stop'
$workspace = 'F:\codexCoding\dailyZhihu'
$secretFile = Join-Path $workspace '.private\zhihu-secret.dpapi'
$env:PYTHONIOENCODING = 'utf-8'
try {
    if (($Action -in @('hot', 'answers')) -or ($Action -eq 'prepare' -and $Rest -notcontains '--offline')) {
        $protected = (Get-Content -LiteralPath $secretFile -Raw).Trim()
        $secure = ConvertTo-SecureString $protected
        $env:ZHIHU_ACCESS_SECRET = [System.Net.NetworkCredential]::new('', $secure).Password
    }
    $scriptName = if ($Action -in @('prepare','classify','build','mail','record')) { 'pipeline.py' } else { 'daily.py' }
    & python (Join-Path $PSScriptRoot $scriptName) --workspace $workspace $Action @Rest
    $resultCode = $LASTEXITCODE
} finally {
    Remove-Item Env:\ZHIHU_ACCESS_SECRET -ErrorAction SilentlyContinue
}
exit $resultCode
