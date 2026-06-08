"""
Validación rápida de todos los scrapers.
Uso: python validar_boletines.py [--fecha YYYYMMDD]
"""
import sys, logging, time, argparse, requests
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scrapers.multi_scraper import (
    BOEScraper, BOCMScraper, BOCyLScraper, DOCMScraper, BOJAScraper,
    DOGVScraper, DOGCScraper, GenericHTMLScraper,
    BOAScraper, BOPVScraper, DOEScraper, BONScraper, BOLRScraper,
)

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')

p = argparse.ArgumentParser()
p.add_argument("--fecha", default=None)
args = p.parse_args()

fecha = args.fecha or (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
dt = datetime.strptime(fecha, "%Y%m%d")
dia_semana = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"][dt.weekday()]

print(f"\n{'═'*65}")
print(f"  VALIDACIÓN BOLETINES — {fecha} ({dia_semana} {dt.day}/{dt.month}/{dt.year})")
print(f"{'═'*65}\n")
if dt.weekday() >= 5:
    print("  ⚠  Fin de semana — la mayoría de boletines no publican\n")

SCRAPERS = {
    "BOE":   lambda s: BOEScraper(s),
    "BOCM":  lambda s: BOCMScraper(s),
    "BOCyL": lambda s: BOCyLScraper(s),
    "DOCM":  lambda s: DOCMScraper(s),
    "BOJA":  lambda s: BOJAScraper(s),
    "DOGV":  lambda s: DOGVScraper(s),
    "DOGC":  lambda s: DOGCScraper(s),
    "DOG":   lambda s: GenericHTMLScraper(s, "DOG"),
    "BOPA":  lambda s: GenericHTMLScraper(s, "BOPA"),
    "BOC":   lambda s: GenericHTMLScraper(s, "BOC"),
    "BORM":  lambda s: GenericHTMLScraper(s, "BORM"),
    "BOA":   lambda s: BOAScraper(s),
    "BOPV":  lambda s: BOPVScraper(s),
    "DOE":   lambda s: DOEScraper(s),
    "BON":   lambda s: BONScraper(s),
    "BOLR":  lambda s: BOLRScraper(s),
}

total_items = 0
errores = []
sin_items = []

for nombre, factory in SCRAPERS.items():
    s = requests.Session()
    scraper = factory(s)
    t0 = time.time()
    try:
        items = scraper.get_items(fecha)
        elapsed = time.time() - t0
        n = len(items)
        total_items += n
        if n == 0:
            sin_items.append(nombre)
            print(f"  ⚠   {nombre:<6}  0 items   ({elapsed:.1f}s)")
        else:
            print(f"  ✅  {nombre:<6}  {n} items   ({elapsed:.1f}s)")
            for it in items[:2]:
                titulo = it.get('titulo','')[:68]
                print(f"         └─ {titulo}")
    except Exception as e:
        elapsed = time.time() - t0
        errores.append((nombre, str(e)))
        print(f"  ❌  {nombre:<6}  ERROR ({elapsed:.1f}s): {str(e)[:60]}")
    time.sleep(0.3)

print(f"\n{'─'*65}")
print(f"  Total items relevantes : {total_items}")
print(f"  Con items   : {[n for n in SCRAPERS if n not in sin_items and n not in [e[0] for e in errores]]}")
print(f"  Sin items   : {sin_items}")
print(f"  Errores     : {[e[0] for e in errores]}")
if errores:
    print("\n  Detalle errores:")
    for nom, err in errores:
        print(f"    {nom}: {err}")
print(f"{'═'*65}\n")
