"""
test_portales.py — Inspecciona las APIs reales de BOJA, DOGC, BOPA, BORM
Guarda capturas de pantalla y peticiones de red de cada portal.
Ejecutar: python test_portales.py
Resultado en: portales_diag.txt
"""
import sys, time, json
from datetime import datetime
from playwright.sync_api import sync_playwright

FECHA = "20260429"  # Martes 29/04/2026 — día laborable con publicaciones
DT    = datetime.strptime(FECHA, "%Y%m%d")

def test(nombre, url, acciones=None, wait_ms=5000):
    print(f"\n{'='*60}")
    print(f"[{nombre}] {url}")
    print('='*60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox","--lang=es-ES"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
            locale="es-ES", timezone_id="Europe/Madrid"
        )
        page = ctx.new_page()

        # Capturar TODAS las peticiones de red
        peticiones = []
        def on_req(req):
            peticiones.append({"m": req.method, "u": req.url})
        def on_resp(resp):
            ct = resp.headers.get("content-type","")
            if any(x in ct for x in ["json","xml"]) and len(resp.url) > 10:
                try:
                    body = resp.text()[:500]
                    print(f"  📦 RESPUESTA [{resp.status}] {resp.url[-80:]}")
                    print(f"     {body[:200]}")
                except Exception:
                    pass

        page.on("request", on_req)
        page.on("response", on_resp)

        try:
            page.goto(url, timeout=25000)
            page.wait_for_load_state("networkidle", timeout=15000)

            # Ejecutar acciones si las hay
            if acciones:
                acciones(page)
                page.wait_for_load_state("networkidle", timeout=10000)
                time.sleep(1)

            page.wait_for_timeout(wait_ms)

            print(f"\n  URL final: {page.url}")
            print(f"\n  Peticiones de red ({len(peticiones)}):")
            for p2 in peticiones:
                u = p2["u"]
                if any(x in u for x in ["api","json","xml","sumari","bopa","borm","boja","dogc","ajax","search","fetch","query","data","bolet"]):
                    print(f"    {p2['m']:4} {u[:120]}")

            print(f"\n  Texto página (primeros 1500 chars):")
            try:
                txt = page.inner_text("body")
                print(txt[:1500])
            except Exception as e:
                print(f"  ERROR inner_text: {e}")

        except Exception as e:
            print(f"  ERROR: {e}")
        finally:
            browser.close()

# ── BOJA: Sede electrónica ────────────────────────────────────────────────────
def boja_acciones(page):
    # Intentar acceder al boletín del día desde la sede electrónica
    try:
        # Buscar link al último boletín o al calendario
        links = page.evaluate("""
            () => Array.from(document.querySelectorAll('a'))
                  .filter(a => a.href && (a.href.includes('boletin') || a.href.includes('sumario') || a.href.includes('calendar')))
                  .slice(0,5).map(a => ({t: a.textContent.trim().substring(0,50), u: a.href}))
        """)
        print("  Links de interés BOJA:", links)
    except Exception as e:
        print(f"  BOJA acciones: {e}")

test("BOJA sede",
     "https://www.juntadeandalucia.es/eboja.html",
     acciones=boja_acciones, wait_ms=3000)

# ── BOJA: eboja con fecha ─────────────────────────────────────────────────────
test("BOJA eboja/fecha",
     f"https://www.juntadeandalucia.es/eboja/{DT.year}/{DT.month:02d}/{DT.day:02d}/",
     wait_ms=3000)

# ── DOGC: portal con fecha ────────────────────────────────────────────────────
test("DOGC documento",
     f"https://dogc.gencat.cat/ca/document-del-dogc/?documentId={FECHA}",
     wait_ms=5000)

# ── BOPA: miprincipado ────────────────────────────────────────────────────────
def bopa_acciones(page):
    try:
        links = page.evaluate("""
            () => Array.from(document.querySelectorAll('a'))
                  .filter(a => a.href && (a.href.includes('bopa') || a.href.includes('boletin')))
                  .slice(0,8).map(a => ({t: a.textContent.trim().substring(0,60), u: a.href}))
        """)
        print("  Links BOPA:", links)
    except Exception as e:
        print(f"  BOPA acciones: {e}")

test("BOPA disposiciones",
     "https://miprincipado.asturias.es/bopa/disposiciones",
     acciones=bopa_acciones, wait_ms=4000)

# ── BORM: sede electrónica ────────────────────────────────────────────────────
test("BORM home",
     "https://www.borm.es/#/home",
     wait_ms=5000)

print("\n\nDIAGNÓSTICO COMPLETADO")
