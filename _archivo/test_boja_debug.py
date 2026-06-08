"""
test_boja_debug.py — Debug paso a paso del BOJAScraper
python test_boja_debug.py
"""
import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.juntadeandalucia.es/eboja.html",
    "Accept": "application/json, text/html, */*",
})

FECHA = "20260424"
BASE  = "https://www.juntadeandalucia.es"

# Paso 1: API calendario
print("=== PASO 1: API calendario ===")
fecha_api = "24-04-2026"
url_cal = f"{BASE}/ssdigitales/datasets/contentapi/boja/calendario?fechaDesde={fecha_api}&fechaHasta={fecha_api}"
r = s.get(url_cal, timeout=15)
print(f"Status: {r.status_code} | {len(r.content)}B")
data = r.json()
print(f"JSON: {data}")

resultado_data = data.get("resultado", [])
bojas_del_dia  = resultado_data[0].get("boja", []) if resultado_data else []
print(f"Bojas del día: {bojas_del_dia}")

# Paso 2: Descargar el índice de cada boletín
for boletin_meta in bojas_del_dia:
    enlace = boletin_meta.get("enlace","")
    if not enlace:
        continue
    url_index = BASE + enlace
    print(f"\n=== PASO 2: Índice boletín ===")
    print(f"URL: {url_index}")
    r2 = s.get(url_index, timeout=20)
    print(f"Status: {r2.status_code} | {len(r2.content)}B")

    soup = BeautifulSoup(r2.text, "lxml")

    # Buscar el contenedor
    columna = soup.find("div", id="columna")
    print(f"div#columna encontrado: {columna is not None}")

    if columna:
        # Contar items
        items_div = columna.find_all("div", class_=lambda c: c and "item" in c and "punteado_izquierda" in c)
        print(f"Divs con class 'item punteado_izquierda': {len(items_div)}")

        # Mostrar los primeros 5
        for i, item in enumerate(items_div[:5]):
            txt = item.get_text(" ", strip=True)[:120]
            a_html = item.find("a", class_="item_html")
            a_pdf  = item.find("a", class_="item_pdf_grupo")
            print(f"\n  Item {i+1}:")
            print(f"    Texto: {txt}")
            print(f"    a.item_html: {a_html.get('href') if a_html else 'NO'}")
            print(f"    a.item_pdf_grupo: {a_pdf.get('href') if a_pdf else 'NO'}")

        # Ver las cabeceras de sección
        print("\n  Cabeceras encontradas:")
        for h in columna.find_all(["h2","h3","h4","h5"]):
            print(f"    <{h.name}> {h.get_text(strip=True)[:80]}")

        # Ver texto completo del div#columna para entender estructura
        print(f"\n  Texto div#columna (primeros 2000 chars):")
        print(columna.get_text()[:2000])

print("\nDEBUG COMPLETADO")
