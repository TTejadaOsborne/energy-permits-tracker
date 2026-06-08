@echo off
REM ─── Energy Boletines Pipeline — scraping diario + export a Google Sheets ──
REM  Ejecutar cada mañana (p.ej. 07:30) via Administrador de Tareas de Windows.
REM  Lee ANTHROPIC_API_KEY del fichero .env en el directorio del proyecto.
REM ──────────────────────────────────────────────────────────────────────────

setlocal

set "PROJ_DIR=%~dp0"
cd /d "%PROJ_DIR%"

REM ── Leer .env ─────────────────────────────────────────────────────────────
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "line=%%A"
        if not "!line:~0,1!"=="#" if not "%%A"=="" set "%%A=%%B"
    )
)

REM ── Verificar API key ──────────────────────────────────────────────────────
if "%ANTHROPIC_API_KEY%"=="" (
    echo ERROR: ANTHROPIC_API_KEY no definida en .env
    exit /b 1
)

REM ── Logs ──────────────────────────────────────────────────────────────────
if not exist "logs" mkdir logs
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set "LOGFILE=logs\pipeline_%DT:~0,8%.log"

echo [%DATE% %TIME%] === INICIO PIPELINE === >> "%LOGFILE%"

REM ── PASO 1: Scraping + extraccion AI ─────────────────────────────────────
echo [%DATE% %TIME%] Paso 1: pipeline.py --ayer >> "%LOGFILE%"
python pipeline.py --ayer --modelo haiku >> "%LOGFILE%" 2>&1
set PIPELINE_EXIT=%ERRORLEVEL%
echo [%DATE% %TIME%] pipeline.py fin (exit %PIPELINE_EXIT%) >> "%LOGFILE%"

if %PIPELINE_EXIT% neq 0 (
    echo [%DATE% %TIME%] ERROR en pipeline — abortando export >> "%LOGFILE%"
    exit /b %PIPELINE_EXIT%
)

REM ── PASO 2: Export a Google Sheets ────────────────────────────────────────
echo [%DATE% %TIME%] Paso 2: sheets_exporter.py >> "%LOGFILE%"
python sheets_exporter.py >> "%LOGFILE%" 2>&1
set EXPORT_EXIT=%ERRORLEVEL%
echo [%DATE% %TIME%] sheets_exporter.py fin (exit %EXPORT_EXIT%) >> "%LOGFILE%"

echo [%DATE% %TIME%] === FIN (pipeline=%PIPELINE_EXIT% export=%EXPORT_EXIT%) === >> "%LOGFILE%"
endlocal
exit /b %EXPORT_EXIT%
