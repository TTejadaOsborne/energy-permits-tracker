"""
test_boja_form.py — Inspecciona el formulario real del BOJA y prueba el DOGC SSL fix.
Ejecutar: python test_boja_form.py > boja_form_diag.txt 2>&1
"""
import requests, ssl, urllib3
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

urllib3.disable_warnings()

# ── 1. DOGC SSL fix test ──────────────────────────────────────────────────────
print("="*60)
print("DOGC SSL fix test")
print("="*60)

from requests.adapters import HTTPAdapter
try:
    from urllib3.util.ssl_ import create_urllib3_context
    ctx = create_urllib3_context()
    ctx.set_ciphers("DEFAULT")
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    class SSLAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            kwargs["ssl_context"] = ctx
            return super().init_poolmanager(*args, **kwargs)

    s = requests.Session()
    s.mount("https://portaldogc", SSLAdapter())
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })

    # Probar con fechas que tengan boletín (lunes/martes)
    for fecha in ["20260424", "20260423", "20260422", "20260421"]:
        r = s.post(
            "https://portaldogc.gencat.cat/eadop-rest/api/dogc/documentDOGC",
            data={"documentId": fecha, "language": "ca"},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Origin": "https://dogc.gencat.cat",
                "Referer": "https://dogc.gencat.cat/",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=15, verify=False
        )
        print(f"  {fecha}: {r.status_code} | {len(r.content)}B")
        if r.status_code == 200 and len(r.content) > 100:
            print(f"  RESPUESTA: {r.text[:500]}")
            break
        elif r.status_code == 200:
            print(f"  BODY: {r.text[:100]}")

except Exception as e:
    print(f"  ERROR: {e}")


# ── 2. BOJA: inspeccionar formulario con Playwright ───────────────────────────
print()
print("="*60)
print("BOJA formulario real")
print("="*60)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        locale="es-ES"
    )
    page = ctx.new_page()

    # Navegar al buscador BOJA digital (no el histórico)
    page.goto("https://www.juntadeandalucia.es/eboja.html", timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)

    print("URL final:", page.url)

    # Ver todos los inputs y botones
    elementos = page.evaluate("""
        () => {
            const inputs = Array.from(document.querySelectorAll('input, select, textarea, button'))
                .map(el => ({
                    tag: el.tagName,
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    value: el.value || '',
                    visible: el.offsetParent !== null,
                    text: el.textContent?.trim().substring(0,50) || ''
                }))
                .filter(el => el.visible);
            return inputs.slice(0, 20);
        }
    """)
    print("\nElementos de formulario visibles:")
    for el in elementos:
        print(f"  <{el['tag']}> type={el['type']} name={el['name']} id={el['id']} placeholder={el['placeholder'][:30]} text={el['text'][:30]}")

    # Ver links relevantes
    links = page.evaluate("""
        () => Array.from(document.querySelectorAll('a'))
            .filter(a => a.href && (
                a.href.includes('eboja') || a.href.includes('boja') ||
                a.href.includes('buscador') || a.href.includes('bolet')
            ))
            .slice(0, 15)
            .map(a => ({text: a.textContent.trim().substring(0,60), href: a.href}))
    """)
    print("\nLinks del BOJA:")
    for l in links:
        print(f"  [{l['text']}] {l['href'][:100]}")

    # Capturar las peticiones de red al cargar la página
    print("\nPeticiones API capturadas durante carga:")

    browser.close()


# ── 3. BOJA: probar el buscador digital directamente ─────────────────────────
print()
print("="*60)
print("BOJA: probar contentapi con varios formatos de fecha")
print("="*60)

s2 = requests.Session()
s2.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.juntadeandalucia.es/eboja.html",
    "Accept": "application/json, */*",
})

# Probar formatos de fecha para el calendario
fechas_formato = [
    "2026-04-24", "24-04-2026", "24/04/2026", "20260424",
    "2026/04/24", "04-24-2026",
]
for fmt in fechas_formato:
    url = f"https://www.juntadeandalucia.es/ssdigitales/datasets/contentapi/boja/calendario?fechaDesde={fmt}&fechaHasta={fmt}"
    try:
        r = s2.get(url, timeout=10)
        print(f"  {fmt}: {r.status_code} | {len(r.content)}B | {r.text[:100]}")
    except Exception as e:
        print(f"  {fmt}: ERROR {e}")

print("\nDIAGNOSTICO COMPLETADO")
