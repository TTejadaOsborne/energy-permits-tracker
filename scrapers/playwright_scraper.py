"""
playwright_scraper.py — Scrapers Playwright para BOJA y DOGC.
Requiere: pip install playwright && playwright install chromium

BOJA: Interacción real con formulario de búsqueda avanzada
DOGC: Intercepta respuesta POST a eadop-rest/api/dogc/documentDOGC
"""

import logging
import time
import re
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_DISPONIBLE = True
except ImportError:
    PLAYWRIGHT_DISPONIBLE = False


def _get_es_relevante():
    for mod in ["scrapers.multi_scraper", "multi_scraper"]:
        try:
            import importlib
            m = importlib.import_module(mod)
            return m.es_relevante
        except Exception:
            pass
    return lambda titulo, **kw: True


def _launch(playwright):
    return playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox","--disable-setuid-sandbox",
              "--disable-dev-shm-usage","--disable-gpu","--lang=es-ES"]
    )

def _ctx(browser):
    return browser.new_context(
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"),
        locale="es-ES", timezone_id="Europe/Madrid",
        viewport={"width":1280,"height":900},
    )


# ── BOJA ──────────────────────────────────────────────────────────────────────
class BOJAPlaywrightScraper:
    """
    BOJA — Boletín Oficial de la Junta de Andalucía
    Interacción real con el formulario de búsqueda: rellena campos, hace click en
    Búsqueda avanzada para activar filtros de fecha, y extrae resultados del DOM.
    """
    NOMBRE = "BOJA"
    CCAA   = "Andalucía"
    URL    = "https://www.juntadeandalucia.es/boja/buscador/"

    KEYWORDS = [
        "fotovoltaica", "eólico", "aerogenerador",
        "subestación", "hidrógeno", "almacenamiento energético",
        "biogás", "biomasa", "línea alta tensión", "parque eólico",
    ]

    def __init__(self):
        self.er = _get_es_relevante()

    def get_items(self, fecha: str) -> list:
        if not PLAYWRIGHT_DISPONIBLE:
            return []

        dt       = datetime.strptime(fecha, "%Y%m%d")
        fecha_str = f"{dt.day:02d}/{dt.month:02d}/{dt.year}"
        items     = []
        ids_vistos = set()

        with sync_playwright() as p:
            browser = _launch(p)
            ctx     = _ctx(browser)

            for kw in self.KEYWORDS:
                try:
                    page = ctx.new_page()
                    page.goto(self.URL, timeout=20000)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)

                    # Activar Búsqueda avanzada para ver campos de fecha
                    try:
                        adv = page.locator("a:has-text('Búsqueda avanzada'), "
                                          "button:has-text('Búsqueda avanzada'), "
                                          "input[value*='avanzada' i]").first
                        if adv.count() > 0:
                            adv.click()
                            page.wait_for_timeout(600)
                    except Exception:
                        pass

                    # Campo de texto principal
                    try:
                        campo = page.locator(
                            "input[name='buscar'], input[name='q'], "
                            "input[type='text']:visible, input[type='search']:visible"
                        ).first
                        campo.fill(kw)
                    except Exception as e:
                        logger.debug(f"BOJA campo texto: {e}")
                        page.close()
                        continue

                    # Campos de fecha
                    for sel_desde in ["input[name='desde']","input[id*='desde' i]",
                                      "input[placeholder*='desde' i]"]:
                        try:
                            f = page.locator(sel_desde).first
                            if f.count() > 0:
                                f.fill(fecha_str)
                                break
                        except Exception:
                            pass

                    for sel_hasta in ["input[name='hasta']","input[id*='hasta' i]",
                                      "input[placeholder*='hasta' i]"]:
                        try:
                            f = page.locator(sel_hasta).first
                            if f.count() > 0:
                                f.fill(fecha_str)
                                break
                        except Exception:
                            pass

                    # Seleccionar tipo de fecha si hay select
                    try:
                        sel_tipo = page.locator("select[name='tipoFecha']").first
                        if sel_tipo.count() > 0:
                            sel_tipo.select_option("F")
                    except Exception:
                        pass

                    # Submit
                    try:
                        btn = page.locator(
                            "input[type='submit'], button[type='submit'], "
                            "button:has-text('BUSCAR'), input[value='BUSCAR']"
                        ).first
                        btn.click()
                        page.wait_for_load_state("networkidle", timeout=12000)
                        page.wait_for_timeout(800)
                    except Exception as e:
                        logger.debug(f"BOJA submit: {e}")

                    # Extraer resultados del DOM
                    nuevos = self._extraer(page, fecha)
                    for item in nuevos:
                        key = item["titulo"][:70]
                        if key not in ids_vistos:
                            ids_vistos.add(key)
                            items.append(item)

                    page.close()
                    time.sleep(0.4)

                except Exception as e:
                    logger.debug(f"BOJA '{kw}': {e}")
                    try:
                        page.close()
                    except Exception:
                        pass

            browser.close()

        return items

    def _extraer(self, page, fecha: str) -> list:
        items = []
        try:
            rs = page.evaluate("""
                () => {
                    const out = [];
                    // Selectores de resultados del buscador BOJA
                    const sels = [
                        '.resultado-buscador', '.buscador-resultado', '.resultado',
                        '.hits li', '.hit', '.search-hits article',
                        '#resultados li', '.lista-resultados li',
                        'table.resultados tr', '.tabla-resultados tr',
                    ];
                    for (const sel of sels) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 0) {
                            els.forEach(el => {
                                const a   = el.querySelector('a');
                                const h   = el.querySelector('h2,h3,h4,strong');
                                const org = el.querySelector('.organismo,.consejeria,.dept');
                                const tit = (h?.textContent || a?.textContent || el.textContent || '').trim().substring(0,300);
                                if (tit.length > 30 && a?.href) {
                                    out.push({t: tit, u: a.href, o: org?.textContent?.trim()||''});
                                }
                            });
                            if (out.length > 0) break;
                        }
                    }
                    return out;
                }
            """)
            for r in rs:
                if self.er(r["t"], departamento=r.get("o","")):
                    items.append({
                        "boletin":"BOJA","ccaa":"Andalucía",
                        "id":f"BOJA-{fecha}-{len(items)}","fecha":fecha,
                        "departamento":r.get("o",""),"titulo":r["t"],
                        "url":r.get("u",""),"url_pdf":"","url_xml":"","texto":""
                    })
        except Exception as e:
            logger.debug(f"BOJA _extraer: {e}")
        return items

    def get_texto(self, item: dict) -> str:
        if not PLAYWRIGHT_DISPONIBLE or not item.get("url"):
            return ""
        try:
            with sync_playwright() as p:
                b = _launch(p); c = _ctx(b); pg = c.new_page()
                pg.goto(item["url"], timeout=20000)
                pg.wait_for_load_state("networkidle", timeout=10000)
                t = pg.inner_text("body"); b.close()
                return t[:8000]
        except Exception as e:
            logger.debug(f"BOJA texto: {e}")
            return ""


