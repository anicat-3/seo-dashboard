<#
.SYNOPSIS
    Первичная установка SEO-дашборда на Windows (localhost или сервер).

.DESCRIPTION
    Скрипт идемпотентен — его можно запускать повторно:
      1. создаёт пользователя и базы PostgreSQL (рабочую и тестовую);
      2. создаёт .env со случайными ключами и строкой подключения;
      3. создаёт виртуальное окружение Python и ставит зависимости;
      4. применяет миграции схемы (Alembic);
      5. загружает справочники и создаёт учётные записи admin и seo
         (пароли вводятся в консоли и нигде не сохраняются);
      6. собирает фронтенд.

    Пароль суперпользователя postgres запрашивается в консоли и используется
    только в рамках этого запуска.

.PARAMETER PgBin
    Папка bin установленного PostgreSQL. По умолчанию определяется по службе Windows.

.PARAMETER DatabaseOnly
    Только создать базы, пользователя БД и .env (без миграций и учётных записей).

.EXAMPLE
    .\scripts\setup.ps1
#>
[CmdletBinding()]
param(
    [string]$PgBin,
    [string]$DbName = "seo_dashboard",
    [string]$DbUser = "seo_dashboard",
    [string]$PgHost = "localhost",
    [int]$PgPort = 5432,
    [switch]$DatabaseOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$EnvFile = Join-Path $Root ".env"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }

function Invoke-Checked([scriptblock]$Command, [string]$What) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Не удалось: $What (код $LASTEXITCODE)" }
}

# --- 1. PostgreSQL -----------------------------------------------------------
if (-not $PgBin) {
    $service = Get-CimInstance Win32_Service | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1
    if ($service -and $service.PathName -match '"([^"]+)\\pg_ctl\.exe"') { $PgBin = $Matches[1] }
}
if (-not $PgBin -or -not (Test-Path (Join-Path $PgBin "psql.exe"))) {
    throw "Не найден psql.exe. Укажите папку bin PostgreSQL: .\scripts\setup.ps1 -PgBin 'D:\PostgreSQL\bin'"
}
$Psql = Join-Path $PgBin "psql.exe"

if (Test-Path $EnvFile) {
    Write-Step "Файл .env уже существует — создание базы и ключей пропущено"
} else {
    Write-Step "Создание пользователя и баз PostgreSQL"
    $secure = Read-Host "Пароль суперпользователя postgres" -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    try {
        $common = @("-h", $PgHost, "-p", $PgPort, "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-At")
        Invoke-Checked { & $Psql @common -c "SELECT 1" | Out-Null } "подключение к PostgreSQL (проверьте пароль)"

        # Пароль пользователя приложения: только буквы и цифры, безопасен для SQL и URL.
        $chars = [char[]]"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
        $dbPassword = -join (1..32 | ForEach-Object { $chars | Get-Random })

        $roleExists = & $Psql @common -c "SELECT 1 FROM pg_roles WHERE rolname = '$DbUser'"
        $verb = if ($roleExists) { "ALTER" } else { "CREATE" }
        Invoke-Checked { & $Psql @common -c "$verb ROLE $DbUser LOGIN PASSWORD '$dbPassword'" | Out-Null } "создание пользователя БД"

        foreach ($name in @($DbName, "${DbName}_test")) {
            $exists = & $Psql @common -c "SELECT 1 FROM pg_database WHERE datname = '$name'"
            if (-not $exists) {
                Invoke-Checked { & $Psql @common -c "CREATE DATABASE $name OWNER $DbUser ENCODING 'UTF8'" | Out-Null } "создание базы $name"
                Write-Host "Создана база $name"
            }
        }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
    $script:DatabaseUrl = "postgresql+psycopg://${DbUser}:${dbPassword}@${PgHost}:${PgPort}/${DbName}"
}

# --- 2. Python ---------------------------------------------------------------
Write-Step "Виртуальное окружение Python и зависимости"
if (-not (Test-Path $Python)) {
    $systemPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $candidate) { $systemPython = $candidate }
    if (-not $systemPython) { throw "Python 3.12 не найден. Установите: winget install Python.Python.3.12" }
    Invoke-Checked { & $systemPython -m venv (Join-Path $Backend ".venv") } "создание виртуального окружения"
}
Push-Location $Backend
try {
    Invoke-Checked { & $Python -m pip install --quiet --upgrade pip } "обновление pip"
    Invoke-Checked { & $Python -m pip install --quiet -e ".[dev]" } "установка зависимостей"

    # --- 3. .env -------------------------------------------------------------
    if (-not (Test-Path $EnvFile)) {
        Write-Step "Создание .env"
        Invoke-Checked { & $Python -m app.cli init-env --database-url $script:DatabaseUrl } "создание .env"
    }

    if ($DatabaseOnly) {
        Write-Host "`nБазы и .env готовы. Продолжение установки: .\scripts\setup.ps1" -ForegroundColor Green
        return
    }

    # --- 4. Миграции и учётные записи ------------------------------------------
    Write-Step "Миграции схемы БД"
    Invoke-Checked { & $Python -m alembic upgrade head } "миграции"

    Write-Step "Справочники и учётные записи (admin — администратор, seo — SEO-команда)"
    Invoke-Checked { & $Python -m app.cli setup } "создание учётных записей"
} finally {
    Pop-Location
}

# --- 5. Фронтенд -------------------------------------------------------------
Write-Step "Сборка фронтенда"
Push-Location $Frontend
try {
    if (-not (Test-Path "node_modules")) { Invoke-Checked { npm install --no-audit --no-fund } "npm install" }
    Invoke-Checked { npm run build } "сборка фронтенда"
} finally {
    Pop-Location
}

Write-Host "`nГотово. Запуск приложения: .\scripts\run.ps1  →  http://localhost:8000" -ForegroundColor Green
