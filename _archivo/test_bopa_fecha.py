"""
test_bopa_fecha.py — Encontrar la fecha real de un boletín del BOPA.
python test_bopa_fecha.py
"""
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Test 1: Últimos boletines — ver qué fechas tienen publicaciones
print("=== Últimos boletines BOPA ===")
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    page = ctx.new_page()
    page.goto("https://miprincipado.asturias.es/bopa/ultimos-boletines", timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)

    # Extraer todas las fechas y links de boletines
    items = page.evaluate("""
        () => {
            const out = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const txt = a.textContent.trim();
                const href = a.href;
                if ((txt.includes('2026') || txt.includes('202') || href.includes('bopa')) && txt.length > 3) {
                    out.push({t: txt.substring(0,80), u: href});
                }
            });
            return out;
        }
    """)
    print("Links con fechas/boletines:")
    for it in items[:20]:
        print(f"  [{it['t']}] {it['u']}")

    txt = page.inner_text("body")
    # Buscar fechas en el texto
    import re
    fechas = re.findall(r'\d{1,2}[/\-]\d{1,2}[/\-]20\d{2}|\d{2}\s+de\s+\w+\s+de\s+20\d{2}|BOPA\s+n[ºo]\s*\d+', txt)
    print(f"\nFechas encontradas: {fechas[:20]}")
    print(f"\nTexto (2000 chars):\n{txt[:2000]}")
    b.close()

# Test 2: probar fecha de un lunes reciente
print("\n=== Test fecha concreta ===")
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    page = ctx.new_page()

    # El BOPA publica L/X/V — probar 05/05/2026 (martes) y 06/05/2026 (miércoles)
    for fecha_str in ["05/05/2026", "06/05/2026", "04/05/2026", "30/04/2026", "29/04/2026"]:
        DATE_ID = "_pa_sede_bopa_web_portlet_SedeBopaDispositionWeb_p_r_p_dispositionDate"
        page.goto("https://miprincipado.asturias.es/bopa/disposiciones", timeout=20000)
        page.wait_for_load_state("networkidle", timeout=12000)
        try:
            page.evaluate(f"""
                () => {{
                    const inp = document.getElementById('{DATE_ID}');
                    if (inp) inp.value = '{fecha_str}';
                    const form = document.querySelector('form[id*="SedeBopaDispositionWeb"]');
                    if (form) form.submit();
                }}
            """)
            page.wait_for_load_state("networkidle", timeout=10000)
            page.wait_for_timeout(500)
            txt = page.inner_text("body")
            has = any(w in txt for w in ["Resolución","Decreto","Orden","ANUNCIO"])
            error = "incorrecto" in txt.lower() or "no se ha" in txt.lower()
            print(f"  {fecha_str}: contenido={'SI' if has else 'NO'} error={'SI' if error else 'NO'}")
            if has:
                print(f"  EXITO — primer resultado: {txt[txt.find('Resolución'):txt.find('Resolución')+200]}")
                break
        except Exception as e:
            print(f"  {fecha_str}: ERROR {e}")

    b.close()
print("\nCOMPLETADO")
