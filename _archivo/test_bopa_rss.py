"""
test_bopa_rss.py — Buscar RSS/Atom del BOPA y otras alternativas simples.
python test_bopa_rss.py > bopa_rss_diag.txt 2>&1
"""
import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

BASE = "https://miprincipado.asturias.es"

print("=== Test RSS y alternativas ===")
urls = [
    # RSS feeds típicos de Liferay
    f"{BASE}/bopa/rss",
    f"{BASE}/bopa/disposiciones/rss",
    f"{BASE}/bopa/-/rss",
    f"{BASE}/rss/bopa",
    # Liferay REST API
    f"{BASE}/o/headless-delivery/v1.0/sites/bopa/structured-contents",
    f"{BASE}/o/bopa-ws/v1.0/disposiciones/date/2026-04-24",
    f"{BASE}/o/bopa-ws/v1.0/disposiciones?fecha=2026-04-24",
    # URL alternativa con parámetros Liferay
    f"{BASE}/bopa/disposiciones?p_r_p_dispositionDate=24%2F04%2F2026",
    f"{BASE}/bopa/disposiciones?p_r_p_dispositionDate=2026-04-24",
    # Endpoint de datos
    f"{BASE}/bopa/ultimos-boletines?p_r_p_summaryLastBopa=true",
]

for url in urls:
    try:
        r = s.get(url, timeout=10, allow_redirects=True)
        ct = r.headers.get("Content-Type","")[:50]
        has = any(w in r.text for w in ["Resolución","Decreto","Orden","bopa","BOPA","disposicion"])
        print(f"  {r.status_code} | {len(r.content):7}B | {ct:35} | {'CONTENIDO' if has else '        '} | {url[-70:]}")
        if r.status_code == 200 and ("xml" in ct or "rss" in ct.lower() or "atom" in ct.lower()):
            print(f"  XML/RSS ENCONTRADO: {r.text[:300]}")
        elif r.status_code == 200 and has and len(r.content) < 50000:
            # Mostrar texto relevante
            soup = BeautifulSoup(r.text, "lxml")
            txt = soup.get_text()
            for line in txt.split("\n"):
                if any(w in line for w in ["Resolución","Decreto","Orden"]) and len(line.strip()) > 20:
                    print(f"    {line.strip()[:100]}")
    except Exception as e:
        print(f"  ERR | {url[-70:]}: {str(e)[:50]}")

# Ver HTML del último boletín directamente
print("\n=== HTML de ultimos-boletines?summaryLastBopa=true ===")
r = s.get(f"{BASE}/bopa/ultimos-boletines?p_r_p_summaryLastBopa=true", timeout=15)
print(f"Status: {r.status_code} | {len(r.content)}B")
if r.status_code == 200:
    soup = BeautifulSoup(r.text, "lxml")
    # Buscar fechas y links de boletines
    for a in soup.find_all("a", href=True):
        txt = a.get_text(strip=True)
        href = a.get("href","")
        if any(w in txt.lower() for w in ["bopa","boletín","resolución","decreto","número","nº"]):
            print(f"  [{txt[:80]}] {href[:80]}")
    print(soup.get_text()[:2000])

print("\nCOMPLETADO")