# ── DOGC ──────────────────────────────────────────────────────────────────────
class DOGCPlaywrightScraper:
    """
    DOGC — Diari Oficial de la Generalitat de Catalunya
    Intercepta la respuesta del POST a:
      https://portaldogc.gencat.cat/eadop-rest/api/dogc/documentDOGC
    La respuesta contiene el JSON con todas las disposiciones del día.
    """
    NOMBRE = "DOGC"
    CCAA   = "Cataluña"
    API_URL = "eadop-rest/api/dogc/documentDOGC"

    def __init__(self):
        self.er = _get_es_relevante()

    def get_items(self, fecha: str) -> list:
        if not PLAYWRIGHT_DISPONIBLE:
            return []

        items = []
        api_data = []

        with sync_playwright() as p:
            browser = _launch(p)
            ctx     = _ctx(browser)
            page    = ctx.new_page()

            # Interceptar la respuesta de la API
            def on_response(resp):
                if self.API_URL in resp.url:
                    try:
                        data = resp.json()
                        api_data.append(data)
                        logger.debug(f"DOGC API capturada: {resp.url[-60:]}")
                    except Exception as e:
                        logger.debug(f"DOGC API parse: {e}")
                        try:
                            # Intentar con texto si no es JSON directo
                            import json
                            api_data.append(json.loads(resp.text()))
                        except Exception:
                            pass

            page.on("response", on_response)

            try:
                url = f"https://dogc.gencat.cat/ca/document-del-dogc/?documentId={fecha}"
                page.goto(url, timeout=25000)
                # Esperar más tiempo para que se complete el POST
                page.wait_for_load_state("networkidle", timeout=18000)
                page.wait_for_timeout(3000)  # Extra: asegurar que la API responde

            except Exception as e:
                logger.debug(f"DOGC navegación: {e}")

            if api_data:
                for data in api_data:
                    items.extend(self._parse_json(data, fecha))
                logger.debug(f"DOGC: {len(items)} items de API JSON")
            else:
                # Fallback DOM
                items = self._parse_dom(page, fecha)
                logger.debug(f"DOGC: {len(items)} items de DOM (sin API)")

            page.close()
            browser.close()

        return items

    def _parse_json(self, data, fecha: str) -> list:
        items = []
        if not data:
            return items

        # Normalizar estructura — la API puede tener distintas formas
        disposicions = []
        if isinstance(data, list):
            disposicions = data
        elif isinstance(data, dict):
            for key in ["disposicions","documents","items","results","data","content"]:
                if key in data and isinstance(data[key], list):
                    disposicions = data[key]
                    break
            if not disposicions:
                # Podría ser un objeto con lista de objetos hija
                for v in data.values():
                    if isinstance(v, list) and len(v) > 0:
                        disposicions = v
                        break
                if not disposicions:
                    disposicions = [data]  # El propio objeto

        er = self.er
        for d in disposicions:
            if not isinstance(d, dict):
                continue
            titulo = (d.get("titol") or d.get("titulo") or
                     d.get("title") or d.get("nom") or
                     d.get("descripcio") or "").strip()
            dept = (d.get("organisme") or d.get("organismo") or
                   d.get("departament") or d.get("department") or "").strip()
            url  = (d.get("urlHtml") or d.get("url_html") or
                   d.get("url") or "").strip()
            url_pdf = (d.get("urlPdf") or d.get("url_pdf") or "").strip()
            item_id = (str(d.get("id") or d.get("codi") or d.get("idDocument") or
                      f"DOGC-{fecha}-{len(items)}"))

            if not titulo or len(titulo) < 20:
                continue

            if er(titulo, departamento=dept):
                items.append({
                    "boletin":"DOGC","ccaa":"Cataluña",
                    "id":f"DOGC-{item_id}","fecha":fecha,
                    "departamento":dept,"titulo":titulo[:300],
                    "url":url,"url_pdf":url_pdf,"url_xml":"","texto":""
                })

        return items

    def _parse_dom(self, page, fecha: str) -> list:
        items = []
        try:
            rs = page.evaluate("""
                () => {
                    const out = [];
                    const sels = [
                        '.llistat-disposicions li', '.disposicio-item',
                        '.document-list li', 'table.sumari tr',
                        '.cerca-resultats .item', '.fitxa-disposicio',
                        '.list-group-item', '.card-body'
                    ];
                    for (const sel of sels) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 1) {
                            els.forEach(el => {
                                const a = el.querySelector('a');
                                const tEl = el.querySelector('.titol,.titulo,h3,h4,td:nth-child(2),p');
                                const oEl = el.querySelector('.organisme,.organismo,.dept');
                                const t = (tEl?.textContent || a?.textContent||'').trim();
                                if (t.length > 30 && a?.href) {
                                    out.push({t, u:a.href, o:oEl?.textContent?.trim()||''});
                                }
                            });
                            if (out.length > 0) break;
                        }
                    }
                    return out;
                }
            """)
            for r in rs:
                if self.er(r["t"], departamento=r.get("o","")):
                    items.append({
                        "boletin":"DOGC","ccaa":"Cataluña",
                        "id":f"DOGC-{fecha}-{len(items)}","fecha":fecha,
                        "departamento":r.get("o",""),"titulo":r["t"][:300],
                        "url":r.get("u",""),"url_pdf":"","url_xml":"","texto":""
                    })
        except Exception as e:
            logger.debug(f"DOGC DOM: {e}")
        return items

    def get_texto(self, item: dict) -> str:
        if not PLAYWRIGHT_DISPONIBLE or not item.get("url"):
            return ""
        try:
            with sync_playwright() as p:
                b = _launch(p); c = _ctx(b); pg = c.new_page()
                pg.goto(item["url"], timeout=20000)
                pg.wait_for_load_state("networkidle", timeout=10000)
                t = pg.inner_text("body"); b.close()
                return t[:8000]
        except Exception as e:
            logger.debug(f"DOGC texto: {e}")
            return ""



