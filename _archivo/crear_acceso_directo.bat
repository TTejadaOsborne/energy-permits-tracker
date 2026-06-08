@echo off
REM Ejecutar esto UNA SOLA VEZ para crear el acceso directo en el escritorio
REM Doble clic en "Nodalys - Permisos" para abrir la herramienta directamente

set URL=https://TTejadaOsborne.github.io/energy-permits-tracker/

REM Crear acceso directo en el escritorio
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Nodalys - Permisos.lnk'); $s.TargetPath = 'https://TTejadaOsborne.github.io/energy-permits-tracker/'; $s.Description = 'Nodalys Permisos Energeticos'; $s.Save()"

echo.
echo Acceso directo creado en el escritorio: "Nodalys - Permisos"
echo Puedes hacer doble clic en el para abrir la herramienta.
echo.
pause
