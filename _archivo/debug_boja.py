"""Debug paso a paso del scraper BOJA — maneja JSON y XML."""
import sys, logging, re, requests
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, str(Path(__file__).parent))
from scrapers.multi_scraper import es_relevante, BOJAScraper

fecha = sys.argv[1] if len(sys.argv) > 1 else "20260518"
dt = datetime.strptime(fecha, "%Y%m%d")
fecha_api = f"{dt.day:02d}-{dt.month:02d}-{dt.year}"

BASE = "https://www.juntadeandalucia.es"
s = requests.Session()
s.headers.update({"Referer": f"{BASE}/eboja.html", "Accept": "application/json, text/html, */*"})

# ── Paso 1: API calendario ─────────────────────────────────────────────────────
api_url = f"{BASE}/ssdigitales/datasets/contentapi/boja/calendario?fechaDesde={fecha_api}&fechaHasta={fecha_api}"
print(f"\n[1] API: {api_url}")
r = s.get(api_url, timeout=15)
print(f"    Status: {r.status_code}  Bytes: {len(r.content)}")
print(f"    Body: {r.text[:500]}\n")

# ── Paso 2: parsear respuesta ──────────────────────────────────────────────────
boletines = []
try:
    data = r.json()
    resultado_raw = data.get("resultado", [])
    for b in resultado_raw[0].get("boja", []) if resultado_raw else []:
        enlace = b.get("enlace","")
        bnum   = str(b.get("bojaNumber","")) or None
        if enlace:
            boletines.append({"enlace": enlace, "boja_num": bnum})
    print(f"[2] Formato JSON — boletines: {boletines}")
except Exception:
    xml_soup = BeautifulSoup(r.text, "lxml-xml")
    for res in xml_soup.find_all("resultado"):
        et = res.find("enlace"); bt = res.find("bojaNumber")
        if et:
            boletines.append({"enlace": et.get_text(strip=True), "boja_num": bt.get_text(strip=True) if bt else None})
    print(f"[2] Formato XML — boletines: {boletines}")

if not boletines:
    print("    → Sin boletines, saliendo"); sys.exit()

# ── Paso 3: índice + secciones para cada boletín ──────────────────────────────
for bm in boletines:
    enlace_index = bm["enlace"]
    boja_num_meta = bm["boja_num"]
    url_index = BASE + enlace_index
    print(f"\n[3] Índice: {url_index}")
    r2 = s.get(url_index, timeout=20)
    print(f"    Status: {r2.status_code}  Bytes: {len(r2.content)}")

    soup2 = BeautifulSoup(r2.text, "lxml")
    columna = soup2.find("div", id="columna") or soup2

    secciones = [a.get("href") for a in columna.find_all("a", href=True)
                 if re.match(r'^s\d+$', a.get("href",""))]
    print(f"    Secciones tipo 's\\d+': {secciones}")

    if not secciones:
        print("    ⚠ Sin secciones. Primeros 50 hrefs del índice:")
        hrefs = list({a.get("href","") for a in columna.find_all("a", href=True)})[:50]
        for h in sorted(hrefs):
            print(f"      {h}")
        print(f"\n    HTML índice (primeros 1500 chars):\n{r2.text[:1500]}")
        continue

    # ── Paso 4: primera sección ────────────────────────────────────────────────
    m_old = re.search(r'/eboja/(\d{4})/(\d+)/index\.html', enlace_index)
    if m_old:
        boja_num = m_old.group(2)
        base_sec = f"{BASE}/boja/{m_old.group(1)}/{boja_num}/"
    else:
        boja_num = boja_num_meta or "?"
        base_sec = f"{BASE}/boja/{dt.year}/{boja_num}/"

    print(f"    base_sec: {base_sec}")

    for sec in secciones[:3]:  # máximo 3 secciones para el debug
        url_sec = base_sec + sec
        print(f"\n[4] Sección {sec}: {url_sec}")
        r3 = s.get(url_sec, timeout=20)
        print(f"    Status: {r3.status_code}  Bytes: {len(r3.content)}")
        soup3 = BeautifulSoup(r3.text, "lxml")
        divs = soup3.find_all("div", class_=lambda c: c and "item" in c and "punteado_izquierda" in c)
        print(f"    Divs item.punteado_izquierda: {len(divs)}")
        for div in divs[:8]:
            p = div.find("p")
            titulo = p.get_text(" ", strip=True)[:100] if p else "?"
            rel = es_relevante(titulo)
            print(f"    {'✅' if rel else '  '} {titulo}")
        if not divs:
            print(f"    HTML sección (primeros 1000 chars):\n{r3.text[:1000]}")

# ── Paso 5: scraper completo ───────────────────────────────────────────────────
print(f"\n[5] BOJAScraper.get_items({fecha}):")
scraper = BOJAScraper(requests.Session())
items = scraper.get_items(fecha)
print(f"    Items totales: {len(items)}")
for i in items:
    print(f"    - {i.get('titulo','')[:90]}")
