# Sync pure pet logic from Studio frontend into this package.
# Run from repo root: pwsh packages/desk-pet/sync-from-studio.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "../..")
$src = Join-Path $root "frontend/src/lib"
$dst = Join-Path $PSScriptRoot "src/core"
New-Item -ItemType Directory -Force -Path $dst | Out-Null

$files = @(
  "petMachine.ts",
  "petMachine.test.ts",
  "petCopy.ts",
  "petMotion.ts",
  "petMotion.test.ts",
  "petVisual.ts",
  "petVisual.test.ts",
  "petManifest.ts",
  "petBridge.ts",
  "deskPet.ts",
  "petEmoteSvg.ts"
)

foreach ($f in $files) {
  $from = Join-Path $src $f
  if (-not (Test-Path $from)) { Write-Warning "missing $f"; continue }
  Copy-Item -Force $from (Join-Path $dst $f)
  Write-Host "synced $f"
}

$assetNote = Join-Path $dst "ASSETS.md"
@"
# Runtime assets

Authoritative atlases live in ``frontend/public/pet/v1/`` (committed with Studio).

For a standalone shell, copy or symlink that folder to your app ``public/pet/v1/``.
Do not bake opaque backgrounds into masters — mobile overlay needs alpha.
"@ | Set-Content -Encoding utf8 $assetNote

Write-Host "done -> $dst"
