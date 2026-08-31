param(
  [string]$Output = "data\demo-season",
  [string]$Ffmpeg = "ffmpeg"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path -LiteralPath "."
$outDir = Join-Path $root $Output
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

for ($i = 1; $i -le 2; $i++) {
  $episode = Join-Path $outDir ("s01e{0:d2}.mp4" -f $i)
  & $Ffmpeg -hide_banner -y `
    -f lavfi -i "testsrc2=size=1280x720:rate=25:duration=8" `
    -f lavfi -i "sine=frequency=$($i * 220):duration=8" `
    -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest $episode
  if ($LASTEXITCODE -ne 0) {
    throw "FFmpeg не смог создать $episode"
  }
}

Write-Output "Demo season created: $outDir"
Write-Output "Import this folder in SerialCuts, then run media/candidate steps."
