#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_all.py — Alinea Búsqueda, Dashboard y Sheets en un solo comando.

Pasos:
  1. Procesa fechas sin JSON (pipeline + extractor)
  2. Sincroniza todos los JSONs locales pendientes al Sheet
  3. Regenera projects.json + projects_data.js
  4. (Opcional) git commit + push → actualiza GitHub Pages

Uso:
  python sync_all.py                     # pide API key interactivamente
  python sync_all.py sk-ant-xxxxx        # API key como argumento
  python sync_all.py --no-pipeline       # solo sincroniza Sheet + regenera
  python sync_all.py --no-push          # sin git push al final
"""

import os, sys, subprocess, json
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── Configuración ──────────────────────────────────────────────────────────────
BOLETINES = [
    "BOE", "BOCyL", "BOCM", "DOCM", "DOG", "BOJA", "BOC",
    "BOA", "BOPV", "DOE", "BON", "BOLR",
]
OUTPUT_DIR = Path("output")

def _sep(title=""):
    print()
    if title:
        print(f"  {'─'*60}")
        print(f"  {title}")
        print(f"  {'─'*60}")

def _run(*cmd):
    return subprocess.run([sys.executable] + list(cmd), capture_output=False)

def analizar_locales():
    """Fechas con JSON local que tienen datos energéticos."""
    con_datos = {}
    for f in sorted(OUTPUT_DIR.glob("energy_extraido_*.json")):
        fecha_str = f.stem.replace("energy_extraido_", "")
        if len(fecha_str) != 8 or not fecha_str.isdigit():
            continue
        try:
            d = date(int(fecha_str[:4]), int(fecha_str[4:6]), int(fecha_str[6:]))
            data = json.loads(f.read_text(encoding="utf-8"))
            n = len([r for r in data.get("resultados", [])
                     if r.get("es_energetico") and r.get("datos")])
            if n > 0:
                con_datos[d] = n
        except Exception:
            pass
    return con_datos

def detectar_pendientes():
    """Fechas hábiles sin JSON."""
    from alimentar_bbdd import dias_habiles_mes, FECHA_INICIO, analizar_locales as _al
    procesadas, _, _ = _al()
    hoy = date.today()
    pendientes = []
    for anio in range(FECHA_INICIO.year, hoy.year + 1):
        for mes in range(1, 13):
            for d in dias_habiles_mes(anio, mes, hoy):
                if d not in procesadas:
                    pendientes.append(d)
    return sorted(pendientes)

def detectar_no_sincronizadas(con_datos):
    """JSONs con datos que no están en seen_sheet.json."""
    seen_path = Path("references") / "seen_sheet.json"
    seen = {}
    if seen_path.exists():
        try:
            seen = json.loads(seen_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return [d for d in sorted(con_datos) if str(d) not in seen]

def procesar_pendientes(pendientes, api_key):
    """Ejecuta pipeline para cada fecha sin JSON."""
    ok = 0
    for i, d in enumerate(pendientes, 1):
        fecha = d.strftime("%Y%m%d")
        print(f"\n  [{i}/{len(pendientes)}] {fecha}")
        subprocess.run(
            [sys.executable, "pipeline.py", "--fecha", fecha,
             "--boletines"] + BOLETINES + ["--api-key", api_key]
        )
        out = OUTPUT_DIR / f"energy_extraido_{fecha}.json"
        if out.exists():
            _run("sheets_exporter.py", str(out))
            ok += 1
        else:
            # Crear JSON vacío para marcar como procesado
            OUTPUT_DIR.mkdir(exist_ok=True)
            out.write_text(json.dumps({
                "fecha": fecha, "total": 0, "energeticos": 0,
                "descartados": 0, "exitosos": 0, "errores": 0,
                "tokens": {"input": 0, "output": 0}, "coste_usd": 0.0,
                "alertas_capacidad_liberada": 0, "mw_totales_liberados": 0.0,
                "resultados": []
            }), encoding="utf-8")
    return ok

def sincronizar_sheet(no_sync):
    """Sube al Sheet los JSONs pendientes."""
    import time
    ok = errores = 0
    seen_path = Path("references") / "seen_sheet.json"
    seen = {}
    if seen_path.exists():
        try: seen = json.loads(seen_path.read_text(encoding="utf-8"))
        except Exception: pass

    for i, d in enumerate(no_sync, 1):
        fecha = d.strftime("%Y%m%d")
        fpath = OUTPUT_DIR / f"energy_extraido_{fecha}.json"
        if not fpath.exists():
            continue
        sys.stdout.write(f"\r  [{i}/{len(no_sync)}] {fecha}...   ")
        sys.stdout.flush()
        intentos = 0
        while intentos < 3:
            result = subprocess.run(
                [sys.executable, "sheets_exporter.py", str(fpath)],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                ok += 1
                seen[str(d)] = {"fecha": fecha}
                seen_path.parent.mkdir(exist_ok=True)
                seen_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
                break
            err = (result.stderr or result.stdout or "").strip()
            if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                intentos += 1
                if intentos < 3:
                    print(f"\n  Rate-limit, esperando 30s...")
                    time.sleep(30)
                    continue
            errores += 1
            break
        time.sleep(0.8)
    print()
    return ok, errores

def regenerar_projects():
    """Reconstruye projects.json y projects_data.js."""
    print("  Regenerando projects.json...")
    try:
        import project_resolver as pr, json as _j
        records  = pr.load_all_records(pr.OUTPUT_DIR)
        uf, conf = pr.resolve_projects(records)
        projs    = pr.build_projects(records, uf)
        with open("projects.json", "w", encoding="utf-8") as f:
            _j.dump({"version": "1.0", "generado": date.today().isoformat(),
                     "total": len(projs), "proyectos": projs}, f,
                    ensure_ascii=False, indent=2)
        print(f"  OK  {len(projs)} proyectos")
    except Exception as e:
        print(f"  WARN  No se pudo regenerar projects.json: {e}")
        return False

    print("  Regenerando projects_data.js...")
    try:
        js_path = Path("projects_data.js")
        pj = json.loads(Path("projects.json").read_text(encoding="utf-8"))
        js_path.write_text(
            "window.PROJECTS_INLINE = " + json.dumps(pj, ensure_ascii=False) + ";",
            encoding="utf-8"
        )
        print(f"  OK  projects_data.js actualizado ({js_path.stat().st_size // 1024} KB)")
        return True
    except Exception as e:
        print(f"  WARN  No se pudo generar projects_data.js: {e}")
        return False

def git_push():
    """Commit y push a GitHub Pages."""
    try:
        today = date.today().strftime("%Y%m%d")
        # projects_data.js may be in .gitignore — force-add it
        subprocess.run(["git", "add", "index.html", "projects.json"], check=True)
        subprocess.run(["git", "add", "-f", "projects_data.js"], check=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True
        )
        if result.returncode == 0:
            print("  Sin cambios que publicar.")
            return True
        subprocess.run(
            ["git", "commit", "-m", f"data: sync {today}"], check=True
        )
        # Push to main (GitHub Pages default branch)
        # Also push master for backup
        subprocess.run(["git", "push", "--set-upstream", "origin", "master"], check=True)
        try:
            subprocess.run(["git", "push", "origin", "master:main"], check=True)
        except Exception:
            pass  # main may need manual merge if diverged
        print("  OK  Publicado en GitHub Pages")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  WARN  Git push falló: {e}")
        return False

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    no_pipeline = "--no-pipeline" in args
    no_push     = "--no-push"     in args
    api_args    = [a for a in args if not a.startswith("--")]
    api_key     = api_args[0] if api_args else ""

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║  NODALYS — Sincronización completa       ║")
    print("  ╚══════════════════════════════════════════╝")

    # ── PASO 1: Fechas sin JSON ──────────────────────────────────────────────
    if not no_pipeline:
        _sep("PASO 1 / 4 — Fechas pendientes de procesar")
        try:
            pendientes = detectar_pendientes()
        except Exception as e:
            print(f"  WARN  No se pudo obtener pendientes: {e}")
            pendientes = []

        if pendientes:
            print(f"  {len(pendientes)} fechas sin JSON")
            if not api_key:
                env_path = Path(".env")
                if env_path.exists():
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        if line.strip().startswith("ANTHROPIC_API_KEY="):
                            api_key = line.split("=", 1)[1].strip().strip('"\'')
            if not api_key:
                api_key = input("\n  Anthropic API key: ").strip()
            if not api_key:
                print("  ERROR: API key necesaria. Usa --no-pipeline para saltar este paso.")
                sys.exit(1)
            ok = procesar_pendientes(pendientes, api_key)
            print(f"\n  PASO 1 completo: {ok}/{len(pendientes)} con resultados")
        else:
            print("  Sin fechas pendientes.")
    else:
        print("\n  PASO 1 omitido (--no-pipeline)")

    # ── PASO 2: Sincronizar Sheet ────────────────────────────────────────────
    _sep("PASO 2 / 4 — Sincronizar al Sheet")
    con_datos = analizar_locales()
    no_sync   = detectar_no_sincronizadas(con_datos)
    if no_sync:
        print(f"  {len(no_sync)} fechas sin sincronizar al Sheet")
        ok, err = sincronizar_sheet(no_sync)
        print(f"  PASO 2 completo: {ok} subidas, {err} errores")
    else:
        print("  Sheet ya está sincronizado.")

    # ── PASO 3: Regenerar datos ──────────────────────────────────────────────
    _sep("PASO 3 / 4 — Regenerar projects.json + projects_data.js")
    regenerar_projects()

    # ── PASO 4: Git push ─────────────────────────────────────────────────────
    if not no_push:
        _sep("PASO 4 / 4 — Publicar en GitHub Pages")
        git_push()
    else:
        print("\n  PASO 4 omitido (--no-push)")

    print()
    print("  ✓ Sincronización completa")
    print()

if __name__ == "__main__":
    main()
