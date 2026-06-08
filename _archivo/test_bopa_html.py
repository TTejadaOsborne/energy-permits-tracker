"""
test_bopa_html.py — Ver estructura del HTML del BOPA por fecha.
python test_bopa_html.py > bopa_html2.txt 2>&1
type bopa_html2.txt
"""
import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

# El diagnóstico confirmó: disposiciones?fecha=DD/MM/YYYY devuelve 200
url = "https://miprincipado.asturias.es/bopa/disposiciones?fecha=24/04/2026"
r = s.get(url, timeout=15)
print(f"Status: {r.status_code} | {len(r.content)}B")

soup = BeautifulSoup(r.text, "lxml")

# Buscar todos los divs/clases relevantes
print("\n=== Clases CSS con contenido relevante ===")
for el in soup.find_all(class_=True):
    cls = " ".join(el.get("class",[]))
    txt = el.get_text(strip=True)[:80]
    if any(w in cls for w in ["disposicion","bopa","sumario","item","result","boletin","entrada","portlet","journal","article"]):
        print(f"  <{el.name} class='{cls}'> {txt}")

print("\n=== IDs relevantes ===")
for el in soup.find_all(id=True):
    eid = el.get("id","")
    txt = el.get_text(strip=True)[:60]
    if any(w in eid.lower() for w in ["bopa","disposicion","sumario","content","main","boletin"]):
        print(f"  <{el.name} id='{eid}'> {txt}")

print("\n=== Párrafos con texto de disposición ===")
for el in soup.find_all(["p","li","h3","h4","a","span"]):
    txt = el.get_text(strip=True)
    if len(txt) > 60 and any(w in txt for w in ["Resolución","Decreto","Orden","RESOLUCIÓN","autorización","ANUNCIO"]):
        cls = " ".join(el.get("class",[]) if el.get("class") else [])
        href = el.get("href","") if el.name == "a" else ""
        print(f"  <{el.name} class='{cls}'> {txt[:120]}")
        if href:
            print(f"    href: {href}")

print("\n=== Texto completo (3000 chars desde main/article) ===")
for sel in ["main", "article", "#content", ".portlet-body", "#portlet_bopaportlet"]:
    el = soup.select_one(sel)
    if el:
        print(f"Selector '{sel}':")
        print(el.get_text()[:3000])
        break

# También buscar el BORM con requests directo
print("\n=== BORM: buscar API sin JavaScript ===")
borm_urls = [
    "https://www.borm.es/borm/rest/sumario?fecha=20260424",
    "https://www.borm.es/borm/rest/sumario/20260424",
    "https://www.borm.es/borm/api/sumario?fecha=2026-04-24",
    "https://www.borm.es/services/borm/sumario/20260424",
    "https://www.borm.es/borm/documento.json?fecha=28/04/2026",
]
for url in borm_urls:
    try:
        r2 = s.get(url, timeout=8)
        print(f"  {r2.status_code} | {len(r2.content):6}B | {url[-60:]}")
        if r2.status_code == 200 and len(r2.content) > 100:
            print(f"  CONTENT: {r2.text[:200]}")
    except Exception as e:
        print(f"  ERR | {url[-60:]}: {e}")

print("\nCOMPLETADO")
