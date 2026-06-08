"""
test_boja_seccion2.py — Ver HTML real de la sección s54 del BOJA.
python test_boja_seccion2.py > boja_sec2.txt 2>&1
type boja_sec2.txt
"""
import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.juntadeandalucia.es/eboja/2026/78/index.html",
    "Accept": "text/html,*/*",
})
BASE = "https://www.juntadeandalucia.es"

# Probar la URL de la sección "Otras disposiciones"
url = f"{BASE}/boja/2026/78/s54"
print(f"=== URL: {url} ===")
r = s.get(url, timeout=15)
print(f"Status: {r.status_code} | {len(r.content)}B")

if r.status_code == 200:
    soup = BeautifulSoup(r.text, "lxml")
    columna = soup.find("div", id="columna") or soup

    print(f"\n-- Todas las clases de divs en columna --")
    for div in columna.find_all("div"):
        cls = div.get("class", [])
        if cls:
            txt = div.get_text(strip=True)[:50]
            print(f"  class={cls} | {txt}")

    print(f"\n-- Texto completo div#columna (4000 chars) --")
    print(columna.get_text()[:4000])

    print(f"\n-- Todos los links --")
    for a in columna.find_all("a", href=True):
        txt = a.get_text(strip=True)[:60]
        if txt:
            print(f"  [{txt}] {a['href']}")

# También probar s51 (Disposiciones generales)
print(f"\n=== URL: {BASE}/boja/2026/78/s51 ===")
r2 = s.get(f"{BASE}/boja/2026/78/s51", timeout=15)
print(f"Status: {r2.status_code} | {len(r2.content)}B")
if r2.status_code == 200:
    soup2 = BeautifulSoup(r2.text, "lxml")
    col2 = soup2.find("div", id="columna") or soup2
    print(col2.get_text()[:2000])

print("\nCOMPLETADO")
