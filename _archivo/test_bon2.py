"""
test_bon2.py -- Inspecciona HTML de una pagina de anuncio individual
y busca patron de fecha + numero de edicion en el indice (script tags).
"""
import sys, re, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
})

# ── A. Volcar HTML de un anuncio conocido ─────────────────────────────────────
print("="*60)
print("A. Anuncio /es/anuncio/-/texto/2026/88/21 (URL confirmada)")
print("="*60)
r = s.get("https://bon.navarra.es/es/anuncio/-/texto/2026/88/21", timeout=25)
html = r.content.decode(r.encoding or "utf-8", errors="replace")
soup = BeautifulSoup(html, "lxml")

# Texto completo
full_txt = soup.get_text(" ", strip=True)
print("Texto completo (primeros 1500 chars):")
print(full_txt[:1500])
print("\n--- ultimos 500 chars ---")
print(full_txt[-500:])

# Selectores candidatos
print("\nSelectores:")
for sel in ["h1","h2","h3",".anuncio-titulo",".titulo",
            ".anuncio-contenido","article","main","#content",
            ".portlet-body",".journal-content-article",
            "#portlet_com_liferay",".entry-content"]:
    el = soup.select_one(sel)
    if el:
        t = el.get_text(" ", strip=True)[:150]
        print("  [{}]: {}".format(sel, t))

# Fecha en HTML?
fecha_matches = re.findall(r"\d{1,2}[\s/\-]\w+[\s/\-]\d{4}|\d{4}[\-/]\d{2}[\-/]\d{2}", html)
print("\nPatrones de fecha encontrados (primeros 10):")
for m in set(fecha_matches[:20]):
    print("  " + m)

# ── B. Buscar edicion en script tags del indice ───────────────────────────────
print("\n" + "="*60)
print("B. Script tags del indice (buscar '88' y '2026-05-07')")
print("="*60)
time.sleep(0.5)
r2 = s.get("https://bon.navarra.es/es/indice-boletines?mes=5&anio=2026", timeout=25)
html2 = r2.content.decode(r2.encoding or "utf-8", errors="replace")
soup2 = BeautifulSoup(html2, "lxml")

for i, script in enumerate(soup2.find_all("script")):
    content = script.string or ""
    if "88" in content and ("2026-05-07" in content or "mayo" in content.lower()):
        print("Script #{} (len={}):".format(i, len(content)))
        # Encontrar contexto alrededor de '88'
        idx = content.find("88")
        while idx != -1:
            snippet = content[max(0,idx-80):idx+80]
            if "fecha" in snippet.lower() or "mayo" in snippet.lower() or "2026" in snippet:
                print("  ...{}...".format(snippet.replace("\n"," ")))
            idx = content.find("88", idx+1)
        print()

# Tambien buscar en atributos data-* del HTML
print("\nAtributos data-* con '88' o fecha:")
for tag in soup2.find_all(True):
    for attr, val in tag.attrs.items():
        if isinstance(val, str) and ("88" in val or "2026-05-07" in val):
            print("  <{} {}='{}'>".format(tag.name, attr, val[:120]))

