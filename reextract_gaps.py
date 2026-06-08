#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reextract_gaps.py — Re-extrae con IA los meses que fallaron por falta de créditos API.

Usa los energy_raw_*.json ya descargados (no re-descarga nada).
Solo llama a EnergyExtractor.procesar_batch() para cada fecha pendiente.

Uso:
  python reextract_gaps.py                   # pide API key, procesa meses con 0 exitosos
  python reextract_gaps.py sk-ant-xxx        # con API key
  python reextract_gaps.py sk-ant-xxx --dry  # sólo muestra lo que haría
  python reextract_gaps.py sk-ant-xxx --mes 202303  # un mes específico
"""

import os, sys, json, argparse
from pathlib import Path
from datetime import date

# ── Asegurar que el directorio de trabajo es el del script ───────────────────
os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent))

from extractor.energy_extractor import EnergyExtractor

DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")

# ── Meses afectados conocidos (créditos insuficientes en su momento) ─────────
MESES_CON_GAPS = [
    "202301", "202303", "202304", "202305", "202306",
    "202307", "202308", "202401", "202402", "202403", "202404",
]


def get_fechas_raw(mes: str) -> list[str]:
    """Devuelve las fechas (YYYYMMDD) que tienen energy_raw_*.json para ese mes."""
    yr, mo = mes[:4], mes[4:]
    return sorted(
        f.name.replace("energy_raw_", "").replace(".json", "")
        for f in DATA_DIR.glob(f"energy_raw_{yr}{mo}*.json")
    )


def tiene_exitos(fecha: str) -> bool:
    """True si el energy_extraido_*.json ya tiene al menos 1 extracción exitosa."""
    fp = OUTPUT_DIR / f"energy_extraido_{fecha}.json"
    if not fp.exists():
        return False
    try:
        d = json.loads(fp.read_text(encoding="utf-8"))
        return (d.get("exitosos", 0) or 0) > 0
    except Exception:
        return False


def load_items(fecha: str) -> list:
    """Lee los items del energy_raw_*.json de esa fecha."""
    fp = DATA_DIR / f"energy_raw_{fecha}.json"
    if not fp.exists():
        return []
    d = json.loads(fp.read_text(encoding="utf-8"))
    return d.get("items", [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("api_key", nargs="?", help="ANTHROPIC_API_KEY")
    parser.add_argument("--dry",   action="store_true", help="No ejecutar, sólo listar")
    parser.add_argument("--mes",   help="Procesar sólo este mes (YYYYMM)")
    parser.add_argument("--force", action="store_true", help="Re-procesar aunque ya tenga exitosos")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY") or input("API Key (sk-ant-...): ").strip()
    if not api_key.startswith("sk-"):
        print("❌ API key inválida"); sys.exit(1)

    meses = [args.mes] if args.mes else MESES_CON_GAPS

    # ── Inventario de trabajo ────────────────────────────────────────────────
    plan = []  # [(mes, fecha, n_items)]
    for mes in meses:
        fechas = get_fechas_raw(mes)
        for fecha in fechas:
            items = load_items(fecha)
            if not items:
                continue
            if not args.force and tiene_exitos(fecha):
                continue
            plan.append((mes, fecha, items))

    if not plan:
        print("✅ No hay nada pendiente. Todos los meses tienen extracciones exitosas.")
        return

    total_items = sum(len(its) for _, _, its in plan)
    coste_est   = total_items * 0.002  # ~$0.002/item con Haiku
    print(f"\n{'═'*60}")
    print(f"  RE-EXTRACCIÓN DE GAPS")
    print(f"{'═'*60}")
    print(f"  Fechas a procesar : {len(plan)}")
    print(f"  Items totales     : {total_items}")
    print(f"  Coste estimado    : ${coste_est:.2f} USD (Haiku)")
    print(f"{'═'*60}")
    for mes, fecha, its in plan:
        print(f"  {fecha}  →  {len(its)} items")

    if args.dry:
        print("\n[--dry mode: no se procesa nada]")
        return

    confirm = input(f"\n¿Continuar? (s/N): ").strip().lower()
    if confirm != "s":
        print("Cancelado.")
        return

    # ── Procesado ────────────────────────────────────────────────────────────
    extractor = EnergyExtractor(api_key=api_key)
    ok, err = 0, 0

    for i, (mes, fecha, items) in enumerate(plan, 1):
        print(f"\n[{i}/{len(plan)}] {fecha}  ({len(items)} items)...")
        try:
            res = extractor.procesar_batch(items, fecha)
            exitosos = res.get("exitosos", 0)
            errores  = res.get("errores", 0)
            coste    = res.get("coste_usd", 0)
            print(f"  ✓ {exitosos} exitosos, {errores} errores  — ${coste:.4f}")
            ok += exitosos
            err += errores
        except Exception as e:
            print(f"  ❌ Error: {e}")
            err += len(items)

    print(f"\n{'═'*60}")
    print(f"  RESULTADO FINAL")
    print(f"  Exitosos : {ok}")
    print(f"  Errores  : {err}")
    print(f"{'═'*60}")
    print("\nPróximo paso: regenerar projects.json y projects_data.js")
    print("  python project_resolver.py")
    print("  (o ejecutar la opción correspondiente en alimentar_bbdd.py)\n")


if __name__ == "__main__":
    main()
