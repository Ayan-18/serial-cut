<#
  Remove local scratch files that accumulate during development: throwaway
  databases, pytest temp dirs, tool caches. Never touches .env, .venv, the
  managed cache/output dirs, models, or anything tracked by git.
#>
param([switch]$Caches)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Set-Location (Split-Path -Parent $PSScriptRoot)

$targets = @(
  "data\ci*.db", "data\*-smoke.db", "data\ci-local*.db",
  "data\pytest-tmp*", ".pytest_cache", ".coverage", "htmlcov",
  "frontend\coverage"
)
if ($Caches) {
  $targets += @(".ruff_cache", ".mypy_cache")
}

$removed = 0
foreach ($pattern in $targets) {
  foreach ($item in Get-Item -Path $pattern -ErrorAction SilentlyContinue) {
    Remove-Item -LiteralPath $item.FullName -Recurse -Force
    Write-Host "  removed $($item.FullName.Replace((Get-Location).Path + '\', ''))"
    $removed++
  }
}
Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch "\\\.venv\\" } |
  ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force; $removed++ }

Write-Host "Done. $removed item(s) removed."
Write-Host "Kept: .env, .venv, data\cache, data\output, data\models, data\characters, data\logs."
