@echo off
SET PYTHONIOENCODING=utf-8
echo ============================================================
echo  NODALYS - RE-VOLCADO LIMPIO DE DATOS HISTORICOS
echo  Paso 1: Limpia el Sheet manualmente (Ctrl+A + Suprimir)
echo  Paso 2: Ejecuta este script
echo ============================================================
echo.

set API_KEY=%1
if "%API_KEY%"=="" (
    echo ERROR: Falta API key. Uso: revolver_historico.bat TU_API_KEY
    exit /b 1
)

set BOLETINES=BOE BOCyL BOCM DOCM DOG BOJA BOC

echo Procesando fechas historicas...
echo.

for %%F in (20260428 20260424 20260423 20260422 20260417) do (
    echo --- Fecha: %%F ---
    python pipeline.py --fecha %%F --boletines %BOLETINES% --api-key %API_KEY%
    if exist output\energy_extraido_%%F.json (
        python sheets_exporter.py output\energy_extraido_%%F.json
        echo OK - %%F exportado
    ) else (
        echo WARN - No se genero archivo para %%F
    )
    echo.
    timeout /t 3 /nobreak > nul
)

echo ============================================================
echo  RE-VOLCADO COMPLETADO
echo  Recarga el dashboard con Ctrl+F5
echo ============================================================
