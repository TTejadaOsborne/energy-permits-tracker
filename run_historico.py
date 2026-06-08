"""
run_historico.py — Backfill historico mes a mes
================================================
Procesa todos los dias laborables de un mes que NO tengan ya output,
ejecuta scraping + extraccion AI y exporta a Google Sheets.

Uso:
  python run_historico.py --mes 202512          # diciembre 2025
  python run_historico.py --mes 202511          # noviembre 2025
  python run_historico.py --desde 20251201 --hasta 20251231
  python run_historico.py --mes 202512 --dry    # sin AI ni Sheets
  python run_historico.py --mes 202512 --estimar  # solo coste estimado
  python run_historico.py --mes 202512 --modelo sonnet  # mas preciso

El script salta automaticamente los dias ya procesados (tiene output).
Muestra progreso, coste acumulado y permite Ctrl+C para parar entre fechas.
"""

import argparse, json, logging, os, sys, time
from datetime import date, timedelta
from pathlib import Path

# ── cargar .env ───────────────────────────────────────────────────────────────
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _l in open(_env, encoding="utf-8"):
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/historico.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)
Path("logs").mkdir(exist_ok=True)

from scrapers.multi_scraper import MultiBoletinScraper
from extractor.energy_extractor import EnergyExtractor


# ─── Helpers ──────────────────────────────────────────────────────────────────

def dias_laborables(desde: str, hasta: str) -> list:
    """Lista de fechas YYYYMMDD de lunes a viernes en el rango dado."""
    d0 = date(int(desde[:4]), int(desde[4:6]), int(desde[6:8]))
    d1 = date(int(hasta[:4]), int(hasta[4:6]), int(hasta[6:8]))
    dias = []
    cur = d0
    while cur <= d1:
        if cur.weekday() < 5:   # lunes=0 ... viernes=4
            dias.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return dias


def tiene_output(fecha: str) -> bool:
    return (Path("output") / f"energy_extraido_{fecha}.json").exists()


def tiene_raw(fecha: str) -> bool:
    return (Path("data") / f"energy_raw_{fecha}.json").exists()


def estimar_coste(n_dias: int, items_por_dia: float = 15, modelo: str = "haiku") -> float:
    inp = n_dias * items_por_dia * 2500
    out = n_dias * items_por_dia * 600
    if modelo == "haiku":
        return (inp / 1e6) * 0.80 + (out / 1e6) * 4.0
    else:
        return (inp / 1e6) * 3.0  + (out / 1e6) * 15.0


