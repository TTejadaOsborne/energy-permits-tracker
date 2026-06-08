"""
test_boja_api.py — Verifica BOJA con enlace correcto y DOGC SSL fix.
python test_boja_api.py > boja_api_diag.txt 2>&1
"""
import requests, json, ssl, urllib3
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
urllib3.disable_warnings()

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.juntadeandalucia.es/eboja.html",
    "Accept": "application/json, text/html, */*",
})

# ── BOJA: obtener índice real del boletín ─────────────────────────────────────
print("=== BOJA: índice real del boletín ===")
r = s.get("https://www.juntadeandalucia.es/ssdigitales/datasets/contentapi/boja/calendario?fechaDesde=24-04-2026&fechaHasta=24-04-2026")
data = r.json()
boja_enlace = data["resultado"][0]["boja"][0]["enlace"]
print(f"Enlace boletín: {boja_enlace}")

url_index = "https://www.juntadeandalucia.es" + boja_enlace
print(f"URL índice: {url_index}")

r2 = s.get(url_index)
print(f"Status: {r2.status_code} | {len(r2.content)}B")
if r2.status_code == 200:
    soup = BeautifulSoup(r2.text, "lxml")
    print("\nTexto del índice (3000 chars):")
    print(soup.get_text()[:3000])

# ── DOGC: SSL legacy fix ──────────────────────────────────────────────────────
print("\n=== DOGC SSL legacy fix ===")

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

    for fecha in ["20260428","20260427","20260424","20260423","20260422","20260421","20260420"]:
        try:
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
            print(f"  {fecha}: {r.status_code} | {len(r.content)}B | {r.text[:150]}")
            if r.status_code == 200 and len(r.content) > 100:
                print("  *** EXITO - DOGC con datos ***")
                with open(f"dogc_{fecha}.json", "w", encoding="utf-8") as f:
                    json.dump(r.json(), f, ensure_ascii=False, indent=2)
                print(f"  Guardado dogc_{fecha}.json")
                break
        except Exception as e:
            print(f"  {fecha}: ERROR {str(e)[:100]}")

except Exception as e:
    print(f"SSL setup error: {e}")

print("\nCOMPLETADO")
