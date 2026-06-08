"""
test_boja_raw.py — Ver el HTML raw de s54 para encontrar dónde están los items.
python test_boja_raw.py > boja_raw.txt 2>&1
type boja_raw.txt
"""
import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.juntadeandalucia.es/eboja/2026/78/index.html",
})
BASE = "https://www.juntadeandalucia.es"

url = f"{BASE}/boja/2026/78/s54"
r = s.get(url, timeout=15)
print(f"Status: {r.status_code} | {len(r.content)}B")

soup = BeautifulSoup(r.text, "lxml")

# Ver TODOS los divs con sus clases
print("\n=== TODOS los divs con clase ===")
for div in soup.find_all("div", class_=True):
    cls = " ".join(div.get("class",[]))
    txt = div.get_text(strip=True)[:80]
    if txt and not any(x in cls for x in ["nav","menu","footer","header","block-field","blazy","clearfix text"]):
        print(f"  class='{cls}' | {txt}")

# Ver TODOS los IDs
print("\n=== TODOS los IDs ===")
for el in soup.find_all(id=True):
    txt = el.get_text(strip=True)[:80]
    if txt:
        print(f"  id='{el.get('id')}' tag={el.name} | {txt}")

# Buscar donde están las disposiciones (texto largo con "Resolución", "Orden", etc.)
print("\n=== Párrafos con texto de disposición ===")
for el in soup.find_all(["p","li","dt","span","h4","h5"]):
    txt = el.get_text(strip=True)
    if len(txt) > 60 and any(w in txt for w in ["Resolución","Orden","Decreto","RESOLUCIÓN","ORDEN","autorización"]):
        parent_cls = " ".join(el.parent.get("class",[]) if el.parent else [])
        print(f"  <{el.name}> parent_class='{parent_cls[:50]}' | {txt[:120]}")

# Guardar el HTML de la sección de contenido (sin header/footer)
print("\n=== HTML de la parte central (grid_11 o boja_sumario) ===")
for sel in [".grid_11", ".boja_sumario", ".contenidos_nivel3", "#cuerpo", "main", "article"]:
    el = soup.select_one(sel)
    if el:
        txt = el.get_text()[:2000]
        print(f"Selector '{sel}' encontrado:")
        print(txt)
        break

print("\nCOMPLETADO")
