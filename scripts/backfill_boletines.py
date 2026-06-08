"""
backfill_boletines.py
─────────────────────
Re-escanea boletines concretos para fechas ya procesadas y añade
las nuevas publicaciones al Google Sheet SIN borrar las existentes.

Uso:
  python backfill_boletines.py                        # BOPV + DOE en todas las fechas
  python backfill_boletines.py --boletines BOPV       # solo BOPV
  python backfill_boletines.py --desde 20260401       # desde esa fecha
  python backfill_boletines.py --dry                  # sin escribir al Sheet

BON y BOLR tienen acceso histórico via script-tag del indice (implementado 2026-05-19).
"""

import json, logging, os, sys, time
from datetime import datetime
from pathlib import Path

# ── cargar .env ──────────────────────────────────────────────────────────────
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _l in open(_env, encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1); os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent))

import argparse
from scrapers.multi_scraper import MultiBoletinScraper
from extractor.energy_extractor import EnergyExtractor
from sheets_exporter import get_client, resultado_a_fila, SPREADSHEET_ID, SHEET_NAME, COLUMNAS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Boletines que SÍ tienen acceso histórico por fecha
BACKFILLABLES = ["BOE", "BOCM", "BOCyL", "DOCM", "BOJA", "DOGV", "DOGC",
                 "DOG", "BOPA", "BOC", "BORM", "BOA", "BOPV", "DOE", "BON", "BOLR"]
# BON y BOLR ahora tienen acceso histórico por fecha
NO_HISTORICO  = []  # todos los boletines soportan histórico


def ids_en_sheet(ws) -> set:
    """Devuelve el conjunto de IDs (col A) ya presentes en el Sheet."""
    vals = ws.col_values(1)  # columna id_boe
    return set(v for v in vals[1:] if v)  # skip cabecera


def ids_en_extraido(fecha: str) -> set:
    """IDs ya en el archivo energy_extraido_FECHA.json."""
    p = Path("output") / f"energy_extraido_{fecha}.json"
    if not p.exists():
        return set()
    d = json.load(open(p, encoding="utf-8"))
    return {r["id"] for r in d.get("resultados", []) if r.get("id")}


def fechas_disponibles(desde: str = None, hasta: str = None) -> list:
    """Lista de fechas con energy_extraido existente, ordenadas."""
    fechas = []
    for f in sorted(Path("output").glob("energy_extraido_*.json")):
        fecha = f.stem.replace("energy_extraido_", "")
        if desde and fecha < desde: continue
        if hasta and fecha > hasta: continue
        fechas.append(fecha)
    return fechas


def boletines_ya_en_extraido(fecha: str) -> set:
    """Boletines que ya tienen items (es_energetico) en el extraído."""
    p = Path("output") / f"energy_extraido_{fecha}.json"
    if not p.exists():
        return set()
    d = json.load(open(p, encoding="utf-8"))
    return {r["boletin"] for r in d.get("resultados", []) if r.get("es_energetico")}


