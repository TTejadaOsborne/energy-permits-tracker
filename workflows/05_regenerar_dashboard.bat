@echo off
:: ============================================================
:: WORKFLOW 05 — Regenerar dashboard (projects_data.js)
:: Frecuencia: tras cualquier cambio en output/ o index.html
:: Descripción: Re-ejecuta project_resolver.py para regenerar
::   projects_data.js y projects.json desde los output JSONs.
::   No requiere scraping ni APIs externas.
:: ============================================================
echo [%date% %time%] Regenerando dashboard...
cd /d "%~dp0.."

python project_resolver.py
if %errorlevel% neq 0 (
    echo ERROR en project_resolver.py — revisar output/
    exit /b 1
)

echo [%date% %time%] Dashboard regenerado.
echo Ficheros actualizados:
echo   projects.json
echo   projects_data.js
echo.
echo Abrir index.html en el navegador para verificar.
