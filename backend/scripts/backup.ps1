#Requires -Version 5.1
<#
VN Script Studio — PostgreSQL 备份脚本
用法：  .\scripts\backup.ps1 [-OutDir .\backups] [-Keep 14]
说明： 使用 docker 内的 postgres 16（宿主机 15432）。直接 pg_dump，无需 docker exec。
       - DATABASE_URL 与 backend/.env 不一致时，先手动改下面的 $DbName / $DbUser / $DbHost / $DbPort。
#>
param(
  [string]$OutDir = (Join-Path $PSScriptRoot "..\backups"),
  [int]$Keep = 14
)

$ErrorActionPreference = "Stop"

# 与 backend/.env / docker-compose.yml 保持一致
$DbHost = "127.0.0.1"
$DbPort = "15432"
$DbUser = "vnss"
$DbName = "vnss"

# 支持 docker desktop 与本地 pg 两种环境下的 pg_dump 查找
function Find-PgDump {
  $candidates = @(
    (Get-Command pg_dump -ErrorAction SilentlyContinue),
    (Get-ChildItem "C:\Program Files\PostgreSQL" -Recurse -Filter pg_dump.exe -ErrorAction SilentlyContinue | Select-Object -First 1),
    (Get-ChildItem "$env:USERPROFILE\scoop\apps\postgresql" -Recurse -Filter pg_dump.exe -ErrorAction SilentlyContinue | Select-Object -First 1)
  ) | Where-Object { $_ -ne $null } | Select-Object -First 1
  if (-not $candidates) { throw "未找到 pg_dump：请安装 PostgreSQL 客户端，或用 docker exec pg_dump 手动备份。" }
  return $candidates.Path
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outFile = Join-Path $OutDir ("vnss-" + $stamp + ".dump")

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$pgDump = Find-PgDump
$env:PGPASSWORD = "vnss"

Write-Host "备份 -> $outFile"
& $pgDump -h $DbHost -p $DbPort -U $DbUser -d $DbName -F c -Z 6 -f $outFile
if ($LASTEXITCODE -ne 0) { throw "pg_dump 失败 (exit $LASTEXITCODE)" }
Write-Host "完成。"

# 清理过期备份（保留最近 $Keep 份）
Get-ChildItem $OutDir -Filter "vnss-*.dump" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -Skip $Keep |
  ForEach-Object { Write-Host ("清理旧备份: " + $_.Name); Remove-Item $_.FullName -Force }
