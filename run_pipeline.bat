@echo off
REM ─── Energy Boletines Pipeline ───────────────────────────────────────────────
REM  Ejecuta el scraping + extracción diaria de permisos energéticos.
REM  Configuración: editar .env con tu ANTHROPIC_API_KEY antes de usar.
REM  Uso manual:    run_pipeline.bat
REM  Automático:    Programar en Administrador de tareas de Windows
REM ─────────────────────────────────────────────────────────────────────────────

setlocal

REM ── Directorio del proyecto ──────────────────────────────────────────────────
set "PROJ_DIR=%~dp0"
cd /d "%PROJ_DIR%"

REM ── Leer .env si existe ──────────────────────────────────────────────────────
if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)

REM ── Verificar API key ────────────────────────────────────────────────────────
if "%ANTHROPIC_API_KEY%"=="" (
    echo ERROR: ANTHROPIC_API_KEY no definida.
    echo Edita el fichero .env y añade:  ANTHROPIC_API_KEY=sk-ant-...
    exit /b 1
)

REM ── Logs ─────────────────────────────────────────────────────────────────────
if not exist "logs" mkdir logs
set "LOGFILE=logs\pipeline_%DATE:~-4%%DATE:~3,2%%DATE:~0,2%.log"

echo [%DATE% %TIME%] Iniciando pipeline >> "%LOGFILE%"

REM ── Ejecutar ─────────────────────────────────────────────────────────────────
python pipeline.py --ayer --modelo haiku >> "%LOGFILE%" 2>&1

set EXIT_CODE=%ERRORLEVEL%
echo [%DATE% %TIME%] Fin pipeline (exit %EXIT_CODE%) >> "%LOGFILE%"

endlocal
exit /b %EXIT_CODE%
