#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair_corrupt_jsons.py — Detecta y reprocesa JSONs corruptos.

Un JSON corrupto es aquel que tiene energeticos>0 pero resultados=[],
lo que indica que el extractor procesó ítems pero no los guardó.

Uso:
  python repair_corrupt_jsons.py                  # solo lista corruptos
  python repair_corrupt_jsons.py --fix            # elimina y re-procesa
  python repair_corrupt_jsons.py --fix sk-ant-xx  # API key directa
"""

import os, sys, json, subprocess
from pathlib import Path
from datetime import date

OUTPUT_DIR = Path("output")
BOLETINES = [
    "BOE", "BOCyL", "BOCM", "DOCM", "DOG", "BOJA", "BOC",
    "BOA", "BOPV", "DOE", "BON", "BOLR",
]

def detectar_corruptos():
    corrupt = []
    for f in sorted(OUTPUT_DIR.glob("energy_extraido_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            n_e = data.get("energeticos", 0)
            n_r = len(data.get("resultados", []))
            if n_e > 0 and n_r == 0:
                corrupt.append(f.stem.replace("energy_extraido_", ""))
        except Exception:
            pass
    return corrupt

def limpiar_seen_urls(fechas):
    """Elimina del seen_urls.json las entradas de las fechas a re-procesar."""
    seen_path = Path("references") / "seen_urls.json"
    if not seen_path.exists():
        return 0
    seen = json.loads(seen_path.read_text(encoding="utf-8"))
    antes = len(seen)
    seen = {url: meta for url, meta in seen.items()
            if meta.get("fecha", "") not in set(fechas)}
    seen_path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    return antes - len(seen)

def main():
    args = sys.argv[1:]
    fix_mode = "--fix" in args
    api_args = [a for a in args if not a.startswith("--")]
    api_key  = api_args[0] if api_args else ""

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║  Reparación de JSONs corruptos           ║")
    print("  ╚══════════════════════════════════════════╝")

    corrupt = detectar_corruptos()
    print(f"\n  JSONs corruptos detectados: {len(corrupt)}")
    for fecha in corrupt:
        print(f"    {fecha}")

    if not corrupt:
        print("\n  Sin corruptos — no hay nada que reparar.")
        return

    if not fix_mode:
        print("\n  Añade --fix para eliminarlos y re-procesarlos:")
        print(f"  python repair_corrupt_jsons.py --fix")
        return

    # API key
    if not api_key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"\'')
    if not api_key:
        api_key = input("\n  Anthropic API key: ").strip()
    if not api_key:
        print("  ERROR: se necesita la API key.")
        sys.exit(1)

    # 1. Eliminar JSONs corruptos
    print(f"\n  Eliminando {len(corrupt)} JSONs corruptos...")
    for fecha in corrupt:
        f = OUTPUT_DIR / f"energy_extraido_{fecha}.json"
        if f.exists():
            f.unlink()
    print("  OK")

    # 2. Limpiar seen_urls.json
    removed = limpiar_seen_urls(corrupt)
    print(f"  seen_urls.json: {removed} entradas eliminadas")

    # 3. Re-procesar
    print(f"\n  Re-procesando {len(corrupt)} fechas...\n")
    ok = 0
    for i, fecha in enumerate(corrupt, 1):
        print(f"  [{i}/{len(corrupt)}] {fecha}")
        subprocess.run(
            [sys.executable, "pipeline.py", "--fecha", fecha,
             "--boletines"] + BOLETINES + ["--api-key", api_key]
        )
        out = OUTPUT_DIR / f"energy_extraido_{fecha}.json"
        if out.exists():
            data = json.loads(out.read_text(encoding="utf-8"))
            n_r = len(data.get("resultados", []))
            n_e = data.get("energeticos", 0)
            if n_e > 0 and n_r == 0:
                print(f"    ⚠  Sigue corrupto tras re-proceso")
            elif n_r > 0:
                print(f"    ✓  {n_r} resultados guardados")
                subprocess.run([sys.executable, "sheets_exporter.py", str(out)])
                ok += 1
            else:
                print(f"    --  Sin ítems energéticos (normal)")
        else:
            print(f"    --  Sin ítems (festivo o sin publicaciones)")

    # 4. Regenerar projects
    print(f"\n  Regenerando projects.json...")
    try:
        import project_resolver as pr
        records = pr.load_all_records(pr.OUTPUT_DIR)
        uf, _ = pr.resolve_projects(records)
        projs = pr.build_projects(records, uf)
        with open("projects.json", "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "generado": date.today().isoformat(),
                       "total": len(projs), "proyectos": projs},
                      f, ensure_ascii=False, indent=2)
        pjs = Path("projects_data.js")
        pj = json.loads(Path("projects.json").read_text(encoding="utf-8"))
        pjs.write_text("window.PROJECTS_INLINE = " + json.dumps(pj, ensure_ascii=False) + ";",
                       encoding="utf-8")
        print(f"  OK  {len(projs)} proyectos — projects_data.js actualizado")
    except Exception as e:
        print(f"  WARN: {e}")

    print(f"\n  COMPLETADO: {ok}/{len(corrupt)} fechas con resultados recuperados")
    print()

if __name__ == "__main__":
    main()