def exportar_sheets(fecha: str) -> bool:
    archivo = f"output/energy_extraido_{fecha}.json"
    if not Path(archivo).exists():
        return False
    try:
        from sheets_exporter import exportar_a_sheets
        res = exportar_a_sheets(archivo)
        logger.info("  Sheets: %s", res)
        return True
    except Exception as e:
        logger.warning("  Sheets export fallido: %s", e)
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--mes",   type=str, help="Mes YYYYMM (p.ej. 202512)")
    group.add_argument("--desde", type=str, help="Fecha inicio YYYYMMDD (con --hasta)")
    p.add_argument("--hasta",   type=str, help="Fecha fin YYYYMMDD")
    p.add_argument("--modelo",  choices=["haiku","sonnet"], default="haiku")
    p.add_argument("--dry",     action="store_true", help="Sin AI ni Sheets (solo scraping)")
    p.add_argument("--estimar", action="store_true", help="Solo muestra estimacion de coste y sale")
    p.add_argument("--no-sheets", action="store_true", help="No exportar a Google Sheets")
    p.add_argument("--api-key", type=str)
    args = p.parse_args()

    # Calcular rango
    if args.mes:
        anio, mes = int(args.mes[:4]), int(args.mes[4:])
        import calendar
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        desde = f"{anio}{mes:02d}01"
        hasta = f"{anio}{mes:02d}{ultimo_dia:02d}"
    else:
        desde = args.desde
        hasta = args.hasta or args.desde

    dias = dias_laborables(desde, hasta)
    pendientes = [d for d in dias if not tiene_output(d)]
    ya_hechos  = [d for d in dias if tiene_output(d)]

    print(f"\n{'='*60}")
    print(f"  HISTORICO {desde[:6]} ({desde} → {hasta})")
    print(f"{'='*60}")
    print(f"  Dias laborables  : {len(dias)}")
    print(f"  Ya procesados    : {len(ya_hechos)}")
    print(f"  Pendientes       : {len(pendientes)}")
    if pendientes:
        print(f"  Primero          : {pendientes[0]}")
        print(f"  Ultimo           : {pendientes[-1]}")

    if not pendientes:
        print("\n  Todos los dias ya tienen output. Nada que hacer.")
        return

    # Estimacion de coste
    coste_est = estimar_coste(len(pendientes), modelo=args.modelo)
    print(f"\n  Coste estimado   : ${coste_est:.3f} USD  "
          f"(~{coste_est*0.93:.3f} EUR)  [{args.modelo}]")
    print(f"  Nota: ~15 items/dia promedio — puede variar")

    if args.estimar:
        print("\n  [--estimar] Saliendo sin ejecutar.")
        return

    if args.dry:
        print("\n  [--dry] Solo scraping, sin AI ni Sheets.")

    # API key
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.dry:
        print("\n  ERROR: Falta ANTHROPIC_API_KEY en .env")
        sys.exit(1)

    scraper   = MultiBoletinScraper(output_dir="data")
    extractor = EnergyExtractor(api_key=api_key) if (api_key and not args.dry) else None
    if extractor and args.modelo == "sonnet":
        extractor.upgrade_to_sonnet()

    coste_total   = 0.0
    items_total   = 0
    fechas_ok     = 0
    fechas_vacias = 0

    print(f"\n{'─'*60}")

    for i, fecha in enumerate(pendientes, 1):
        print(f"\n[{i}/{len(pendientes)}] {fecha}", end="  ", flush=True)

        try:
            # ── Scraping ──────────────────────────────────────────────────────
            items_raw = scraper.scrape_dia(fecha=fecha)

            if not items_raw:
                print(f"0 items  (sin publicaciones)")
                fechas_vacias += 1
                # Crear output vacio para no reprocesar
                out_vacio = Path("output") / f"energy_extraido_{fecha}.json"
                with open(out_vacio, "w", encoding="utf-8") as f:
                    json.dump({"fecha": fecha, "total": 0, "resultados": []},
                              f, ensure_ascii=False)
                continue

            if args.dry:
                print(f"{len(items_raw)} items raw  [dry]")
                fechas_ok += 1
                continue

            # ── Extraccion AI ─────────────────────────────────────────────────
            resultado = extractor.procesar_batch(items_raw, fecha)
            energeticos = sum(1 for r in resultado["resultados"] if r.get("es_energetico"))
            coste = resultado["coste_usd"]
            coste_total += coste
            items_total += energeticos

            print(f"{len(items_raw)} raw  |  {energeticos} energeticos  |  ${coste:.4f}")
            fechas_ok += 1

            # ── Export Sheets ─────────────────────────────────────────────────
            if not args.no_sheets:
                exportar_sheets(fecha)

        except KeyboardInterrupt:
            print(f"\n\n  Ctrl+C — detenido en {fecha}. Progreso guardado.")
            break
        except Exception as e:
            logger.error("  ERROR en %s: %s", fecha, e)

        time.sleep(1.5)

    # ── Resumen ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  RESUMEN {desde[:6]}")
    print(f"{'='*60}")
    print(f"  Fechas procesadas : {fechas_ok}")
    print(f"  Fechas vacias     : {fechas_vacias}")
    print(f"  Items energeticos : {items_total}")
    if not args.dry:
        print(f"  Coste real        : ${coste_total:.4f} USD  (~{coste_total*0.93:.4f} EUR)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
