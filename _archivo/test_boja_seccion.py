"""
test_boja_seccion.py — Ver estructura de las sub-páginas del BOJA con las disposiciones reales.
python test_boja_seccion.py > boja_sec_diag.txt 2>&1
"""
import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.juntadeandalucia.es/eboja.html",
})
BASE = "https://www.juntadeandalucia.es"

# Los links del sumario son: /boja/2026/78/1, /boja/2026/78/2, etc.
# Descargar la sección 3 (Otras disposiciones) — más probable de tener energía
for sec_num in ["1","2","3","4","5"]:
    url = f"{BASE}/boja/2026/78/{sec_num}"
    r = s.get(url, timeout=15)
    print(f"\n=== Sección {sec_num}: {url} ===")
    print(f"Status: {r.status_code} | {len(r.content)}B")

    if r.status_code != 200:
        continue

    soup = BeautifulSoup(r.text, "lxml")
    columna = soup.find("div", id="columna") or soup

    # Clases con "item"
    items = columna.find_all("div", class_=lambda c: c and "item" in c)
    print(f"Divs con 'item' en clase: {len(items)}")
    for it in items[:3]:
        txt = it.get_text(" ", strip=True)[:100]
        print(f"  class={it.get('class')} | {txt}")

    # Todos los links del contenido
    links = columna.find_all("a", href=True)
    print(f"Links en columna: {len(links)}")
    for a in links[:10]:
        print(f"  [{a.get_text(strip=True)[:50]}] {a['href']}")

    # Texto completo de columna
    print(f"\nTexto columna (2000 chars):")
    print(columna.get_text()[:2000])
    break  # Solo sección 1 para no sobrecargar

print("\nCOMPLETADO")
