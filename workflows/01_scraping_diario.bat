@echo off
:: ============================================================
:: WORKFLOW 01 — Scraping diario de boletines
:: Frecuencia: diario (programado via Tarea de Windows)
:: Descripción: Descarga publicaciones nuevas de todos los
::   boletines (BOE, BOCYL, BOJA, DOG, BOPA, BOA, DOCM, ...)
::   las procesa con el extractor IA y actualiza Google Sheets.
:: ============================================================
echo [%date% %time%] Iniciando scraping diario...
cd /d "%~dp0.."

python pipeline.py
if %errorlevel% neq 0 (
    echo ERROR en pipeline.py — revisar logs\pipeline.log
    exit /b 1
)

python project_resolver.py
if %errorlevel% neq 0 (
    echo ERROR en project_resolver.py
    exit /b 1
)

echo [%date% %time%] Scraping diario completado.
