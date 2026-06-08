"""
test_apis.py — Captura las respuestas JSON reales de BOJA, DOGC y BOPA.
Guarda los JSONs en archivos para construir los parsers definitivos.
Ejecutar: python test_apis.py
"""
import json, time, requests
from playwright.sync_api import sync_playwright

FECHA = "20260429"  # Martes — día laborable

def guardar(nombre, data):
    with open(f"api_{nombre}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Guardado: api_{nombre}.json ({len(str(data))} chars)")


# ══════════════════════════════════════════════════════════════
# 1. BOJA — contentapi (requests directo, accesible desde España)
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("BOJA contentapi")
print("="*60)

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.juntadeandalucia.es/eboja.html",
    "Accept": "application/json, */*",
})

# Calendario del día
boja_urls = [
    f"https://www.juntadeandalucia.es/ssdigitales/datasets/contentapi/boja/calendario?fechaDesde=2026-04-29&fechaHasta=2026-04-29",
    f"https://www.juntadeandalucia.es/ssdigitales/datasets/contentapi/boja/ultimo/secciones",
    f"https://www.juntadeandalucia.es/ssdigitales/datasets/contentapi/boja/secciones/20260429",
    f"https://www.juntadeandalucia.es/ssdigitales/datasets/contentapi/boja/disposiciones/20260429",
]

for url in boja_urls:
    r = s.get(url, timeout=15)
    print(f"  {r.status_code} | {len(r.content):6}B | {url[-70:]}")
    if r.status_code == 200 and len(r.content) > 100:
        try:
            data = r.json()
            guardar(f"boja_{url.split('/')[-1].replace('?','_')[:20]}", data)
        except Exception:
            print(f"    TEXT: {r.text[:300]}")


# ══════════════════════════════════════════════════════════════
# 2. DOGC — capturar respuesta del POST con Playwright route intercept
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("DOGC route intercept")
print("="*60)

dogc_data = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        locale="es-ES"
    )
    page = ctx.new_page()

    # Usar route para interceptar Y continuar la petición
    def handle_route(route, request):
        if "eadop-rest/api/dogc/documentDOGC" in request.url:
            print(f"  INTERCEPTANDO: {request.url}")
            print(f"  Method: {request.method}")
            print(f"  Headers: {dict(list(request.headers.items())[:5])}")
            print(f"  Body: {request.post_data}")
        route.continue_()

    page.route("**/*", handle_route)

    # También capturar la respuesta
    def on_response(resp):
        if "eadop-rest/api/dogc" in resp.url:
            try:
                body = resp.text()
                print(f"  RESPUESTA [{resp.status}]: {body[:500]}")
                try:
                    dogc_data.append(resp.json())
                except Exception:
                    dogc_data.append({"raw": body[:2000]})
            except Exception as e:
                print(f"  Error leyendo respuesta: {e}")

    page.on("response", on_response)

    url = f"https://dogc.gencat.cat/ca/document-del-dogc/?documentId={FECHA}"
    print(f"  Navegando a: {url}")
    page.goto(url, timeout=25000)
    page.wait_for_load_state("networkidle", timeout=20000)
    page.wait_for_timeout(4000)  # Espera extra

    if dogc_data:
        guardar("dogc", dogc_data[0])
        print(f"  ✓ API DOGC capturada")
    else:
        print("  ✗ No se capturó respuesta API del DOGC")
        # Guardar el HTML renderizado como fallback
        html = page.content()
        with open("dogc_rendered.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  Guardado dogc_rendered.html para análisis")

    browser.close()


# ══════════════════════════════════════════════════════════════
# 3. BOPA — capturar peticiones de red al buscar
# ══════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("BOPA miprincipado")
print("="*60)

bopa_data = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        locale="es-ES"
    )
    page = ctx.new_page()

    def on_resp_bopa(resp):
        url = resp.url
        ct = resp.headers.get("content-type","")
        if ("json" in ct or "xml" in ct) and "bopa" in url.lower():
            try:
                body = resp.text()
                print(f"  API [{resp.status}] {url[-80:]}")
                print(f"  Body: {body[:300]}")
                bopa_data.append({"url": url, "body": body[:5000]})
            except Exception as e:
                print(f"  Error: {e}")
        elif "json" in ct and resp.status == 200 and len(resp.url) > 30:
            try:
                body = resp.text()
                if len(body) > 200 and ("bopa" in body.lower() or "boletin" in body.lower()):
                    print(f"  JSON relevante [{resp.status}] {url[-80:]}")
                    print(f"  Body: {body[:200]}")
            except Exception:
                pass

    page.on("response", on_resp_bopa)

    # Navegar al buscador del BOPA
    page.goto("https://miprincipado.asturias.es/bopa/disposiciones", timeout=20000)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(2000)

    # Intentar buscar con keyword energético
    try:
        campo = page.locator("input[type='text'], input[type='search'], input[name='q'], input[name='search']").first
        if campo.count() > 0:
            campo.fill("fotovoltaica")
            print("  Campo de búsqueda rellenado")

            btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Buscar')").first
            if btn.count() > 0:
                btn.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                page.wait_for_timeout(2000)
                print("  Búsqueda ejecutada")
    except Exception as e:
        print(f"  Error en búsqueda: {e}")

    # Mostrar todas las peticiones de red capturadas
    if bopa_data:
        guardar("bopa", bopa_data)
    else:
        print("  No se encontraron APIs JSON del BOPA")
        # Guardar HTML renderizado
        html = page.content()
        with open("bopa_rendered.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  Guardado bopa_rendered.html")

    browser.close()

print("\n\nDIAGNÓSTICO COMPLETADO")
print("Archivos generados:")
import os
for f in os.listdir("."):
    if f.startswith("api_") or f in ["dogc_rendered.html","bopa_rendered.html"]:
        print(f"  {f} ({os.path.getsize(f)} bytes)")
