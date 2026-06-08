"""
repair_liberada.py
──────────────────
Parcheo puntual: detecta registros con estado_permiso negativo
+ potencia_mw conocida pero capacidad_mw_liberada = null.

Aplica: capacidad_mw_liberada = potencia_mw
Guarda el JSON corregido y re-exporta esas fechas a Google Sheets.

Uso:
  python repair_liberada.py              # muestra afectados + aplica parche + Sheets
  python repair_liberada.py --dry        # solo muestra, no escribe nada
  python repair_liberada.py --no-sheets  # parchea JSONs pero no sube a Sheets
"""

import json, sys, logging
from pathlib import Path

# ── cargar .env ───────────────────────────────────────────────────────────────
import os
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _l in open(_env, encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Estados que deberían liberar capacidad
ESTADOS_LIBERAN = {
    "desfavorable", "denegado", "desistido", "caducado",
    "archivado", "revocado", "inadmitido",
}

OUTPUT_DIR = Path("output")


def escanear_afectados() -> list:
    """
    Retorna lista de dicts {archivo, fecha, idx_resultado, id, nombre, estado, mw}
    para cada resultado energético con estado negativo + potencia pero sin capacidad_liberada.
    """
    afectados = []
    for f in sorted(OUTPUT_DIR.glob("energy_extraido_*.json")):
        fecha = f.stem.replace("energy_extraido_", "")
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("No se pudo leer %s: %s", f.name, e)
            continue

        for i, r in enumerate(d.get("resultados", [])):
            if not r.get("es_energetico"):
                continue
            datos = r.get("datos") or {}
            estado   = datos.get("estado_permiso", "")
            potencia = datos.get("potencia_mw")
            liberada = datos.get("capacidad_mw_liberada")

            if estado in ESTADOS_LIBERAN and potencia is not None and liberada is None:
                afectados.append({
                    "archivo": f,
                    "fecha":   fecha,
                    "idx":     i,
                    "id":      r.get("id", "?"),
                    "nombre":  datos.get("nombre_proyecto", "(sin nombre)"),
                    "estado":  estado,
                    "mw":      potencia,
                })
    return afectados


def aplicar_parche(afectados: list) -> set:
    """Agrupa por archivo, aplica parches y guarda. Devuelve set de fechas modificadas."""
    por_archivo: dict = {}
    for a in afectados:
        por_archivo.setdefault(str(a["archivo"]), []).append(a)

    fechas_modificadas = set()
    for fpath_str, casos in por_archivo.items():
        f = Path(fpath_str)
        d = json.loads(f.read_text(encoding="utf-8"))
        for c in casos:
            datos = d["resultados"][c["idx"]]["datos"]
            datos["capacidad_mw_liberada"] = c["mw"]
            logger.info("  Parchado: %s | %.2f MW | %s", c["id"], c["mw"], c["nombre"][:50])
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(d, fp, ensure_ascii=False, indent=2)
        fecha = casos[0]["fecha"]
        fechas_modificadas.add(fecha)
        logger.info("Guardado: %s", f.name)
    return fechas_modificadas


def exportar_fechas(fechas: set):
    """Re-exporta cada fecha al Google Sheet."""
    try:
        from sheets_exporter import exportar_a_sheets
    except ImportError as e:
        logger.error("No se pudo importar sheets_exporter: %s", e)
        return
    for fecha in sorted(fechas):
        archivo = str(OUTPUT_DIR / f"energy_extraido_{fecha}.json")
        try:
            res = exportar_a_sheets(archivo)
            logger.info("  Sheets %s: %s", fecha, res)
        except Exception as e:
            logger.warning("  Sheets %s fallido: %s", fecha, e)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry",       action="store_true", help="Solo muestra, no escribe")
    p.add_argument("--no-sheets", action="store_true", help="Parchea JSONs pero no sube a Sheets")
    args = p.parse_args()

    afectados = escanear_afectados()

    print(f"\n{'='*65}")
    print(f"  REPAIR capacidad_mw_liberada — {len(afectados)} registro(s) afectado(s)")
    print(f"{'='*65}")

    if not afectados:
        print("  Nada que reparar. Todos los registros negativos tienen capacidad_mw_liberada.\n")
        return

    print(f"\n  {'ID':<30} {'Estado':<14} {'MW':>7}  Nombre")
    print(f"  {'-'*30} {'-'*14} {'-'*7}  {'-'*35}")
    for a in afectados:
        print(f"  {a['id']:<30} {a['estado']:<14} {a['mw']:>7.2f}  {a['nombre'][:40]}")

    mw_total = sum(a["mw"] for a in afectados)
    fechas_unicas = set(a["fecha"] for a in afectados)
    print(f"\n  Total MW a reparar: {mw_total:.2f} MW en {len(fechas_unicas)} fecha(s)")

    if args.dry:
        print("\n  [--dry] Sin cambios.\n")
        return

    print()
    fechas_mod = aplicar_parche(afectados)
    print(f"\n  Parche aplicado en {len(fechas_mod)} archivo(s).")

    if not args.no_sheets:
        print("  Exportando a Google Sheets...")
        exportar_fechas(fechas_mod)
    else:
        print("  [--no-sheets] Exportacion omitida.")

    print(f"\n{'='*65}")
    print(f"  COMPLETADO — {len(afectados)} registros reparados")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
