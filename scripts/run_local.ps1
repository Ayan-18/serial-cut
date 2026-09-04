param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8090,
  [int]$LlmPort = 8081,
  [string]$ModelPath = ".\data\models\qwen3-4b\Qwen3-4B-Q4_K_M.gguf",
  [int]$HealthIntervalSec = 15
)

$ErrorActionPreference = "Stop"
if ($HostName -notin @("127.0.0.1", "localhost", "::1")) {
  throw "SerialCuts разрешено запускать только на 127.0.0.1, localhost или ::1."
}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PATH = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $ProjectRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  throw "Virtual environment is missing. Run: powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1"
}
$ResolvedModel = (Resolve-Path -LiteralPath $ModelPath -ErrorAction SilentlyContinue)
if ($null -eq $ResolvedModel) {
  throw "Qwen model is missing. Run: powershell -ExecutionPolicy Bypass -File .\scripts\install_models.ps1"
}

$HealthUrl = "http://127.0.0.1:$LlmPort/health"
$LogsDir = Join-Path $ProjectRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Test-LlamaHealthy {
  try { $null = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2; return $true }
  catch { return $false }
}

function Start-Llama {
  $llama = Get-Command "llama-server" -ErrorAction SilentlyContinue
  if ($null -eq $llama) { throw "llama-server is missing. Install: winget install --exact --id ggml.llamacpp" }
  $startArgs = @{
    FilePath               = $llama.Source
    ArgumentList           = @(
      "-m", ('"' + $ResolvedModel.Path + '"'),
      "--host", "127.0.0.1", "--port", "$LlmPort",
      "--ctx-size", "12288", "--parallel", "1", "--gpu-layers", "auto",
      "--cors-origins", "localhost", "--jinja", "--no-webui"
    )
    PassThru               = $true
    WindowStyle            = "Hidden"
    RedirectStandardOutput = (Join-Path $LogsDir "llama.stdout.log")
    RedirectStandardError  = (Join-Path $LogsDir "llama.stderr.log")
  }
  $proc = Start-Process @startArgs
  for ($i = 1; $i -le 120; $i++) {
    if ($proc.HasExited) { throw "Qwen server stopped during startup. See data\logs\llama.stderr.log" }
    if (Test-LlamaHealthy) { return $proc }
    Start-Sleep -Seconds 1
  }
  throw "Qwen server did not become ready in 120 seconds. See data\logs\llama.stderr.log"
}

$LlamaProcess = $null
$AppProcess = $null
try {
  if (Test-LlamaHealthy) {
    Write-Host "Local Qwen server is already ready on port $LlmPort."
  } else {
    Write-Host "Starting local Qwen model (5-15 seconds)..."
    $LlamaProcess = Start-Llama
    Write-Host "Local Qwen server is ready."
  }

  & $Python -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  $uvicornLog = Join-Path $LogsDir "uvicorn.log"
  $AppProcess = Start-Process -FilePath $Python -PassThru -WindowStyle Hidden `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $HostName, "--port", "$Port") `
    -RedirectStandardOutput $uvicornLog -RedirectStandardError (Join-Path $LogsDir "uvicorn.err.log")

  Write-Host "SerialCuts is ready: http://${HostName}:$Port"
  Write-Host "Logs: data\logs\serialcuts.log. Press Ctrl+C to stop."

  # Supervisor loop: keep Qwen alive while the app runs.
  while (-not $AppProcess.HasExited) {
    Start-Sleep -Seconds $HealthIntervalSec
    if ($AppProcess.HasExited) { break }
    if ($null -ne $LlamaProcess -and -not (Test-LlamaHealthy)) {
      Write-Warning "Local Qwen server is not responding — restarting it."
      if (-not $LlamaProcess.HasExited) { try { Stop-Process -Id $LlamaProcess.Id -Force } catch {} }
      try { $LlamaProcess = Start-Llama; Write-Host "Local Qwen server restarted." }
      catch { Write-Warning "Restart failed: $($_.Exception.Message)" }
    }
  }
  exit $AppProcess.ExitCode
}
finally {
  foreach ($p in @($AppProcess, $LlamaProcess)) {
    if ($null -ne $p -and -not $p.HasExited) {
      try { Stop-Process -Id $p.Id -Force } catch {}
    }
  }
  Write-Host "SerialCuts stopped."
}
