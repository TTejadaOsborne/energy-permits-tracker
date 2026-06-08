"""
test_playwright.py — Diagnóstico de portales con Playwright
Ejecutar: python test_playwright.py
"""
from playwright.sync_api import sync_playwright
import time

def test_portal(nombre, url, wait_selector=None):
    print(f"\n{'='*60}")
    print(f"TESTING: {nombre}")
    print(f"URL: {url}")
    print('='*60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
            locale="es-ES"
        )

        # Capturar peticiones de red
        api_calls = []
        def on_request(req):
            url_r = req.url
            if any(x in url_r for x in ["api","json","xml","sumari","buscar","ajax","search","cerca","document"]):
                api_calls.append(f"  {req.method} {url_r[:120]}")

        page = ctx.new_page()
        page.on("request", on_request)

        try:
            page.goto(url, timeout=25000)
            page.wait_for_load_state("networkidle", timeout=15000)

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=5000)
                except Exception:
                    pass

            print(f"\nURL final: {page.url}")
            print(f"\nAPI calls capturadas ({len(api_calls)}):")
            for c in api_calls[:20]:
                print(c)

            print(f"\nTexto de la página (primeros 2000 chars):")
            texto = page.inner_text("body")
            print(texto[:2000])

            # Intentar extraer items de disposición
            print(f"\nIntentar extraer items via JS:")
            items = page.evaluate("""
                () => {
                    const sels = [
                        '.resultado', '.item-resultado', '.buscador-resultado',
                        '.disposicio', '.document-item', '.llistat-item',
                        'article', '.list-item', '.search-result', 'tr td a',
                        '.cerca-resultat', '.fitxa-item'
                    ];
                    const found = [];
                    for (const sel of sels) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 0) {
                            found.push(`${sel}: ${els.length} elementos`);
                            const el = els[0];
                            found.push(`  primer: ${el.textContent.trim().substring(0,100)}`);
                        }
                    }
                    return found;
                }
            """)
            for item in items:
                print(f"  {item}")

        except Exception as e:
            print(f"ERROR: {e}")

        browser.close()


# Test BOJA
test_portal(
    "BOJA - buscador fotovoltaica 28/04/2026",
    "https://www.juntadeandalucia.es/boja/buscador/?buscar=fotovoltaica&desde=28%2F04%2F2026&hasta=28%2F04%2F2026&tipoFecha=F"
)

# Test DOGC
test_portal(
    "DOGC - documento 28/04/2026",
    "https://dogc.gencat.cat/ca/document-del-dogc/?documentId=20260428"
)

# Test DOGV
test_portal(
    "DOGV - XML 28/04/2026",
    "https://dogv.gva.es/datos/2026/04/28/xml/20260428.xml"
)

print("\n\nDIAGNÓSTICO COMPLETADO")
