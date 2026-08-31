param(
  [string]$Path = "tests\quality",
  [int]$MinOverall = 70,
  [switch]$Json
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $ProjectRoot

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$Args = @("-m", "app.analysis.benchmark", $Path, "--min-overall", "$MinOverall")
if ($Json) {
  $Args += "--json"
}

& $Python @Args
exit $LASTEXITCODE

