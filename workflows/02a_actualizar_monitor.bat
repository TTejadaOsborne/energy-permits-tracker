@echo off
:: ============================================================
:: WORKFLOW 02a — Actualizar capacidad desde Monitor consolidado
:: Frecuencia: mensual, cuando se actualiza Monitor_Capacidad_Red_INTEGRADO_v4.xlsx
::
:: FUENTE: Monitor_Capacidad_Red_INTEGRADO_v4.xlsx (en la raíz del proyecto)
::   Contiene todas las operadoras (REE + DSOs) en hojas "DSO MesAño" / "REE MesAño".
::   Es el fichero que integra y consolida todos los snapshots mensuales.
::
:: RESULTADO:
::   sets_capacity.json  → capacidad actual por SET en el dashboard (pestaña Subestaciones)
::   sets_history.json   → evolución histórica de capacidad por SET
::   references/monitor_capacidad.csv → CSV normalizado del monitor
::
:: PASO PREVIO (manual):
::   Sustituir Monitor_Capacidad_Red_INTEGRADO_v4.xlsx por la versión más reciente.
:: ============================================================
echo [%date% %time%] Actualizando capacidad desde Monitor...
cd /d "%~dp0.."

if not exist "Monitor_Capacidad_Red_INTEGRADO_v4.xlsx" (
    echo ERROR: no se encuentra Monitor_Capacidad_Red_INTEGRADO_v4.xlsx en la raiz del proyecto.
    echo Copia el fichero actualizado aqui antes de continuar.
    exit /b 1
)

echo --- Extrayendo snapshot actual ---
python parse_monitor.py
if %errorlevel% neq 0 (
    echo ERROR en parse_monitor.py
    exit /b 1
)

echo --- Generando sets_capacity.json (estado actual en dashboard) ---
python generate_sets_capacity.py
if %errorlevel% neq 0 (
    echo ERROR en generate_sets_capacity.py
    exit /b 1
)

echo --- Actualizando histórico por SET ---
python generate_sets_history.py
if %errorlevel% neq 0 (
    echo ERROR en generate_sets_history.py
    exit /b 1
)

echo.
echo [%date% %time%] Monitor actualizado.
echo Ficheros actualizados:
echo   sets_capacity.json             (pestaña Subestaciones — estado actual)
echo   sets_history.json              (evolución histórica por SET)
echo   references\monitor_capacidad.csv
echo.
echo SIGUIENTE PASO: 
echo   Si también hay nuevos Excels de operadoras individuales → ejecutar WF 02b
echo   Si quieres actualizar el análisis de afloramientos      → ejecutar WF 03
