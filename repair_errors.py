#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair_errors.py — Re-procesa fechas con JSONs erróneos.

Detecta y re-procesa fechas donde los resultados del extractor fallaron por:
  - Errores de conexión (network)
  - Errores de API (400/529/500)
  - Errores de parsing JSON del LLM
  - Errores de código del extractor (bug 'name re is not defined', ya corregido)

Uso:
  python repair_errors.py                    # lista las fechas afectadas
  python repair_errors.py --fix              # re-procesa todas
  python repair_errors.py --fix --year 2023  # solo un año
  python repair_errors.py --fix sk-ant-xxx   # API key directa
"""

import os, sys, json, subprocess
from pathlib import Path
from datetime import date
from collections import Counter

OUTPUT_DIR = Path("output")
BOLETINES  = ["BOE","BOCyL","BOCM","DOCM","DOG","BOJA","BOC","BOA","BOPV","DOE","BON","BOLR"]

def detectar_con_errores(only_year=None):
    """Devuelve lista de fechas donde TODOS o ALGUNOS resultados tienen estado_validacion=error."""
    all_error  = []  # ningún resultado válido
    some_error = []  # mezcla de ok + error

    for f in sorted(OUTPUT_DIR.glob("energy_extraido_*.json")):
        fecha = f.stem.replace("energy_extraido_", "")
        if only_year and not fecha.startswith(str(only_year)):
            continue
        try:
            data  = json.loads(f.read_text(encoding="utf-8"))
            res   = data.get("resultados", [])
            errors = [r for r in res if r.get("estado_validacion") == "error"]
            valid  = [r for r in res if r.get("es_energetico") and r.get("datos")
                      and r.get("estado_validacion") != "error"]
            if not errors:
                continue
            if not valid:
                all_error.append(fecha)
            else:
                some_error.append((fecha, len(valid), len(errors)))
        except Exception:
            pass

    return all_error, some_error

def classify_errors(all_error, some_error):
    """Agrupa por tipo de error para informe."""
    counts = Counter()
    for f in sorted(OUTPUT_DIR.glob("energy_extraido_*.json")):
        fecha = f.stem.replace("energy_extraido_", "")
        if fecha not in set(all_error) | {f for f, _, _ in some_error}:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            errs = [str(r.get("error","")) for r in data.get("resultados",[])
                    if r.get("estado_validacion") == "error"]
            main = errs[0] if errs else ""
            if "Connection" in main:        counts["Conexión fallida"] += 1
            elif "400" in main:             counts["API 400 (credenciales/modelo)"] += 1
            elif "529" in main:             counts["API 529 (sobrecarga)"] += 1
            elif "500" in main:             counts["API 500 (error interno)"] += 1
            elif "name 're'" in main:       counts["Bug regex (ya corregido)"] += 1
            elif "JSON" in main or \
                 "Expecting" in main or \
                 "Unterminated" in main:    counts["JSON parse error"] += 1
            else:                           counts["Otro"] += 1
        except Exception:
            pass
    return counts

def limpiar_seen_urls(fechas):
    seen_path = Path("references") / "seen_urls.json"
    if not seen_path.exists():
        return 0
    seen = json.loads(seen_path.read_text(encoding="utf-8"))
    antes = len(seen)
    seen = {url: m for url, m in seen.items() if m.get("fecha","") not in set(fechas)}
    seen_path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    return antes - len(seen)

def main():
    args      = sys.argv[1:]
    fix_mode  = "--fix" in args
    only_year = None
    for i, a in enumerate(args):
        if a == "--year" and i+1 < len(args):
            only_year = args[i+1]
    api_args = [a for a in args if not a.startswith("--") and not a.isdigit() or len(a) > 6]
    api_key  = next((a for a in api_args if a.startswith("sk-")), "")

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║  Reparación de JSONs con errores         ║")
    print("  ╚══════════════════════════════════════════╝")

    all_error, some_error = detectar_con_errores(only_year)
    total_fechas = len(all_error) + len(some_error)
    print(f"\n  Fechas con TODOS errores (0 resultados válidos): {len(all_error)}")
    print(f"  Fechas con errores parciales (mix ok+error):      {len(some_error)}")
    print(f"  Total a re-procesar:                              {total_fechas}")

    if total_fechas == 0:
        print("\n  Sin errores — todo correcto.")
        return

    # Clasificación de causas
    by_year = Counter(f[:4] for f in all_error + [f for f,_,_ in some_error])
    print(f"\n  Por año: {dict(sorted(by_year.items()))}")
    counts = classify_errors(all_error, some_error)
    print(f"\n  Causas de error:")
    for cause, n in counts.most_common():
        print(f"    {n:4d}  {cause}")

    if not fix_mode:
        print("\n  Opciones:")
        print("    python repair_errors.py --fix              # re-procesa todas")
        print("    python repair_errors.py --fix --year 2023  # solo 2023")
        return

    # API key
    if not api_key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=",1)[1].strip().strip('"\'')
    if not api_key:
        api_key = input("\n  Anthropic API key: ").strip()
    if not api_key:
        print("  ERROR: API key necesaria.")
        sys.exit(1)

    todas = sorted(set(all_error) | {f for f,_,_ in some_error})

    # 1. Limpiar seen_urls
    removed = limpiar_seen_urls(todas)
    print(f"\n  seen_urls.json: {removed} entradas eliminadas")

    # 2. Eliminar JSONs erróneos para forzar re-proceso
    for fecha in todas:
        fpath = OUTPUT_DIR / f"energy_extraido_{fecha}.json"
        if fpath.exists():
            fpath.unlink()
    print(f"  {len(todas)} JSONs eliminados para re-proceso")

    # 3. Re-procesar
    print(f"\n  Re-procesando {len(todas)} fechas...\n")
    ok = sin_datos = nuevos_errores = 0

    for i, fecha in enumerate(todas, 1):
        sys.stdout.write(f"\r  [{i}/{len(todas)}] {fecha}...   ")
        sys.stdout.flush()
        subprocess.run(
            [sys.executable, "pipeline.py", "--fecha", fecha,
             "--boletines"] + BOLETINES + ["--api-key", api_key],
            capture_output=True  # silencia output individual
        )
        out = OUTPUT_DIR / f"energy_extraido_{fecha}.json"
        if not out.exists():
            sin_datos += 1
            # crear placeholder vacío
            out.write_text(json.dumps({"fecha": fecha, "total": 0, "energeticos": 0,
                "descartados": 0, "exitosos": 0, "errores": 0,
                "tokens": {"input": 0, "output": 0}, "coste_usd": 0.0,
                "alertas_capacidad_liberada": 0, "mw_totales_liberados": 0.0,
                "resultados": []}), encoding="utf-8")
            continue
        data = json.loads(out.read_text(encoding="utf-8"))
        res  = data.get("resultados", [])
        new_errs = [r for r in res if r.get("estado_validacion") == "error"]
        valid    = [r for r in res if r.get("es_energetico") and r.get("datos")
                    and r.get("estado_validacion") != "error"]
        if valid:
            subprocess.run([sys.executable, "sheets_exporter.py", str(out)],
                           capture_output=True)
            ok += 1
        elif new_errs:
            nuevos_errores += 1
        else:
            sin_datos += 1

    print(f"\n\n  RESULTADO:")
    print(f"    ✓ Con datos recuperados:    {ok}")
    print(f"    ○ Sin datos (normal):        {sin_datos}")
    print(f"    ✗ Siguen con errores:        {nuevos_errores}")

    # 4. Regenerar projects
    print(f"\n  Regenerando projects.json + projects_data.js...")
    try:
        import project_resolver as pr
        records = pr.load_all_records(pr.OUTPUT_DIR)
        uf, _   = pr.resolve_projects(records)
        projs   = pr.build_projects(records, uf)
        with open("projects.json", "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "generado": date.today().isoformat(),
                       "total": len(projs), "proyectos": projs},
                      f, ensure_ascii=False, indent=2)
        pj = json.loads(Path("projects.json").read_text(encoding="utf-8"))
        Path("projects_data.js").write_text(
            "window.PROJECTS_INLINE = " + json.dumps(pj, ensure_ascii=False) + ";",
            encoding="utf-8")
        print(f"  OK  {len(projs)} proyectos")
    except Exception as e:
        print(f"  WARN: {e}")

    print()
    if nuevos_errores > 0:
        print(f"  ⚠  {nuevos_errores} fechas siguen fallando — vuelve a ejecutar o revisa la API key.")
    else:
        print("  ✓ Reparación completa.")
    print()

if __name__ == "__main__":
    main()
