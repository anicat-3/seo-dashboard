<#
.SYNOPSIS
    Резервная копия базы SEO-дашборда (pg_dump в формате custom).

.DESCRIPTION
    Строка подключения берётся из .env. Файл сохраняется в папку backups
    (или в -OutDir, например в папку облачного хранилища), копии старше
    -KeepDays дней удаляются. Восстановление:
        pg_restore -h localhost -U seo_dashboard -d seo_dashboard --clean backups\<файл>.dump

    Для ежедневного запуска добавьте скрипт в Планировщик заданий Windows.

.EXAMPLE
    .\scripts\backup.ps1 -OutDir "G:\Мой диск\Backups\seo-dashboard"
#>
[CmdletBinding()]
param(
    [string]$OutDir,
    [string]$PgBin,
    [int]$KeepDays = 30
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $Root "backups" }

$line = Get-Content (Join-Path $Root ".env") | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
if ($line -notmatch '://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(\S+)\s*$') { throw "Не удалось разобрать DATABASE_URL в .env" }
$dbUser, $dbPassword, $dbHost, $dbPort, $dbName = $Matches[1], $Matches[2], $Matches[3], $Matches[4], $Matches[5]
if (-not $dbPort) { $dbPort = 5432 }

if (-not $PgBin) {
    $service = Get-CimInstance Win32_Service | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1
    if ($service -and $service.PathName -match '"([^"]+)\\pg_ctl\.exe"') { $PgBin = $Matches[1] }
}
$pgDump = Join-Path $PgBin "pg_dump.exe"
if (-not (Test-Path $pgDump)) { throw "Не найден pg_dump.exe; укажите -PgBin" }

New-Item -ItemType Directory -Force $OutDir | Out-Null
$file = Join-Path $OutDir ("{0}_{1}.dump" -f $dbName, (Get-Date -Format "yyyy-MM-dd_HHmm"))

$env:PGPASSWORD = $dbPassword
try {
    & $pgDump -h $dbHost -p $dbPort -U $dbUser -Fc -f $file $dbName
    if ($LASTEXITCODE -ne 0) { throw "pg_dump завершился с кодом $LASTEXITCODE" }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

Get-ChildItem $OutDir -Filter "*.dump" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } |
    Remove-Item -Force -Confirm:$false

Write-Host "Резервная копия: $file" -ForegroundColor Green
