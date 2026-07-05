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
$OpenCooldownSeconds = 60
$DefaultOllamaModel = "qwen3:1.7b"

function Write-Info {
    param([string]$Message)
    Write-Host "[Job Seeker Auto] $Message" -ForegroundColor Cyan
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[Job Seeker Auto] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[Job Seeker Auto] $Message" -ForegroundColor Red
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

function Wait-OllamaAvailable {
    param(
        [string]$HostUrl,
        [int]$TimeoutSeconds = 20
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-OllamaAvailable $HostUrl) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-OllamaModels {
    param([string]$HostUrl)
    $ollamaTagsUrl = $HostUrl.TrimEnd("/") + "/api/tags"
    try {
        $payload = Invoke-RestMethod -Uri $ollamaTagsUrl -Method Get -TimeoutSec 5
        $models = @()
        foreach ($item in @($payload.models)) {
            if ($item.name) {
                $models += [string]$item.name
            } elseif ($item.model) {
                $models += [string]$item.model
            }
        }
        return $models
    } catch {
        return @()
    }
}

function Find-OllamaCommand {
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return ""
}

function Ensure-OllamaCommand {
    $commandPath = Find-OllamaCommand
    if ($commandPath) {
        return $commandPath
    }
    Write-Warn "Ollama was not found. It is required for the default local model."
    Write-Warn "Official Windows installer command: irm https://ollama.com/install.ps1 | iex"
    $answer = Read-Host "Install Ollama now? [y/N]"
    if ($answer -notin @("y", "Y", "yes", "YES", "Yes")) {
        return ""
    }
    try {
        Invoke-Expression (Invoke-RestMethod -Uri "https://ollama.com/install.ps1")
    } catch {
        Write-Fail "Ollama install failed: $($_.Exception.Message)"
        return ""
    }
    $commandPath = Find-OllamaCommand
    if (-not $commandPath) {
        Write-Fail "Ollama installation finished, but the ollama command was not found in PATH or common install paths. Reopen this launcher after installation."
        return ""
    }
    return $commandPath
}

function Ensure-OllamaRunning {
    param(
        [string]$OllamaExe,
        [string]$HostUrl
    )
    if (Test-OllamaAvailable $HostUrl) {
        return $true
    }
    if (-not $OllamaExe) {
        return $false
    }
    Write-Warn "Ollama is not reachable. Trying to start Ollama..."
    try {
        Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    } catch {
        Write-Warn "Starting 'ollama serve' failed: $($_.Exception.Message)"
        try {
            Start-Process -FilePath $OllamaExe -WindowStyle Hidden | Out-Null
        } catch {
            Write-Warn "Starting Ollama app failed: $($_.Exception.Message)"
        }
    }
    return (Wait-OllamaAvailable $HostUrl 25)
}

function Ensure-OllamaModel {
    param(
        [string]$OllamaExe,
        [string]$HostUrl,
        [string]$ModelName
    )
    if (-not (Test-OllamaAvailable $HostUrl)) {
        return $false
    }
    $models = @(Get-OllamaModels $HostUrl)
    if ($models -contains $ModelName) {
        Write-Info "Ollama model is available: $ModelName"
        return $true
    }
    if (-not $OllamaExe) {
        Write-Warn "Cannot pull model because ollama command is missing: $ModelName"
        return $false
    }
    Write-Info "Pulling default Ollama model: $ModelName"
    & $OllamaExe pull $ModelName
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Model pull failed: $ModelName"
        return $false
    }
    return $true
}

function Test-OpenCooldown {
    param([string]$Name)
    $cacheDir = Join-Path $ProjectRoot "data\cache"
    $stampPath = Join-Path $cacheDir "browser_open_$Name.stamp"
    try {
        if (-not (Test-Path -LiteralPath $cacheDir)) {
            New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
        }
        if (Test-Path -LiteralPath $stampPath) {
            $age = (Get-Date) - (Get-Item -LiteralPath $stampPath).LastWriteTime
            if ($age.TotalSeconds -lt $OpenCooldownSeconds) {
                return $false
            }
        }
        Set-Content -LiteralPath $stampPath -Value ([DateTimeOffset]::Now.ToUnixTimeSeconds()) -Encoding UTF8
    } catch {
        return $true
    }
    return $true
}

function Open-StartupPages {
    param([int]$Port)
    if ($NoOpen) {
        return
    }
    $scriptUrl = "http://127.0.0.1:${Port}/web_script.user.js"
    if (Test-OpenCooldown "userscript") {
        Write-Info "Opening userscript install/update page: $scriptUrl"
        Start-Process $scriptUrl | Out-Null
    } else {
        Write-Warn "Userscript page was opened recently; skipping duplicate open."
    }
    if (Test-OpenCooldown "boss_search") {
        Write-Info "Opening BOSS search page: $BossUrl"
        Start-Process $BossUrl | Out-Null
    } else {
        Write-Warn "BOSS search page was opened recently; skipping duplicate open."
    }
}

function Resume-ExistingJobSeeker {
    param([int]$Port)
    try {
        $body = @{ command = "resume"; new_run = $true } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri "http://127.0.0.1:${Port}/control" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 5 | Out-Null
        Write-Info "Existing Job Seeker service resumed with a new run."
        return $true
    } catch {
        Write-Warn "Failed to resume existing Job Seeker service: $($_.Exception.Message)"
        return $false
    }
}

function Get-ExistingJobSeekerStatus {
    param([int]$Port)
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:${Port}/status" -Method Get -TimeoutSec 5
    } catch {
        Write-Warn "Failed to read existing Job Seeker status: $($_.Exception.Message)"
        return $null
    }
}

