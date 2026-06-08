@echo off
:: ============================================================
:: WORKFLOW 03 — Análisis de afloramientos tras permisos desfavorables
:: Frecuencia: mensual o tras batch de permisos denegados
:: Descripción: Analiza el lag entre denegación y afloramiento
::   formal de capacidad. Actualiza el forecast y adverse_forecast_data.js
::   que alimenta la pestaña Subestaciones del dashboard.
::
:: Cuándo ejecutar:
::   - Tras acumulación de nuevos denegados/desistidos en el mes
::   - Cuando REE actualiza los mapas de capacidad (después del WF 02)
::   - Tras aplicar un parche Excel con datos manuales (WF 04)
:: ============================================================
echo [%date% %time%] Analizando patrones de afloramiento...
cd /d "%~dp0.."

echo --- Calculando lags denegacion→afloramiento ---
python analyze_adverse_lag.py
if %errorlevel% neq 0 (
    echo ERROR en analyze_adverse_lag.py
    exit /b 1
)

echo --- Generando forecast de afloramientos ---
python generate_adverse_forecast.py
if %errorlevel% neq 0 (
    echo ERROR en generate_adverse_forecast.py
    exit /b 1
)

echo [%date% %time%] Análisis de afloramientos completado.
echo Ficheros actualizados:
echo   references\adverse_lag_cases.csv   (casos con lag medido)
echo   references\adverse_active.csv      (proyectos activos sin aflorar)
echo   references\adverse_forecast.csv    (forecast completo)
echo   adverse_forecast_data.js           (cargado por el dashboard)
echo.
echo SIGUIENTE PASO: revisar la pestaña Subestaciones → detalle de SET → sección Afloramientos.
