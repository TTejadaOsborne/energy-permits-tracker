# autopush.ps1 — Vigila todos los archivos trackeados por git y hace push al detectar cambios
# Ejecutar con: powershell -ExecutionPolicy Bypass -File autopush.ps1

$folder   = Split-Path -Parent $MyInvocation.MyCommand.Path
$interval = 5

# Archivos a vigilar (los que deben estar en GitHub)
$watchFiles = @(
    "index.html",
    "projects.json",
    "projects_data.js",
    "adverse_forecast_data.js",
    "forecast_data.js",
    "sets_capacity.json",
    "sets_history.json",
    "sets_history.json.gz",
    "logo.png",
    ".gitignore",
    ".nojekyll",
    "parse_ree.py",
    "generate_sets_history.py",
    "generate_sets_capacity.py",
    "Monitor_Capacidad_Red_INTEGRADO_v4.xlsx",
    "references\ree_capacidad.csv",
    "references\Mapas_Capacidad_AyC-REE.xlsx",
    "references\endesa_capacidad.csv",
    "references\eredes_capacidad.csv",
    "references\ide_capacidad.csv",
    "references\ufd_capacidad.csv",
    "references\viesgo_capacidad.csv"
)
Write-Host "Nodalys AutoPush activo" -ForegroundColor Green
Write-Host "Vigilando $($watchFiles.Count) archivos en: $folder" -ForegroundColor Gray
Write-Host "Pulsa Ctrl+C para detener`n" -ForegroundColor Gray

# Snapshot inicial de fechas de modificacion
$snapshots = @{}
foreach ($f in $watchFiles) {
    $path = Join-Path $folder $f
    if (Test-Path $path) {
        $snapshots[$f] = (Get-Item $path).LastWriteTime
    }
}

Set-Location $folder

while ($true) {
    Start-Sleep -Seconds $interval

    $changed = @()
    foreach ($f in $watchFiles) {
        $path = Join-Path $folder $f
        if (-not (Test-Path $path)) { continue }
        $current = (Get-Item $path).LastWriteTime
        if (-not $snapshots.ContainsKey($f) -or $current -ne $snapshots[$f]) {
            $snapshots[$f] = $current
            $changed += $f
        }
    }

    if ($changed.Count -gt 0) {
        $ts  = Get-Date -Format "HH:mm:ss"
        $msg = "Auto-update $($changed -join ', ') $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
        Write-Host "[$ts] Cambios detectados: $($changed -join ', ')" -ForegroundColor Yellow

        foreach ($f in $changed) {
            git add $f 2>&1 | Out-Null
        }

        $status = git status --short
        if ($status -ne $null -and $status -ne "") {
            git commit -m $msg 2>&1 | Out-Null
            $result = git push 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[$ts] Push OK - GitHub Pages actualizando (~60s)" -ForegroundColor Green
            } else {
                Write-Host "[$ts] Error en push: $result" -ForegroundColor Red
            }
        } else {
            Write-Host "[$ts] Sin cambios nuevos para commitear" -ForegroundColor Gray
        }
    }
}
