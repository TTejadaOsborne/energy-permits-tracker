@echo off
:: ============================================================
:: WORKFLOW 06 — Exportar datos a Google Sheets
:: Frecuencia: mensual o bajo demanda
:: Descripción: Sincroniza los datos del dashboard (publicaciones
::   de permisos energéticos) con Google Sheets para compartir
::   o editar manualmente. Requiere credentials.json válido.
::
:: Requisito previo: credentials.json en la raíz del proyecto
::   (Google Service Account con acceso a la hoja destino)
:: ============================================================
echo [%date% %time%] Exportando a Google Sheets...
cd /d "%~dp0.."

if not exist credentials.json (
    echo ERROR: no se encuentra credentials.json
    echo Descarga las credenciales de Google Cloud Console y ponlas en la raiz del proyecto.
    exit /b 1
)

python sheets_exporter.py
if %errorlevel% neq 0 (
    echo ERROR en sheets_exporter.py
    exit /b 1
)

echo [%date% %time%] Exportacion a Google Sheets completada.