def append_a_extraido(fecha: str, nuevos: list):
    """Añade nuevos resultados al energy_extraido existente."""
    p = Path("output") / f"energy_extraido_{fecha}.json"
    if p.exists():
        d = json.load(open(p, encoding="utf-8"))
    else:
        d = {"fecha": fecha, "total": 0, "resultados": []}
    ids_previos = {r["id"] for r in d["resultados"] if r.get("id")}
    añadidos = [r for r in nuevos if r.get("id") not in ids_previos]
    d["resultados"].extend(añadidos)
    d["total"] = len(d["resultados"])
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return len(añadidos)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boletines", nargs="+", default=["BOPV", "DOE", "BON", "BOLR"],
                   choices=BACKFILLABLES,
                   help="Boletines a backfillear (default: BOPV DOE)")
    p.add_argument("--desde", default=None, help="Fecha inicio YYYYMMDD")
    p.add_argument("--hasta", default=None, help="Fecha fin YYYYMMDD (inclusive)")
    p.add_argument("--dry",   action="store_true", help="Sin escribir al Sheet")
    p.add_argument("--api-key", default=None)
    args = p.parse_args()

    # Comprobar que ningún boletín es de tipo "no histórico"
    for b in args.boletines:
        if b in NO_HISTORICO:
            logger.error(f"{b} no tiene acceso histórico por fecha. Elimínalo de --boletines.")
            sys.exit(1)

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.dry:
        logger.error("Falta ANTHROPIC_API_KEY. Usa --dry para probar sin extracción AI.")
        sys.exit(1)

    fechas = fechas_disponibles(args.desde, args.hasta)
    logger.info(f"Fechas a procesar: {len(fechas)} ({fechas[0] if fechas else '?'} → {fechas[-1] if fechas else '?'})")
    logger.info(f"Boletines: {args.boletines}")

    if not fechas:
        logger.warning("No hay fechas en el rango indicado.")
        return

    # ── Conectar al Sheet ─────────────────────────────────────────────────────
    if not args.dry:
        try:
            gc = get_client()
            sh = gc.open_by_key(SPREADSHEET_ID)
            ws = sh.worksheet(SHEET_NAME)
            ids_sheet = ids_en_sheet(ws)
            logger.info(f"Sheet conectado. IDs existentes: {len(ids_sheet)}")
        except Exception as e:
            logger.error(f"Error Google Sheets: {e}")
            sys.exit(1)
    else:
        ids_sheet = set()
        ws = None

    extractor = EnergyExtractor(api_key=api_key) if api_key else None

    total_nuevos = 0
    scraper = MultiBoletinScraper(output_dir="data")

    for fecha in fechas:
        bols_presentes = boletines_ya_en_extraido(fecha)
        # Solo procesar boletines que NO están ya en el extraído para esta fecha
        bols_pendientes = [b for b in args.boletines if b not in bols_presentes]

        if not bols_pendientes:
            logger.debug(f"{fecha}: {args.boletines} ya presentes → saltar")
            continue

        logger.info(f"{fecha}: scraping {bols_pendientes}")
        items_raw = scraper.scrape_dia(fecha=fecha, boletines=bols_pendientes)

        if not items_raw:
            logger.info(f"  {fecha}: 0 items raw")
            continue

        logger.info(f"  {fecha}: {len(items_raw)} items raw encontrados")

        # Filtrar IDs ya en el Sheet
        items_nuevos = [i for i in items_raw if i.get("id") not in ids_sheet]
        if not items_nuevos:
            logger.info(f"  {fecha}: todos ya estaban en el Sheet")
            continue

        if args.dry:
            logger.info(f"  [DRY] {fecha}: {len(items_nuevos)} items nuevos para {bols_pendientes}")
            total_nuevos += len(items_nuevos)
            continue

        # ── Extracción AI ─────────────────────────────────────────────────────
        resultado = extractor.procesar_batch(items_nuevos, fecha)
        energeticos = [r for r in resultado["resultados"] if r.get("es_energetico")]
        logger.info(f"  {fecha}: {len(energeticos)} energéticos extraídos (coste ${resultado['coste_usd']:.5f})")

        if not energeticos:
            continue

        # ── Añadir al extraído local ──────────────────────────────────────────
        append_a_extraido(fecha, resultado["resultados"])

        # ── Append al Sheet ───────────────────────────────────────────────────
        filas = [resultado_a_fila(r) for r in energeticos
                 if r.get("id") not in ids_sheet]
        if filas:
            ws.append_rows(filas, value_input_option="USER_ENTERED")
            ids_sheet.update(r.get("id","") for r in energeticos)
            total_nuevos += len(filas)
            logger.info(f"  ✅ {fecha}: {len(filas)} filas añadidas al Sheet")

        time.sleep(1.5)  # respetar rate limit Sheets API

    logger.info(f"\n{'═'*50}")
    logger.info(f"BACKFILL COMPLETO — {total_nuevos} filas {'(dry)' if args.dry else 'añadidas al Sheet'}")
    logger.info(f"{'═'*50}")


if __name__ == "__main__":
    main()
