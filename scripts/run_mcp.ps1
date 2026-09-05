$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $ProjectRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  throw "Virtual environment is missing. Run: powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1"
}

& $Python -c "import mcp" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing the MCP extra..."
  & $Python -m pip install -e ".[mcp]"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# SerialCuts must already be running (scripts\run_local.ps1); this is a thin
# loopback client. stdio transport — the MCP client launches and talks to it.
& $Python -m app.mcp_server
exit $LASTEXITCODE
