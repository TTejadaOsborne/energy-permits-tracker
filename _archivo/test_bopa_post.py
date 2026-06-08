"""
test_bopa_post.py — Probar formatos de fecha del BOPA y capturar API con Playwright.
python test_bopa_post.py > bopa_post_diag.txt 2>&1
type bopa_post_diag.txt
"""
import requests, json
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

# La URL con ?fecha=DD/MM/YYYY llega pero dice "formato incorrecto"
# El portlet Liferay tiene un parámetro específico
# Del HTML sabemos: input#_pa_sede_bopa_web_portlet_SedeBopaDispositionWeb_p_r_p_dispositionDate
# Probar con ese parámetro exacto
BASE = "https://miprincipado.asturias.es"

print("=== Test 1: parámetro del portlet Liferay ===")
for fecha_fmt in ["24/04/2026", "2026-04-24", "20260424", "24-04-2026", "04/24/2026"]:
    url = f"{BASE}/bopa/disposiciones?_pa_sede_bopa_web_portlet_SedeBopaDispositionWeb_p_r_p_dispositionDate={fecha_fmt}"
    r = s.get(url, timeout=10)
    # Buscar si hay contenido de disposiciones
    has_content = "Resolución" in r.text or "Decreto" in r.text or "Orden" in r.text
    error_msg   = "formato" in r.text.lower() and "incorrecto" in r.text.lower()
    print(f"  {fecha_fmt}: {r.status_code} | {len(r.content)}B | contenido={'SI' if has_content else 'NO'} | error={'SI' if error_msg else 'NO'}")
    if has_content:
        soup = BeautifulSoup(r.text, "lxml")
        print(f"  EXITO - encontrando items...")
        # Buscar los items
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            if len(txt) > 40 and any(w in txt for w in ["Resolución","Decreto","Orden","RESOLUCIÓN"]):
                print(f"    [{txt[:100]}] {a['href'][:60]}")
        break

print()
print("=== Test 2: Playwright con cookies y POST ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    page = ctx.new_page()

    apis = []
    def on_resp(resp):
        if resp.status == 200:
            url = resp.url
            ct = resp.headers.get("content-type","")
            if "json" in ct and "bopa" in url.lower():
                try:
                    apis.append({"url": url, "body": resp.text()[:500]})
                except Exception:
                    pass

    page.on("response", on_resp)

    # Navegar y rellenar el formulario
    page.goto(f"{BASE}/bopa/disposiciones", timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)

    # Aceptar cookies si aparece el banner
    try:
        btn_cookies = page.locator("button:has-text('Aceptar')").first
        if btn_cookies.is_visible():
            btn_cookies.click()
            page.wait_for_timeout(500)
    except Exception:
        pass

    # Buscar el campo de fecha del portlet
    campos_fecha = page.evaluate("""
        () => {
            const inputs = document.querySelectorAll('input');
            return Array.from(inputs).map(i => ({
                id: i.id, name: i.name, type: i.type,
                value: i.value, placeholder: i.placeholder,
                visible: i.offsetParent !== null
            })).filter(i => i.visible || i.id.includes('Date') || i.id.includes('date'));
        }
    """)
    print(f"Inputs encontrados:")
    for c in campos_fecha:
        print(f"  id={c['id']} name={c['name']} type={c['type']} placeholder={c['placeholder']}")

    # Intentar rellenar el campo de fecha con el ID del portlet
    date_input_id = "_pa_sede_bopa_web_portlet_SedeBopaDispositionWeb_p_r_p_dispositionDate"
    try:
        inp = page.locator(f"#{date_input_id}").first
        if inp.count() > 0:
            inp.fill("24/04/2026")
            print(f"\nCampo {date_input_id} rellenado con 24/04/2026")

            # Click en el botón buscar
            btn = page.locator(f"#{date_input_id.replace('_p_r_p_dispositionDate','_submit')}").first
            if btn.count() == 0:
                btn = page.locator("button[type='submit'], input[type='submit']").first
            btn.click()
            page.wait_for_load_state("networkidle", timeout=10000)
            page.wait_for_timeout(1000)

            # Ver resultado
            txt = page.inner_text("body")
            has_content = any(w in txt for w in ["Resolución","Decreto","Orden"])
            print(f"Resultado: contenido={'SI' if has_content else 'NO'}")
            if has_content:
                print(txt[:2000])
            else:
                # Buscar mensaje de error
                for line in txt.split("\n"):
                    if "formato" in line.lower() or "fecha" in line.lower() or "error" in line.lower():
                        print(f"  MSG: {line.strip()}")
        else:
            print("Campo de fecha NO encontrado")

    except Exception as e:
        print(f"Error: {e}")

    # Ver URL final
    print(f"\nURL final: {page.url}")
    print(f"APIs capturadas: {len(apis)}")
    for api in apis:
        print(f"  {api['url']}\n  {api['body'][:200]}")

    browser.close()

# BORM: intentar con Playwright con timeout mayor
print()
print("=== BORM: Playwright con timeout extendido ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    page = ctx.new_page()

    borm_requests = []
    def on_req_borm(req):
        url = req.url
        if "borm" in url.lower() or "murcia" in url.lower():
            if any(x in url for x in ["api","json","sumario","boletin","data","search"]):
                borm_requests.append({"m": req.method, "u": url})

    page.on("request", on_req_borm)

    try:
        page.goto("https://www.borm.es/#/home", timeout=30000)
        # NO esperar networkidle — solo domcontentloaded
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(8000)  # Esperar que Angular cargue

        print(f"URL: {page.url}")
        print(f"Requests capturadas: {len(borm_requests)}")
        for req in borm_requests[:15]:
            print(f"  {req['m']} {req['u']}")

        txt = page.inner_text("body")
        print(f"\nTexto BORM (2000 chars):\n{txt[:2000]}")

    except Exception as e:
        print(f"Error BORM: {e}")

    browser.close()

print("\nCOMPLETADO")
