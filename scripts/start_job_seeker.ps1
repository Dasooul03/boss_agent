param(
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    $OutputEncoding = [Text.Encoding]::UTF8
} catch {
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BossUrl = "https://www.zhipin.com/web/geek/job"

function Write-Info {
    param([string]$Message)
    Write-Host "[Job Seeker] $Message" -ForegroundColor Cyan
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[Job Seeker] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[Job Seeker] $Message" -ForegroundColor Red
}

function Pause-And-Exit {
    param([int]$Code)
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit $Code
}

function Get-ConfigValue {
    param(
        [object]$Config,
        [string]$Name,
        [object]$Default
    )
    if ($null -eq $Config) {
        return $Default
    }
    $property = $Config.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value -or "$($property.Value)" -eq "") {
        return $Default
    }
    return $property.Value
}

function Test-TcpPort {
    param([int]$Port)
    $client = New-Object Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-JobSeekerHealth {
    param([int]$Port)
    try {
        $result = Invoke-RestMethod -Uri "http://127.0.0.1:${Port}/health" -Method Get -TimeoutSec 2
        return [bool]$result.ok
    } catch {
        return $false
    }
}

function Test-OllamaAvailable {
    param([string]$HostUrl)
    $ollamaTagsUrl = $HostUrl.TrimEnd("/") + "/api/tags"
    try {
        Invoke-RestMethod -Uri $ollamaTagsUrl -Method Get -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Open-StartupPages {
    param([int]$Port)
    $scriptUrl = "http://127.0.0.1:${Port}/web_script.user.js"
    Write-Info "Opening userscript install/update page: $scriptUrl"
    Start-Process $scriptUrl | Out-Null
    Write-Info "Opening BOSS search page: $BossUrl"
    Start-Process $BossUrl | Out-Null
}

Set-Location $ProjectRoot
Write-Info "Project root: $ProjectRoot"

$requirementsPath = Join-Path $ProjectRoot "requirements.txt"
if (-not (Test-Path -LiteralPath $requirementsPath)) {
    Write-Fail "requirements.txt was not found. Please run this launcher from the Job Seeker project root."
    Pause-And-Exit 1
}

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $pythonExe = $venvPython
    Write-Info "Using virtualenv Python: $pythonExe"
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        Write-Fail "Python was not found. Install Python 3.10+ and then run: python -m venv .venv"
        Pause-And-Exit 1
    }
    $pythonExe = $pythonCommand.Source
    Write-Warn ".venv was not found. Using system Python: $pythonExe"
    Write-Warn "Recommended setup: python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt"
}

Write-Info "Checking Python dependencies..."
& $pythonExe -c "import fastapi, uvicorn, pydantic, ollama, pypdf, multipart" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Python dependencies are incomplete. Run: pip install -r requirements.txt"
    Pause-And-Exit 1
}

$configPath = Join-Path $ProjectRoot "data\config.json"
$config = $null
if (Test-Path -LiteralPath $configPath) {
    try {
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Warn "Failed to read data/config.json. Using default port 33333."
    }
}

$port = [int](Get-ConfigValue $config "server_port" 33333)
$provider = [string](Get-ConfigValue $config "model_provider" "ollama")
$ollamaHost = [string](Get-ConfigValue $config "ollama_host" "http://127.0.0.1:11434")
$openaiKey = [string](Get-ConfigValue $config "openai_api_key" "")

if (Test-TcpPort $port) {
    if (Test-JobSeekerHealth $port) {
        Write-Warn "Job Seeker is already running on port $port. This launcher will not start another backend."
        if (-not $NoOpen) {
            Open-StartupPages $port
        }
        Pause-And-Exit 0
    }
    Write-Fail "Port $port is occupied by another program. Close it or change server_port in data/config.json."
    Pause-And-Exit 1
}

$ollamaAvailable = $false
if ($provider -eq "ollama") {
    $ollamaAvailable = Test-OllamaAvailable $ollamaHost
}

if ($provider -eq "ollama" -and $ollamaAvailable) {
    Write-Info "Ollama is reachable: $ollamaHost"
}

if ($provider -eq "ollama" -and -not $ollamaAvailable) {
    Write-Warn "Ollama is not reachable: $ollamaHost. The service will still start, but model calls may fail."
}

if ($provider -eq "openai" -and $openaiKey) {
    Write-Info "OpenAI API Key is configured."
}

if ($provider -eq "openai" -and -not $openaiKey) {
    Write-Warn "Provider is OpenAI, but API Key is missing. Run config in the CLI."
}

Write-Info "Starting Job Seeker CLI..."
$mainPy = Join-Path $ProjectRoot "main.py"
& $pythonExe $mainPy
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Pause-And-Exit $exitCode
}

exit 0
