"""
test_bopa_borm.py — Inspecciona BOPA y BORM para encontrar sus APIs.
python test_bopa_borm.py > bopa_borm_diag.txt 2>&1
type bopa_borm_diag.txt
"""
import requests, json
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

# ── BOPA: buscar API con fecha ────────────────────────────────────────────────
print("="*60)
print("BOPA: probar URLs de búsqueda por fecha")
print("="*60)

bopa_urls = [
    "https://miprincipado.asturias.es/bopa/disposiciones?fecha=24/04/2026",
    "https://miprincipado.asturias.es/bopa/disposiciones?fecha=2026-04-24",
    "https://miprincipado.asturias.es/bopa/-/disposiciones/fecha/20260424",
    "https://miprincipado.asturias.es/o/bopa-ws/api/disposiciones?fecha=2026-04-24",
    "https://miprincipado.asturias.es/bopa/ultimos-boletines",
]

for url in bopa_urls:
    try:
        r = s.get(url, timeout=10)
        ct = r.headers.get("Content-Type","")[:40]
        print(f"  {r.status_code} | {len(r.content):6}B | {ct} | {url[-60:]}")
        if r.status_code == 200 and "json" in ct:
            print(f"  JSON: {r.text[:300]}")
    except Exception as e:
        print(f"  ERR | {url[-60:]}: {e}")

# ── BOPA: Playwright para capturar API ───────────────────────────────────────
print()
print("="*60)
print("BOPA: Playwright capturar peticiones de red")
print("="*60)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    page = ctx.new_page()

    apis = []
    def on_resp(resp):
        ct = resp.headers.get("content-type","")
        if ("json" in ct or "xml" in ct) and resp.status == 200:
            try:
                body = resp.text()
                if len(body) > 100:
                    apis.append({"url": resp.url, "body": body[:500]})
            except Exception:
                pass

    page.on("response", on_resp)

    # Navegar al último boletín
    page.goto("https://miprincipado.asturias.es/bopa/ultimos-boletines", timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(3000)

    print(f"URL final: {page.url}")
    print(f"APIs JSON capturadas: {len(apis)}")
    for api in apis[:10]:
        print(f"  {api['url'][-80:]}")
        print(f"  {api['body'][:200]}")
        print()

    # Ver texto de la página
    txt = page.inner_text("body")
    print(f"Texto página (2000 chars):\n{txt[:2000]}")

    browser.close()

# ── BORM: Playwright ──────────────────────────────────────────────────────────
print()
print("="*60)
print("BORM: Playwright capturar API Angular")
print("="*60)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    page = ctx.new_page()

    borm_apis = []
    def on_resp_borm(resp):
        url = resp.url
        ct = resp.headers.get("content-type","")
        if resp.status == 200 and ("json" in ct or "xml" in ct) and len(url) > 20:
            try:
                body = resp.text()
                if len(body) > 50:
                    borm_apis.append({"url": url, "body": body[:400]})
            except Exception:
                pass

    page.on("response", on_resp_borm)

    try:
        page.goto("https://www.borm.es/#/home", timeout=25000)
        page.wait_for_load_state("networkidle", timeout=20000)
        page.wait_for_timeout(5000)

        print(f"URL final: {page.url}")
        print(f"APIs capturadas: {len(borm_apis)}")
        for api in borm_apis[:10]:
            print(f"  {api['url'][-90:]}")
            print(f"  {api['body'][:300]}")
            print()

        txt = page.inner_text("body")
        print(f"Texto BORM (1500 chars):\n{txt[:1500]}")
    except Exception as e:
        print(f"Error BORM: {e}")

    browser.close()

print("\nCOMPLETADO")
