param(
  [string]$ModelPath = ".\data\models\qwen3-4b\Qwen3-4B-Q4_K_M.gguf",
  [int]$Port = 8081
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PATH = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

$LlamaServer = Get-Command "llama-server" -ErrorAction SilentlyContinue
if ($null -eq $LlamaServer) {
  throw "llama-server is missing. Install the official package with: winget install llama.cpp"
}
if (-not (Test-Path -LiteralPath $ModelPath)) {
  throw "Qwen model not found: $ModelPath. Run scripts\install_models.ps1 first."
}

$ResolvedModel = (Resolve-Path -LiteralPath $ModelPath).Path
& $LlamaServer.Source @(
  "-m", $ResolvedModel,
  "--host", "127.0.0.1",
  "--port", $Port,
  "--ctx-size", "12288",
  "--parallel", "1",
  "--gpu-layers", "auto",
  "--cors-origins", "localhost",
  "--jinja",
  "--no-webui"
)
exit $LASTEXITCODE
