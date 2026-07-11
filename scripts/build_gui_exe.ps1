param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

if ($Clean) {
    foreach ($target in @((Join-Path $ProjectRoot "build"), (Join-Path $ProjectRoot "dist"))) {
        $resolved = [IO.Path]::GetFullPath($target)
        $rootResolved = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
        if (-not $resolved.StartsWith($rootResolved, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a path outside the project: $resolved"
        }
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -LiteralPath $resolved
    }
}

& $Python -m pip install pyinstaller --disable-pip-version-check --quiet
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Python -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name BossAgent `
    --add-data "$ProjectRoot\dashboard.html;." `
    --add-data "$ProjectRoot\web_script.js;." `
    --collect-all multipart `
    --collect-all pydantic `
    (Join-Path $ProjectRoot "bossagent_gui.py")

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Built: $(Join-Path $ProjectRoot 'dist\BossAgent.exe')" -ForegroundColor Green
