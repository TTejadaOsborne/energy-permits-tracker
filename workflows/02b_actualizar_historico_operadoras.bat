@echo off
:: ============================================================
:: WORKFLOW 02b — Carga histórica de capacidad por operadora
::
:: *** CARGA ÚNICA — NO EJECUTAR MENSUALMENTE ***
::
:: Este workflow se ejecutó una sola vez para cargar el histórico
:: completo de capacidad de todas las distribuidoras DSO y REE.
:: Los archivos fuente son históricos cerrados y no recibirán
:: más actualizaciones (series terminadas o empresa absorbida).
::
:: FUENTES en references\ (no se actualizarán más):
::   Mapas_Capacidad_AyC-REE.xlsx       → histórico REE
::   Mapas_Capacidad_AyC-iDE.xlsx       → histórico i-DE
::   Mapas_Capacidad_AyC-e_distribucion.xlsx → histórico Endesa
::   Mapas_Capacidad_AyC-UFD.xlsx       → histórico UFD
::   Mapas_Capacidad_AyC-EREDES.xlsx    → histórico E-Redes 2023-2025
::   Mapas_Capacidad_AyC-Viesgo.xlsx    → histórico Viesgo 2021-2025 (absorbida UFD)
::
:: RESULTADO (CSVs en references\):
::   ree_capacidad.csv, ide_capacidad.csv, endesa_capacidad.csv,
::   ufd_capacidad.csv, eredes_capacidad.csv, viesgo_capacidad.csv
::   dso_capacidad_historial.csv  → consolidado de todos los anteriores
::   capacity_forecast.csv        → forecast de disponibilidad futura
::
:: Para la actualización mensual de capacidad ACTUAL usar WF 02a.
:: ============================================================
echo [%date% %time%] === CARGA HISTORICA OPERADORAS (una sola vez) ===
cd /d "%~dp0.."

echo --- Parseando REE ---
python parse_ree.py

echo --- Parseando i-DE ---
python parse_ide.py

echo --- Parseando Endesa ---
python parse_endesa.py

echo --- Parseando UFD ---
python parse_ufd.py

echo --- Parseando E-Redes (historico 2023-2025) ---
python parse_eredes.py

echo --- Parseando Viesgo (historico 2021-2025, absorbida UFD) ---
python parse_viesgo.py

echo --- Consolidando historico de todas las operadoras ---
python build_capacity_history.py
if %errorlevel% neq 0 (
    echo ERROR en build_capacity_history.py
    exit /b 1
)

echo --- Generando forecast de capacidad ---
python generate_capacity_forecast.py
if %errorlevel% neq 0 (
    echo ERROR en generate_capacity_forecast.py
    exit /b 1
)

echo.
echo [%date% %time%] === CARGA HISTORICA COMPLETADA ===
echo Ficheros generados:
echo   references\ree_capacidad.csv
echo   references\ide_capacidad.csv
echo   references\endesa_capacidad.csv
echo   references\ufd_capacidad.csv
echo   references\eredes_capacidad.csv
echo   references\viesgo_capacidad.csv
echo   references\dso_capacidad_historial.csv  (consolidado todas las operadoras)
echo   references\capacity_forecast.csv
echo.
echo A partir de ahora, solo es necesario ejecutar WF 02a mensualmente
echo (actualizacion del Monitor consolidado).
