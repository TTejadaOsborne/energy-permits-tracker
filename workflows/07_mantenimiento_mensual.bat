@echo off
:: ============================================================
:: WORKFLOW 07 — Mantenimiento mensual completo
:: Frecuencia: mensual (ej. primer lunes de cada mes)
:: Descripción: Ejecuta el ciclo completo de mantenimiento:
::   validación, dedup, actualización de capacidad desde Monitor,
::   afloramientos y regeneración del dashboard.
::
:: NO incluye WF 02b (histórico por operadora) porque requiere
::   descarga manual de los Excels individuales de REE/DSOs,
::   y no se publican con frecuencia mensual fija.
::
:: PASO PREVIO: 
::   Sustituir Monitor_Capacidad_Red_INTEGRADO_v4.xlsx por la versión
::   más reciente antes de ejecutar este workflow.
:: ============================================================
echo [%date% %time%] === MANTENIMIENTO MENSUAL NODALYS ===
cd /d "%~dp0.."

echo.
echo [1/6] Validando boletines y deduplicando...
python scripts\validar_boletines.py
python scripts\dedup_pipeline.py

echo.
echo [2/6] Reparando capacidad_mw_liberada nula...
python scripts\repair_liberada.py

echo.
echo [3/6] Actualizando capacidad desde Monitor consolidado...
python parse_monitor.py
python generate_sets_capacity.py
python generate_sets_history.py

echo.
echo [4/6] Analizando afloramientos...
python analyze_adverse_lag.py
python generate_adverse_forecast.py

echo.
echo [5/6] Regenerando dashboard...
python project_resolver.py

echo.
echo [6/6] Exportando a Google Sheets...
python sheets_exporter.py

echo.
echo [%date% %time%] === MANTENIMIENTO COMPLETADO ===
echo.
echo Revisar en el dashboard:
echo   - Pestaña Publicaciones: sin duplicados, fechas correctas
echo   - Pestaña Proyectos: agrupaciones correctas
echo   - Pestaña Subestaciones: capacidad actual + afloramientos actualizados
echo   - Google Sheets: datos sincronizados
echo.
echo Si hay nuevos Excels de operadoras individuales (REE/iDE/Endesa/UFD):
echo   ejecutar adicionalmente: workflows\02b_actualizar_historico_operadoras.bat
