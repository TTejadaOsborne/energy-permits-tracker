import requests

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

tests = [
    # BOJA - nuevas variantes
    ("BOJA-v1", "https://www.juntadeandalucia.es/boja/boletines.html?fecha=28/04/2026"),
    ("BOJA-v2", "https://www.juntadeandalucia.es/boja/boletines/?fecha=28/04/2026"),

    # DOGV - bloqueado, probar variante del portal
    ("DOGV-v1", "https://dogv.gva.es/datos/2026/04/28/xml/20260428.xml"),

    # DOGC - ya funciona
    ("DOGC",    "https://dogc.gencat.cat/ca/document-del-dogc/?documentId=20260428"),

    # DOG Galicia - nueva ruta de secciones
    ("DOG-v1",  "https://www.xunta.gal/diario-oficial-galicia/mostrarContenido.do?lang=es&paginaCompleta=false&fecha=20260428&ruta=/2026/20260428/Secciones3_es.html"),
    ("DOG-v2",  "https://www.xunta.gal/dog/Publicados/2026/20260428/"),

    # BOPA - nueva sede
    ("BOPA-v1", "https://sede.asturias.es/bopa/daccess/bopa/bopa.xml?fecha=28/04/2026"),
    ("BOPA-v2", "https://sede.asturias.es/bopa/"),

    # BOC - ya funciona
    ("BOC",     "https://boc.cantabria.es/boces/verAnuncioAction.do?idAnuncioFecha=20260428"),

    # BORM - API datos abiertos
    ("BORM-API", "https://datosabiertos.regiondemurcia.es/api/action/datastore_search?resource_id=borm-indices-anual&q=28/04/2026&limit=5"),
    ("BORM-v2",  "https://www.borm.es/borm/"),
]

print(f"{'BOL':12} | ST  | SIZE     | URL")
print("-" * 100)

for nombre, url in tests:
    try:
        r = s.get(url, timeout=12, allow_redirects=True)
        size = len(r.content)
        ok = "OK " if r.status_code == 200 and size > 500 else f"{r.status_code}"
        print(f"{nombre:12} | {ok:4}| {size:7}B | {r.url[:65]}")
        if r.status_code == 200 and size > 200:
            txt = r.text[:150].replace('\n', ' ')
            print(f"             >> {txt}")
    except Exception as e:
        print(f"{nombre:12} | ERR | {str(e)[:70]}")
    print()