function Test-ExistingJobSeekerReady {
    param([object]$Status)
    if ($null -eq $Status) {
        return $false
    }
    $resumeReady = [bool]$Status.resume.saved
    $profileReady = [bool]$Status.cache.profile_generated
    $greetingReady = [bool]$Status.greeting.confirmed
    $provider = [string]$Status.models.provider
    $modelReady = $false
    if ($provider -eq "openai") {
        $modelReady = [bool]$Status.models.openai_api_key_configured
    } else {
        $modelReady = [bool]$Status.ollama.available -and [bool]$Status.ollama.model_available
    }
    return ($resumeReady -and $profileReady -and $greetingReady -and $modelReady)
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
    Write-Warn ".venv was not found. Creating project virtualenv..."
    & $pythonCommand.Source -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        Write-Fail "Failed to create .venv. Try manually: python -m venv .venv"
        Pause-And-Exit 1
    }
    $pythonExe = $venvPython
    Write-Info "Using virtualenv Python: $pythonExe"
}

Write-Info "Checking Python dependencies..."
$dependencyCheckPath = Join-Path $ProjectRoot "scripts\check_deps.py"
if (-not (Test-Path -LiteralPath $dependencyCheckPath)) {
    Write-Fail "Dependency check script was not found: $dependencyCheckPath"
    Pause-And-Exit 1
}
$dependencyOutput = & $pythonExe $dependencyCheckPath 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($dependencyOutput) {
        $dependencyOutput | ForEach-Object { Write-Warn "$_" }
    }
    Write-Warn "Python dependencies are incomplete. Installing from requirements.txt..."
    Write-Info "Upgrading pip inside .venv..."
    & $pythonExe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "pip upgrade failed. Continuing with requirements install."
    }
    & $pythonExe -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Dependency installation failed. Manual command: $pythonExe -m pip install -r requirements.txt"
        Pause-And-Exit 1
    }
    $dependencyOutput = & $pythonExe $dependencyCheckPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($dependencyOutput) {
            $dependencyOutput | ForEach-Object { Write-Fail "$_" }
        }
        Write-Fail "Dependencies are still incomplete after install."
        Pause-And-Exit 1
    }
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
        Write-Warn "Job Seeker is already running on port $port. Attaching to the existing backend."
        $existingStatus = Get-ExistingJobSeekerStatus $port
        if (Test-ExistingJobSeekerReady $existingStatus) {
            Resume-ExistingJobSeeker $port | Out-Null
        } else {
            Write-Warn "Existing backend is alive, but saved configuration is not fully ready. It will not be resumed automatically."
            Write-Warn "Open http://127.0.0.1:${port}/status or use start_job_seeker.bat to finish configuration."
        }
        Open-StartupPages $port
        Write-Info "Existing backend is attached. You can monitor: http://127.0.0.1:${port}/status"
        Pause-And-Exit 0
    }
    Write-Fail "Port $port is occupied by another program. Close it or change server_port in data/config.json."
    Pause-And-Exit 1
}

if ($provider -eq "ollama") {
    $ollamaExe = Ensure-OllamaCommand
    if ($ollamaExe -and (Ensure-OllamaRunning $ollamaExe $ollamaHost)) {
        Write-Info "Ollama is reachable: $ollamaHost"
        Ensure-OllamaModel $ollamaExe $ollamaHost $DefaultOllamaModel | Out-Null
    } else {
        Write-Warn "Ollama is not ready. Job Seeker will still start and remain paused/blocked until the model is available."
    }
}

if ($provider -eq "openai" -and -not $openaiKey) {
    Write-Warn "Provider is OpenAI, but API Key is missing. Job Seeker will start and remain paused/blocked."
}

Write-Info "Starting Job Seeker auto-run..."
Write-Info "This mode uses saved configuration and starts automatically after the userscript connects."
$mainPy = Join-Path $ProjectRoot "main.py"
& $pythonExe $mainPy autorun
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Pause-And-Exit $exitCode
}

exit 0
