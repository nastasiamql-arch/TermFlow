$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& "$PSScriptRoot\build.ps1"
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (!$iscc) {
    $candidates = @(
        'C:\Program Files\Inno Setup 6\ISCC.exe',
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (!$iscc) { throw 'Inno Setup 6 (ISCC.exe) is required. Install it from https://jrsoftware.org/isdl.php' }
$version = (Select-String -Path src\termflow\version.py -Pattern '"([0-9]+\.[0-9]+\.[0-9]+)"').Matches.Groups[1].Value
& $iscc "/DAppVersion=$version" installer\TermFlow.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed: $LASTEXITCODE" }
$file = Join-Path $root 'installer\output\TermFlow-Setup-x64.exe'
$hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$file.sha256" -Value "$hash  TermFlow-Setup-x64.exe" -NoNewline
Write-Host "Built $file"
Write-Host "SHA256 $hash"
