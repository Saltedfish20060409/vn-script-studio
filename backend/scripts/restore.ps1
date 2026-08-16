#Requires -Version 5.1
<#
VN Script Studio — PostgreSQL 恢复脚本
用法：  .\scripts\restore.ps1 -File .\backups\vnss-20260815-120000.dump
注意： 会**清空并重建** vnss 数据库（先备份再恢复）。
*/
#>
param(
  [Parameter(Mandatory = $true)]
  [string]$File
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $File)) { throw "备份文件不存在: $File" }

$DbHost = "127.0.0.1"
$DbPort = "54102"
$DbUser = "vnss"
$DbName = "vnss"

function Find-PgTools {
  $candidates = @(
    (Get-Command pg_restore -ErrorAction SilentlyContinue),
    (Get-ChildItem "C:\Program Files\PostgreSQL" -Recurse -Filter pg_restore.exe -ErrorAction SilentlyContinue | Select-Object -First 1)
  ) | Where-Object { $_ -ne $null } | Select-Object -First 1
  if (-not $candidates) { throw "未找到 pg_restore。" }
  return $candidates.Path
}

$env:PGPASSWORD = "vnss"

Write-Host "清空并重建 $DbName ..."
# 先断开现有连接再 drop/create（幂等）
psql -h $DbHost -p $DbPort -U $DbUser -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DbName' AND pid <> pg_backend_pid();" 2>$null
psql -h $DbHost -p $DbPort -U $DbUser -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $DbName;"
psql -h $DbHost -p $DbPort -U $DbUser -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DbName;"
if ($LASTEXITCODE -ne 0) { throw "重建数据库失败 (exit $LASTEXITCODE)" }

Write-Host "恢复 -> $File"
& (Find-PgTools) -h $DbHost -p $DbPort -U $DbUser -d $DbName --clean --if-exists -j 4 $File
if ($LASTEXITCODE -ne 0) { throw "pg_restore 失败 (exit $LASTEXITCODE)" }
Write-Host "恢复完成。"