# ── BOPA (Asturias) ───────────────────────────────────────────────────────────
class BOPAPlaywrightScraper:
    """
    BOPA — Boletín Oficial del Principado de Asturias
    El campo de fecha es type=hidden — se rellena via JS evaluate().
    """
    NOMBRE = "BOPA"
    CCAA   = "Asturias"
    BASE   = "https://miprincipado.asturias.es"

    def __init__(self):
        self.er = _get_es_relevante()

    def get_items(self, fecha: str) -> list:
        if not PLAYWRIGHT_DISPONIBLE:
            return []
        dt        = datetime.strptime(fecha, "%Y%m%d")
        fecha_str = f"{dt.day:02d}/{dt.month:02d}/{dt.year}"
        items     = []

        with sync_playwright() as p:
            browser = _launch(p)
            ctx     = _ctx(browser)
            page    = ctx.new_page()
            try:
                page.goto(f"{self.BASE}/bopa/disposiciones", timeout=20000)
                page.wait_for_load_state("networkidle", timeout=15000)

                # Aceptar cookies si aparece
                try:
                    btn = page.locator("button:has-text('Aceptar')").first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        page.wait_for_timeout(500)
                except Exception:
                    pass

                DATE_ID = "_pa_sede_bopa_web_portlet_SedeBopaDispositionWeb_p_r_p_dispositionDate"

                # Rellenar el hidden input y submit via JS
                page.evaluate(f"""
                    () => {{
                        const inp = document.getElementById('{DATE_ID}');
                        if (inp) inp.value = '{fecha_str}';
                        const form = document.querySelector('form[id*="SedeBopaDispositionWeb"]');
                        if (form) form.submit();
                    }}
                """)
                page.wait_for_load_state("networkidle", timeout=12000)
                page.wait_for_timeout(1000)
                items = self._extraer(page, fecha)

            except Exception as e:
                logger.warning(f"BOPA {fecha}: {e}")
            finally:
                page.close()
                browser.close()
        return items

    def _extraer(self, page, fecha: str) -> list:
        items = []
        try:
            rs = page.evaluate("""
                () => {
                    const out = [];
                    const links = document.querySelectorAll('[id*="SedeBopaDispositionWeb"] a[href], .portlet-body a[href], #content a[href]');
                    links.forEach(a => {
                        const txt = a.textContent.trim();
                        if (txt.length > 40) {
                            let org = '';
                            const parent = a.closest('li,div,article');
                            if (parent?.previousElementSibling) org = parent.previousElementSibling.textContent.trim().substring(0,100);
                            out.push({t: txt.substring(0,300), u: a.href, o: org});
                        }
                    });
                    return out;
                }
            """)
            for r in rs:
                if self.er(r["t"], departamento=r.get("o","")):
                    items.append({
                        "boletin":"BOPA","ccaa":"Asturias",
                        "id":f"BOPA-{fecha}-{len(items)}","fecha":fecha,
                        "departamento":r.get("o",""),"titulo":r["t"],
                        "url":r.get("u",""),"url_pdf":"","url_xml":"","texto":""
                    })
        except Exception as e:
            logger.debug(f"BOPA _extraer: {e}")
        return items


# ── Registro ──────────────────────────────────────────────────────────────────
# DOGC ya usa API REST directa (sin Playwright)
# BOJA sigue usando Playwright para interacción con formulario
PLAYWRIGHT_SCRAPERS = {
    "BOJA": BOJAPlaywrightScraper,
    "BOPA": BOPAPlaywrightScraper,
}


def get_playwright_scraper(nombre: str):
    if not PLAYWRIGHT_DISPONIBLE:
        return None
    cls = PLAYWRIGHT_SCRAPERS.get(nombre)
    return cls() if cls else None
