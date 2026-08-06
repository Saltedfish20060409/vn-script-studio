#Requires -Version 5.1
param(
  [switch]$NoBrowser,
  [switch]$SkipDocker,
  [switch]$KeepOpen
)

$ErrorActionPreference = "Continue"
$Root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Py = Join-Path $Backend ".venv\Scripts\python.exe"

function Test-Port([int]$Port) {
  try {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -First 1
    return $null -ne $c
  } catch {
    return $false
  }
}

function Wait-Port([int]$Port, [int]$TimeoutSec = 45) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    if (Test-Port $Port) { return $true }
    try {
      $tcp = New-Object System.Net.Sockets.TcpClient
      $iar = $tcp.BeginConnect("127.0.0.1", $Port, $null, $null)
      $ok = $iar.AsyncWaitHandle.WaitOne(400)
      if ($ok -and $tcp.Connected) {
        $tcp.EndConnect($iar)
        $tcp.Close()
        return $true
      }
      $tcp.Close()
    } catch { }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Wait-IfNeeded([int]$Code = 0) {
  exit $Code
}

function Stop-UvicornWorkers {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $line = [string]$_.CommandLine
      $line -like "*uvicorn*app.main:app*"
    } |
    ForEach-Object {
      Write-Host ("api: stop leftover uvicorn PID=" + $_.ProcessId) -ForegroundColor Yellow
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

try {
  Write-Host "== VN Script Studio  one-click dev ==" -ForegroundColor Cyan
  Write-Host ("Root: " + $Root) -ForegroundColor DarkGray

  if (-not (Test-Path $Py)) {
    Write-Host ""
    Write-Host "ERROR: Missing backend\.venv" -ForegroundColor Red
    Write-Host "Run once in a terminal:" -ForegroundColor Yellow
    Write-Host "  cd backend"
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\pip install -r requirements.txt"
    Write-Host "  copy .env.example .env"
    Wait-IfNeeded 1
  }

  $envFile = Join-Path $Backend ".env"
  if (Test-Path $envFile) {
    $bytes = [System.IO.File]::ReadAllBytes($envFile)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
      Write-Host "env: removed UTF-8 BOM from backend\.env" -ForegroundColor Yellow
      $utf8NoBom = New-Object System.Text.UTF8Encoding $false
      $text = $utf8NoBom.GetString($bytes, 3, $bytes.Length - 3)
      [System.IO.File]::WriteAllText($envFile, $text, $utf8NoBom)
    }
  }

  $nodeModules = Join-Path $Frontend "node_modules"
  if (-not (Test-Path $nodeModules)) {
    Write-Host "web: frontend\node_modules missing, running npm install ..." -ForegroundColor Yellow
    Push-Location $Frontend
    try {
      npm install
      if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }
    } finally {
      Pop-Location
    }
  }

  if (-not $SkipDocker) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
      Write-Host "db: docker compose up -d" -ForegroundColor DarkGray
      Push-Location $Root
      try {
        docker compose up -d
        if ($LASTEXITCODE -ne 0) {
          Write-Host "db: docker compose failed (ok if Postgres already running)" -ForegroundColor Yellow
        }
      } finally {
        Pop-Location
      }
    } else {
      Write-Host "db: docker not found, skip" -ForegroundColor Yellow
    }
  }

  if (Test-Port 8000) {
    $owners = @()
    try {
      $owners = @(
        Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
          Select-Object -ExpandProperty OwningProcess -Unique
      )
    } catch { }
    $needReplace = $false
    foreach ($opid in $owners) {
      if (-not $opid) { continue }
      $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$opid" -ErrorAction SilentlyContinue
      $cmd = [string]$proc.CommandLine
      $exe = [string]$proc.ExecutablePath
      $isOurVenv =
        ($exe -like "*\backend\.venv\Scripts\python.exe") -or
        ($cmd -like "*\backend\.venv\Scripts\python.exe*uvicorn*")
      if (-not $isOurVenv) {
        $who = if ($exe) { $exe } else { $cmd }
        Write-Host ("api: port 8000 held by wrong process PID=" + $opid + " (" + $who + "), stopping...") -ForegroundColor Yellow
        Stop-Process -Id $opid -Force -ErrorAction SilentlyContinue
        $needReplace = $true
      }
    }
    if ($needReplace) {
      Start-Sleep -Seconds 1
      Stop-UvicornWorkers
      Start-Sleep -Seconds 1
    } else {
      $hasKind = $false
      try {
        $oa = Invoke-RestMethod -Uri "http://127.0.0.1:8000/openapi.json" -TimeoutSec 3
        $hasKind = $null -ne $oa.components.schemas.GenerateIn.properties.kind
      } catch { }
      if (-not $hasKind) {
        Write-Host "api: :8000 is up but API schema is stale (no GenerateIn.kind). Restarting..." -ForegroundColor Yellow
        foreach ($opid in $owners) {
          if ($opid) { Stop-Process -Id $opid -Force -ErrorAction SilentlyContinue }
        }
        Stop-UvicornWorkers
        Start-Sleep -Seconds 1
        $needReplace = $true
      } else {
        Write-Host "api: port 8000 already listening (project .venv), skip" -ForegroundColor DarkGray
      }
    }
    if ($needReplace -or -not (Test-Port 8000)) {
      Write-Host "api: starting uvicorn -> http://127.0.0.1:8000" -ForegroundColor Green
      $beCmd = "Set-Location -LiteralPath '$Backend'; `$env:PYTHONPATH='.'; & '$Py' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
      Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $beCmd
      ) | Out-Null
    }
  } else {
    Write-Host "api: starting uvicorn -> http://127.0.0.1:8000" -ForegroundColor Green
    $beCmd = "Set-Location -LiteralPath '$Backend'; `$env:PYTHONPATH='.'; & '$Py' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
      "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $beCmd
    ) | Out-Null
  }

  if (Test-Port 5173) {
    Write-Host "web: port 5173 already listening, skip" -ForegroundColor DarkGray
  } else {
    Write-Host "web: starting Vite -> http://127.0.0.1:5173" -ForegroundColor Green
    $feCmd = "Set-Location -LiteralPath '$Frontend'; npm run dev -- --host 127.0.0.1 --port 5173"
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
      "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $feCmd
    ) | Out-Null
  }

  Write-Host "wait: waiting for API :8000 ..." -ForegroundColor DarkGray
  if (-not (Wait-Port 8000 60)) {
    Write-Host "WARN: API port 8000 not up yet. Check the uvicorn window for DB/import errors." -ForegroundColor Yellow
  } else {
    Write-Host "api: ready" -ForegroundColor Green
  }
  Write-Host "wait: waiting for Vite :5173 ..." -ForegroundColor DarkGray
  if (-not (Wait-Port 5173 60)) {
    Write-Host "WARN: Vite port 5173 not up yet. Check the frontend window." -ForegroundColor Yellow
  } else {
    Write-Host "web: ready" -ForegroundColor Green
  }

  if (-not $NoBrowser) {
    try { Start-Process "http://127.0.0.1:5173" } catch { }
  }

  Write-Host ""
  Write-Host "Done. Backend/Frontend each have their own window (close window = stop)." -ForegroundColor Cyan
  Write-Host "Frontend: http://127.0.0.1:5173"
  Write-Host "API docs: http://127.0.0.1:8000/docs"
  Wait-IfNeeded 0
} catch {
  Write-Host ""
  Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
  Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
  Wait-IfNeeded 1
}
