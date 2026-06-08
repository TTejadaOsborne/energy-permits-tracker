"""
test_boja_html.py — Ver HTML real del boletín BOJA y probar DOGC con fechas correctas.
python test_boja_html.py > boja_html_diag.txt 2>&1
"""
import requests, ssl, urllib3, json
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
urllib3.disable_warnings()

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.juntadeandalucia.es/eboja.html",
})

# ── BOJA: ver estructura HTML del índice ──────────────────────────────────────
print("=== BOJA: estructura HTML del índice ===")
r = s.get("https://www.juntadeandalucia.es/eboja/2026/78/index.html")
soup = BeautifulSoup(r.text, "lxml")

# Ver clases CSS de los elementos del sumario
print("\n-- Clases CSS disponibles (relevantes) --")
for el in soup.find_all(class_=True):
    classes = " ".join(el.get("class", []))
    if any(w in classes for w in ["sumario","disposicion","seccion","item","boja","lista","resultado","contenido","articulo"]):
        txt = el.get_text(strip=True)[:60]
        print(f"  <{el.name} class='{classes}'> {txt}")

print("\n-- IDs disponibles --")
for el in soup.find_all(id=True):
    txt = el.get_text(strip=True)[:60]
    print(f"  <{el.name} id='{el.get('id')}'> {txt}")

print("\n-- Links del sumario --")
links = soup.find_all("a", href=True)
for a in links:
    href = a.get("href","")
    txt = a.get_text(strip=True)
    if href and ("/eboja/" in href or "boja" in href.lower()) and len(txt) > 10:
        print(f"  [{txt[:80]}] {href}")

# Ver raw HTML de la sección de contenido (sin menús)
print("\n-- HTML después de <main> o #main-content (500 chars) --")
main = soup.find("main") or soup.find(id="main-content") or soup.find(id="contenido")
if main:
    print(main.get_text()[:2000])
else:
    # Buscar el primer div con contenido sustancial
    for div in soup.find_all("div"):
        txt = div.get_text(strip=True)
        if len(txt) > 500 and "Consejería" in txt:
            print(f"  DIV class={div.get('class',[])} (primeros 1000 chars):")
            print(txt[:1000])
            break

# ── DOGC: probar con fechas correctas (L/X/V) ────────────────────────────────
print("\n=== DOGC: fechas correctas (Lunes/Miércoles/Viernes) ===")

try:
    from urllib3.util.ssl_ import create_urllib3_context
    ctx = create_urllib3_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
    except Exception:
        pass
    try:
        ctx.set_ciphers("ALL:@SECLEVEL=0")
    except Exception:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")

    class LegacySSLAdapter(HTTPAdapter):
        def init_poolmanager(self, *a, **kw):
            kw["ssl_context"] = ctx
            return super().init_poolmanager(*a, **kw)

    ds = requests.Session()
    ds.mount("https://", LegacySSLAdapter())
    ds.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    # Fechas: L=20260420(L), X=20260422(X), V=20260424(V), L=20260427(L), X=20260429(X)
    # 20/04=lunes, 22/04=miércoles, 24/04=viernes, 27/04=lunes, 29/04=miércoles
    for fecha in ["20260420","20260422","20260424","20260415","20260416","20260417"]:
        r = ds.post(
            "https://portaldogc.gencat.cat/eadop-rest/api/dogc/documentDOGC",
            data={"documentId": fecha, "language": "ca"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json, */*",
                "Origin": "https://dogc.gencat.cat",
                "Referer": "https://dogc.gencat.cat/",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=15, verify=False
        )
        if r.status_code == 200 and len(r.content) > 100:
            print(f"  {fecha}: *** EXITO {r.status_code} | {len(r.content)}B ***")
            data = r.json()
            print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
            with open(f"dogc_{fecha}.json","w",encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            break
        else:
            print(f"  {fecha}: {r.status_code} | {r.text[:80]}")
except Exception as e:
    print(f"Error: {e}")

print("\nCOMPLETADO")
