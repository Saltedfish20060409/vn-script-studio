#Requires -Version 5.1
# Restore committed Persona UI + fixed launcher after a Cursor "Revert conversation".
# Usage (repo root):  .\restore-ui.ps1

$ErrorActionPreference = "Stop"
$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location -LiteralPath $Root

$paths = @(
  "dev.ps1",
  "frontend/index.html",
  "frontend/src/styles/globals.css",
  "frontend/src/pages/LoginPage.tsx",
  "frontend/src/pages/LoginPage.module.css",
  "frontend/src/components/StudioApp.tsx",
  "frontend/src/components/StudioApp.module.css",
  "frontend/src/components/CharacterWorkshop.tsx",
  "frontend/src/components/CharacterWorkshop.module.css",
  "frontend/src/components/AgentFloat.tsx",
  "frontend/src/components/AgentFloat.module.css",
  "frontend/src/components/AgentChat.module.css",
  "frontend/src/components/SettingsModal.tsx",
  "frontend/src/components/SettingsModal.module.css",
  "frontend/src/components/MapStudio.module.css",
  "frontend/src/components/SystemPanel.tsx",
  ".cursor/rules/ui-change-safety.mdc"
)

Write-Host "Restoring Persona UI files from git HEAD ..." -ForegroundColor Cyan
git restore --source=HEAD -- @paths
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: git restore failed (exit $LASTEXITCODE)" -ForegroundColor Red
  exit 1
}

$globals = Join-Path $Root "frontend\src\styles\globals.css"
$text = [System.IO.File]::ReadAllText($globals)
if ($text -notmatch '--accent:\s*#002fa7') {
  Write-Host "ERROR: globals.css still missing day accent #002fa7 after restore." -ForegroundColor Red
  exit 1
}

Write-Host "OK: day accent #002fa7 present." -ForegroundColor Green
Write-Host "In Cursor: reload these files from disk (do not keep old editor buffers)." -ForegroundColor Yellow
Write-Host "Then hard-refresh the browser (Ctrl+Shift+R)." -ForegroundColor Yellow
exit 0
