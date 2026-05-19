"""
Energy BOE Pipeline — Orquestador principal
Uso:
  python pipeline.py --ayer
  python pipeline.py --fecha 20240415 --boletines BOE BOJA
  python pipeline.py --ayer --modelo sonnet   (más preciso, más caro)
  python pipeline.py --estimar --items 30
"""

import argparse, json, os, sys, logging

# Fix codificacion en Windows (cp1252 no soporta emojis ni box-drawing)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scrapers.multi_scraper import MultiBoletinScraper
from extractor.energy_extractor import EnergyExtractor

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

BOLETINES_DISPONIBLES = ["BOE", "BOCM", "BOCyL", "DOCM", "BOJA", "DOGV", "DOGC", "DOG", "BOPA", "BOC", "BORM", "BOA", "BOPV", "DOE", "BON", "BOLR"]


def run(fecha=None, boletines=None, max_items=None, api_key=None, modelo="haiku", solo_scraping=False):
    if not fecha:
        fecha = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    print(f"\n{'═'*62}")
    print(f"  ENERGY BOE EXTRACTOR")
    print(f"  Fecha: {fecha}  |  Boletines: {boletines or 'todos'}  |  Modelo: {modelo}")
    print(f"{'═'*62}\n")

    # PASO 1 — Scraping
    scraper = MultiBoletinScraper(output_dir="data")
    items = scraper.scrape_dia(fecha=fecha, boletines=boletines)

    if not items:
        print(f"⚠  Sin items energéticos para {fecha} (fin de semana / festivo / sin publicaciones)")
        return None

    if max_items:
        items = items[:max_items]

    print(f"\n📥 Items relevantes encontrados: {len(items)}")
    by_boletin = {}
    for it in items:
        by_boletin[it["boletin"]] = by_boletin.get(it["boletin"], 0) + 1
    for b, c in sorted(by_boletin.items()):
        print(f"   {b:<8} {c} items")

    if solo_scraping:
        return {"scrapeados": len(items)}

    # PASO 2 — Extracción
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\n❌ Falta ANTHROPIC_API_KEY\n  export ANTHROPIC_API_KEY=sk-ant-...")
        return None

    extractor = EnergyExtractor(api_key=api_key)
    if modelo == "sonnet":
        extractor.upgrade_to_sonnet()

    print(f"\n🧠 Extrayendo con {extractor.model}...")
    resultado = extractor.procesar_batch(items, fecha)

    # PASO 3 — Reporte
    print(f"\n{'═'*62}")
    print(f"  REPORTE")
    print(f"{'═'*62}")
    print(f"  Items procesados   : {resultado['total']}")
    print(f"  Exitosos           : {resultado['exitosos']}")
    print(f"  Errores            : {resultado['errores']}")
    print(f"  Tokens entrada     : {resultado['tokens']['input']:,}")
    print(f"  Tokens salida      : {resultado['tokens']['output']:,}")
    print(f"  Coste estimado     : ${resultado['coste_usd']:.5f} USD")

    print(f"\n  ⚡ ALERTAS CAPACIDAD LIBERADA: {resultado['alertas_capacidad_liberada']}")
    print(f"  ⚡ MW TOTALES LIBERADOS       : {resultado['mw_totales_liberados']:.1f} MW")

    # Mostrar alertas críticas
    alertas = [r for r in resultado["resultados"]
               if r.get("datos") and r["datos"].get("capacidad_mw_liberada")]
    if alertas:
        print(f"\n  DETALLE ALERTAS:")
        for a in alertas:
            d = a["datos"]
            print(f"    [{a['boletin']}] {d.get('nombre_proyecto','?')} — "
                  f"{d.get('potencia_mw','?')} MW — "
                  f"SET: {d.get('subestacion_conexion','?')} — "
                  f"Estado: {d.get('estado_permiso','?')}")

    print(f"\n  📁 Output: output/energy_extraido_{fecha}.json")
    print(f"{'═'*62}\n")
    return resultado


def estimar(n_items):
    inp = n_items * 2500
    out = n_items * 600
    c_haiku  = (inp/1e6)*0.80  + (out/1e6)*4.0
    c_sonnet = (inp/1e6)*3.0   + (out/1e6)*15.0
    print(f"\n  Estimación para {n_items} items:")
    print(f"  Haiku  (prueba)   ~${c_haiku:.4f}  USD  (~{c_haiku*0.93:.4f} EUR)")
    print(f"  Sonnet (producción) ~${c_sonnet:.4f} USD  (~{c_sonnet*0.93:.4f} EUR)\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fecha",      type=str)
    p.add_argument("--ayer",       action="store_true")
    p.add_argument("--hoy",        action="store_true")
    p.add_argument("--boletines",  nargs="+", choices=BOLETINES_DISPONIBLES)
    p.add_argument("--max-items",  type=int)
    p.add_argument("--api-key",    type=str)
    p.add_argument("--modelo",     choices=["haiku","sonnet"], default="haiku")
    p.add_argument("--solo-scraping", "--dry-run", action="store_true")
    p.add_argument("--estimar",    action="store_true")
    p.add_argument("--items",      type=int, default=20)
    args = p.parse_args()

    if args.estimar:
        estimar(args.items)
        sys.exit(0)

    fecha = None
    if args.fecha: fecha = args.fecha
    elif args.hoy: fecha = datetime.now().strftime("%Y%m%d")

    run(fecha=fecha, boletines=args.boletines, max_items=args.max_items,
        api_key=args.api_key, modelo=args.modelo, solo_scraping=args.solo_scraping)
