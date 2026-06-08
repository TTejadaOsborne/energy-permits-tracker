@echo off
:: ============================================================
:: WORKFLOW 04 — Aplicar parche manual desde Excel
:: Frecuencia: cuando se complete una revisión manual de datos
:: Descripción: Lee un Excel exportado de la herramienta con
::   celdas coloreadas (rojo=nuevo manual, naranja=corrección)
::   y aplica los cambios a los output JSONs y regenera el dashboard.
::
:: Uso:
::   04_aplicar_parche_excel.bat ruta\al\archivo.xlsx
::
:: Si no se especifica ruta, busca el Excel más reciente en la
:: carpeta de descargas del usuario.
:: ============================================================
cd /d "%~dp0.."

set EXCEL_FILE=%1

if "%EXCEL_FILE%"=="" (
    echo Buscando Excel mas reciente en Descargas...
    for /f "delims=" %%f in ('dir /b /od "%USERPROFILE%\Downloads\nodalys_permisos_*.xlsx" 2^>nul') do set EXCEL_FILE=%USERPROFILE%\Downloads\%%f
)

if "%EXCEL_FILE%"=="" (
    echo ERROR: no se encontro ningun Excel. Especifica la ruta:
    echo   04_aplicar_parche_excel.bat "C:\ruta\al\archivo.xlsx"
    exit /b 1
)

echo [%date% %time%] Aplicando parche desde: %EXCEL_FILE%

echo --- Aplicando datos manuales ---
python scripts\apply_excel_patch.py "%EXCEL_FILE%"
if %errorlevel% neq 0 (
    echo ERROR en apply_excel_patch.py
    exit /b 1
)

echo --- Regenerando dashboard ---
python project_resolver.py

echo --- Actualizando análisis de afloramientos ---
python analyze_adverse_lag.py
python generate_adverse_forecast.py

echo [%date% %time%] Parche aplicado y dashboard regenerado.
echo SIGUIENTE PASO: verificar cambios en index.html.
