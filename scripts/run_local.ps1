param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8090,
  [int]$LlmPort = 8081,
  [string]$ModelPath = ".\data\models\qwen3-4b\Qwen3-4B-Q4_K_M.gguf"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PATH = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $ProjectRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  throw "Virtual environment is missing. Run: powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1"
}

$ResolvedModel = (Resolve-Path -LiteralPath $ModelPath -ErrorAction SilentlyContinue)
if ($null -eq $ResolvedModel) {
  throw "Qwen model is missing. Run: powershell -ExecutionPolicy Bypass -File .\scripts\install_models.ps1"
}

$HealthUrl = "http://127.0.0.1:$LlmPort/health"
$LlamaProcess = $null
try {
  try {
    $null = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
    Write-Host "Local Qwen server is already ready on port $LlmPort."
  }
  catch {
    $LlamaServer = Get-Command "llama-server" -ErrorAction SilentlyContinue
    if ($null -eq $LlamaServer) {
      throw "llama-server is missing. Install the official package: winget install llama.cpp"
    }

    $LogsDir = Join-Path $ProjectRoot "data\logs"
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
    $StdoutLog = Join-Path $LogsDir "llama.stdout.log"
    $StderrLog = Join-Path $LogsDir "llama.stderr.log"
    $QuotedModel = '"' + $ResolvedModel.Path + '"'
    $LlamaArgs = @(
      "-m", $QuotedModel,
      "--host", "127.0.0.1",
      "--port", "$LlmPort",
      "--ctx-size", "12288",
      "--parallel", "1",
      "--gpu-layers", "auto",
      "--cors-origins", "localhost",
      "--jinja",
      "--no-webui"
    )
    Write-Host "Starting local Qwen model. This normally takes 5-15 seconds..."
    $StartArgs = @{
      FilePath = $LlamaServer.Source
      ArgumentList = $LlamaArgs
      PassThru = $true
      WindowStyle = "Hidden"
      RedirectStandardOutput = $StdoutLog
      RedirectStandardError = $StderrLog
    }
    $LlamaProcess = Start-Process @StartArgs

    $Ready = $false
    for ($Attempt = 1; $Attempt -le 90; $Attempt++) {
      if ($LlamaProcess.HasExited) {
        throw "Qwen server stopped during startup. See data\logs\llama.stderr.log"
      }
      try {
        $null = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
        $Ready = $true
        break
      }
      catch {
        Start-Sleep -Seconds 1
      }
    }
    if (-not $Ready) {
      throw "Qwen server did not become ready in 90 seconds. See data\logs\llama.stderr.log"
    }
    Write-Host "Local Qwen server is ready."
  }

  & $Python -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Write-Host "SerialCuts is ready: http://${HostName}:$Port"
  Write-Host "Press Ctrl+C to stop the application."
  & $Python -m uvicorn app.main:app --host $HostName --port $Port
  exit $LASTEXITCODE
}
finally {
  if ($null -ne $LlamaProcess -and -not $LlamaProcess.HasExited) {
    Stop-Process -Id $LlamaProcess.Id
    Write-Host "Local Qwen server stopped."
  }
}
