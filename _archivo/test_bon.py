"""
test_bon.py -- Diagnostico BON historico (v2)
Uso: python test_bon.py            # prueba 20260507
     python test_bon.py --fecha YYYYMMDD
"""
import sys, argparse, logging, re, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

import requests
from bs4 import BeautifulSoup
from scrapers.multi_scraper import BONScraper


def dump_index(s, url, fecha):
    dt = datetime.strptime(fecha, "%Y%m%d")
    print("\n  Fetching: " + url)
    try:
        r = s.get(url, timeout=25)
        html = r.content.decode(r.encoding or "utf-8", errors="replace")
        print("  Status: {}  |  Length: {} chars".format(r.status_code, len(html)))

        checks = [
            ("ISO ({}-{:02d}-{:02d})".format(dt.year, dt.month, dt.day),
             "{}-{:02d}-{:02d}".format(dt.year, dt.month, dt.day)),
            ("Slash ({:02d}/{:02d}/{})".format(dt.day, dt.month, dt.year),
             "{:02d}/{:02d}/{}".format(dt.day, dt.month, dt.year)),
            ("Texto ({} de mayo)".format(dt.day),
             "{} de mayo".format(dt.day)),
            ("Num edicion '88'", "88"),
            ("Solo dia '{}'".format(dt.day), str(dt.day)),
        ]
        for label, token in checks:
            found = token in html
            mark = "OK" if found else "--"
            print("  [{}] {:<30s} '{}'".format(mark, label, token))

        soup = BeautifulSoup(html, "lxml")

        edicion_links = soup.find_all("a", href=re.compile(r"/es/boletin/-/boletin/\d{4}/\d+"))
        print("\n  EDICION_PAT links: {}".format(len(edicion_links)))
        for a in edicion_links[:15]:
            parent = a.find_parent(["li","tr","div","article"])
            ctx = parent.get_text(" ", strip=True)[:100] if parent else a.get_text()
            print("    {}  ctx: {}".format(a["href"], ctx[:80]))

        anuncio_links = soup.find_all("a", href=re.compile(r"/es/anuncio/-/texto/\d+/\d+/\d+"))
        print("\n  ANUNCIO_PAT links: {}".format(len(anuncio_links)))
        for a in anuncio_links[:5]:
            print("    " + a["href"])

        txt = soup.get_text(" ", strip=True)
        print("\n  Texto visible (600 chars):")
        print("  " + txt[:600])

    except Exception as e:
        print("  ERROR: " + str(e))


def test_bon(fecha):
    print("\n" + "="*65)
    print("  TEST BON -- " + fecha)
    print("="*65)

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "es-ES,es;q=0.9",
    })
    bon = BONScraper(s)
    dt  = datetime.strptime(fecha, "%Y%m%d")

    # 1. /es/ultimo
    print("\n[1] /es/ultimo -- edicion actual")
    try:
        r = s.get(bon.URL_ULTIMO, timeout=25)
        html = r.content.decode(r.encoding or "utf-8", errors="replace")
        fecha_actual = bon._extraer_fecha(html)
        anuncios = re.findall(r"/es/anuncio/-/texto/(\d+)/(\d+)/(\d+)", html)
        ediciones = set(a[1] for a in anuncios)
        print("  Fecha detectada: {}  |  Ediciones: {}  |  Anuncios: {}".format(
            fecha_actual, ediciones, len(anuncios)))
    except Exception as e:
        print("  ERROR: " + str(e))

    # 2. Volcar indice
    print("\n[2] Volcado del indice de boletines")
    urls_a_probar = [
        bon.URL_INDICE,
        bon.URL_INDICE + "?mes={}&anio={}".format(dt.month, dt.year),
        bon.URL_INDICE + "?anio={}&mes={:02d}".format(dt.year, dt.month),
        bon.URL_INDICE + "?dia={}&mes={}&anio={}".format(dt.day, dt.month, dt.year),
        "https://bon.navarra.es/es/boletin/-/boletin/{}".format(dt.year),
    ]
    for u in urls_a_probar:
        dump_index(s, u, fecha)
        time.sleep(0.4)

    # 3. Acceso directo edicion 88 (solo para 20260507)
    if fecha == "20260507":
        print("\n[3] Acceso directo edicion 88")
        url_ed = "https://bon.navarra.es/es/boletin/-/boletin/2026/88"
        try:
            r2 = s.get(url_ed, timeout=25)
            html2 = r2.content.decode(r2.encoding or "utf-8", errors="replace")
            soup2 = BeautifulSoup(html2, "lxml")
            ans = soup2.find_all("a", href=re.compile(r"/es/anuncio/-/texto/"))
            print("  Status: {}  |  ANUNCIO_PAT: {}".format(r2.status_code, len(ans)))
            print("  Texto (200): " + soup2.get_text(" ", strip=True)[:200])
        except Exception as e:
            print("  ERROR: " + str(e))

        print("\n[4] Enumeracion items 0-9 de edicion 88")
        for i in range(0, 10):
            url = "https://bon.navarra.es/es/anuncio/-/texto/2026/88/{}".format(i)
            try:
                r3 = s.get(url, timeout=15)
                html3 = r3.content.decode(r3.encoding or "utf-8", errors="replace")
                soup3 = BeautifulSoup(html3, "lxml")
                txt = soup3.get_text(" ", strip=True)[:200].replace("\n", " ")
                print("  [{:3d}] HTTP {}  len={:6d}  {}".format(
                    i, r3.status_code, len(html3), txt[:150]))
            except Exception as e:
                print("  [{:3d}] ERROR: {}".format(i, e))
            time.sleep(0.2)

    # 5. get_items completo
    print("\n[5] get_items({}) resultado final".format(fecha))
    t0 = time.time()
    items = bon.get_items(fecha)
    print("  --> {} items en {:.1f}s".format(len(items), time.time() - t0))
    for it in items:
        print("  OK  {}  |  {}".format(it["id"], it["titulo"][:100]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fecha", type=str)
    args = p.parse_args()
    fechas = [args.fecha] if args.fecha else ["20260507"]
    for f in fechas:
        test_bon(f)
