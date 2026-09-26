# 本地跑 e2e（真后端 + 真 Postgres，不动生产）
#
# 为什么需要它：e2e 需要 Postgres + 后端 + 前端 preview 三件套，
# 手工拼环境很容易漏（我第一轮就漏在"Docker daemon 没起"和"忘了 build"上，
# 后者还差点把旧包推上线）。所以把环境固化成一个脚本。
#
# 用法（在仓库根目录）：powershell -File frontend\e2e\run-local.ps1
#   -Spec  e2e/smoke.spec.ts   只跑某个 spec（可选）
#   -Keep  跑完不关后端（默认关掉，释放 8000 端口）
#
# 前置：Docker Desktop 已启动。数据库容器与 CI 用的是同一套配置
# （postgres:16-alpine / vnss:vnss / 库名 vnss_e2e / 端口 54102）。

param(
  [string]$Spec = "",
  [switch]$Keep
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pg = "vnss-e2e-pg"
$env:E2E_DATABASE_URL = "postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_e2e"

Write-Host "=== 1/4 Postgres ===" -ForegroundColor Cyan
$running = (docker ps --filter "name=$pg" --format "{{.Names}}") -contains $pg
if (-not $running) {
  # 已存在但停着的，直接起；不存在的才创建
  if ((docker ps -a --filter "name=$pg" --format "{{.Names}}") -contains $pg) {
    docker start $pg | Out-Null
  } else {
    docker run -d --name $pg -e POSTGRES_USER=vnss -e POSTGRES_PASSWORD=vnss `
      -e POSTGRES_DB=vnss_e2e -p 54102:5432 postgres:16-alpine | Out-Null
  }
  Start-Sleep -Seconds 6
}
docker exec $pg pg_isready -U vnss | Out-Null
Write-Host "  $pg 就绪"

Write-Host "=== 2/4 前端构建（e2e 跑 preview，必须用最新 dist）===" -ForegroundColor Cyan
# 这一步不能省：上一次我就是忘了 build，把旧包推上了线（部署后逐字节核对才发现）
Push-Location "$root\frontend"
npm run build | Select-Object -Last 2
Pop-Location

Write-Host "=== 3/4 后端（127.0.0.1:8000）===" -ForegroundColor Cyan
# 环境变量必须在启动**之前**设好：子进程继承的是启动那一刻的环境
$env:DATABASE_URL = $env:E2E_DATABASE_URL
$env:AUTH_AUTO_VERIFY = "true"
$env:ALLOW_REGISTRATION = "true"
$env:DEEPSEEK_API_KEY = ""
$env:SECRET_KEY = "e2e-test-secret-key-0123456789abcdef0123456789abcdef"
$backend = Start-Process -PassThru -FilePath "$root\backend\.venv\Scripts\python.exe" `
  -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
  -WorkingDirectory "$root\backend" -WindowStyle Hidden
$ok = $false
foreach ($i in 1..20) {
  Start-Sleep -Seconds 2
  try { Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing | Out-Null; $ok = $true; break } catch {}
}
if (-not $ok) { throw "后端没起来：检查 backend/.venv 是否装好依赖" }
Write-Host "  /health OK"

Write-Host "=== 4/4 Playwright ===" -ForegroundColor Cyan
Push-Location "$root\frontend"
try {
  if ($Spec) { npx playwright test $Spec } else { npx playwright test }
} finally {
  Pop-Location
  if (-not $Keep) {
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    Write-Host "已关闭本地后端（数据库容器 $pg 留着，下次复用；不用了：docker rm -f $pg）"
  }
}
