#!/usr/bin/env python3
"""debug_boeb.py — Encuentra la URL correcta del índice BOE-B."""
import sys, re, requests, xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

FECHA = sys.argv[1] if len(sys.argv) > 1 else "20260505"
y,m,d = FECHA[:4], FECHA[4:6], FECHA[6:]
session = requests.Session()
session.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

KNOWN = "BOE-B-2026-14191"
print(f"\n{'='*60}\nDIAGNÓSTICO BOE-B — {FECHA}\n{'='*60}\n")

urls = [
    f"https://www.boe.es/boe/dias/{y}/{m}/{d}/",                    # índice general del día
    f"https://boe.es/datosabiertos/api/boe/sumario/{FECHA}",         # XML API (también incluye BOE-B?)
    f"https://www.boe.es/diario_boe/txt.php?id={KNOWN}",            # item directo (control)
]

for url in urls:
    print(f"\n── {url}")
    try:
        r = session.get(url, timeout=20, headers={"Accept":"application/xml,text/html,*/*"})
        print(f"   Status={r.status_code}  len={len(r.content):,}")
        if r.status_code != 200: continue
        text = r.text

        # Check BOE-B presence
        boeb_count = len(re.findall(r'BOE-B-\d{4}-\d+', text))
        print(f"   BOE-B IDs found: {boeb_count}")
        if boeb_count:
            ids = re.findall(r'BOE-B-\d{4}-\d+', text)[:10]
            print(f"   Sample IDs: {ids}")

        # If it's XML (sumario API)
        if 'xml' in r.headers.get('content-type','') or text.strip().startswith('<?xml') or text.strip().startswith('<'):
            try:
                root = ET.fromstring(r.content)
                secciones = {}
                for sec in root.iter('seccion'):
                    cod = sec.get('codigo','?')
                    nombre = sec.get('nombre','')
                    n_items = len(list(sec.iter('item')))
                    n_boeb = len([i for i in sec.iter('item')
                                  if (i.findtext('identificador','') or '').startswith('BOE-B')])
                    secciones[cod] = (nombre[:40], n_items, n_boeb)
                print(f"   XML sections:")
                for cod,(nom,n,nb) in sorted(secciones.items()):
                    flag = ' ← BOE-B !' if nb>0 else ''
                    print(f"     sec={cod!r:4s}  items={n:3d}  boeb={nb}  {nom}{flag}")
            except ET.ParseError as e:
                print(f"   XML parse error: {e}")

        # If it's HTML, try to find BOE-B links and section structure
        if '<html' in text.lower():
            soup = BeautifulSoup(text, 'html.parser')
            # Look for section B links
            secB = soup.find_all(string=re.compile(r'Secci.n\s*B|Anuncios\s*particulares', re.I))
            print(f"   'Sección B' text found: {len(secB)}")
            # Links to BOE-B items
            links = [a['href'] for a in soup.find_all('a',href=True)
                     if 'BOE-B' in a['href'] or 'boe-b' in a['href'].lower()]
            print(f"   BOE-B links: {len(links)}")
            for l in links[:5]: print(f"     {l}")
    except Exception as e:
        print(f"   ERROR: {e}")

# ── Try the BOE search API ──
print(f"\n── BOE Buscador API")
try:
    # BOE has a search endpoint
    search_url = f"https://boe.es/buscar/boe.php?campo%5B0%5D=TIT&dato%5B0%5D=&operador%5B0%5D=and&campo%5B1%5D=DOC&dato%5B1%5D=B&operador%5B1%5D=and&campo%5B2%5D=FPU&dato%5B2%5D={y}%2F{m}%2F{d}&campo%5B3%5D=FPU&dato%5B3%5D={y}%2F{m}%2F{d}&sort_field%5B0%5D=fpu&sort_order%5B0%5D=asc"
    r2 = session.get(search_url, timeout=20)
    text2 = r2.text
    ids2 = re.findall(r'BOE-B-\d{4}-\d+', text2)
    print(f"   Status={r2.status_code}  BOE-B IDs: {len(ids2)}")
    if ids2: print(f"   Sample: {ids2[:5]}")
except Exception as e:
    print(f"   ERROR: {e}")
