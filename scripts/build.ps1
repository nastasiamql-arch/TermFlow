$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venv = Join-Path $env:TEMP 'termflow-build-venv'
function Remove-CheckedDirectory([string]$Target, [string]$AllowedRoot) {
    $resolvedTarget = [System.IO.Path]::GetFullPath($Target)
    $resolvedRoot = [System.IO.Path]::GetFullPath($AllowedRoot).TrimEnd('\') + '\'
    if (!$resolvedTarget.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside allowed root: $resolvedTarget"
    }
    if (Test-Path -LiteralPath $resolvedTarget) { Remove-Item -LiteralPath $resolvedTarget -Recurse -Force }
}
Remove-CheckedDirectory $venv $env:TEMP
$basePython = $null
if (!$basePython -and (Get-Command uv -ErrorAction SilentlyContinue)) {
    $basePython = (& uv python find 3.12).Trim()
}
if (!$basePython -and (Get-Command py -ErrorAction SilentlyContinue)) {
    $candidate = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0) { $basePython = $candidate.Trim() }
}
if (!$basePython -or !(Test-Path -LiteralPath $basePython)) {
    throw 'Python 3.12 is required. Install Python 3.12 or Astral uv with Python 3.12 available.'
}
& $basePython -m venv $venv
& "$venv\Scripts\python.exe" -m pip install --upgrade pip
& "$venv\Scripts\python.exe" -m pip install -r requirements.lock
& "$venv\Scripts\python.exe" -m pip install -e . --no-deps
Remove-CheckedDirectory (Join-Path $root 'build') $root
Remove-CheckedDirectory (Join-Path $root 'dist') $root
& "$venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean TermFlow.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
if (!(Test-Path dist\TermFlow.exe)) { throw "Build did not produce dist\TermFlow.exe" }
Write-Host "Built $root\dist\TermFlow.exe"
