#!/usr/bin/env python3
"""debug_missing.py v2 — Encuentra fecha real y sección de BOE-B items."""
import sys, re, requests, xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import date, timedelta

sys.path.insert(0, '.')
from scrapers.multi_scraper import es_relevante, BOEScraper

IDS = [
    "BOE-B-2026-11631",
    "BOE-B-2026-10890",
    "BOE-B-2025-45742",
    "BOE-B-2024-21870",
]

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

def find_pub_date(item_id):
    """Extrae la fecha de publicación del HTML del ítem."""
    url = f"https://www.boe.es/diario_boe/txt.php?id={item_id}"
    try:
        r = session.get(url, timeout=20)
        # BOE HTML contains the date in various places
        soup = BeautifulSoup(r.text, 'html.parser')
        # Try canonical link or metadata
        canonical = soup.find('link', rel='canonical')
        if canonical:
            href = canonical.get('href', '')
            m = re.search(r'/dias/(\d{4})/(\d{2})/(\d{2})/', href)
            if m: return m.group(1)+m.group(2)+m.group(3)
        # Try PDF link
        pdf_link = soup.find('a', href=re.compile(r'/boe/dias/\d{4}/\d{2}/\d{2}/pdfs/'))
        if pdf_link:
            m = re.search(r'/dias/(\d{4})/(\d{2})/(\d{2})/', pdf_link['href'])
            if m: return m.group(1)+m.group(2)+m.group(3)
        # Try the boe-download link
        dl = soup.find('a', href=re.compile(r'BOE-B.*\.pdf'))
        if dl:
            m = re.search(r'/dias/(\d{4})/(\d{2})/(\d{2})/', dl['href'])
            if m: return m.group(1)+m.group(2)+m.group(3)
        # Try any link with /dias/ pattern
        for a in soup.find_all('a', href=True):
            m = re.search(r'/dias/(\d{4})/(\d{2})/(\d{2})/', a['href'])
            if m: return m.group(1)+m.group(2)+m.group(3)
    except Exception as e:
        print(f"    Error finding date: {e}")
    return None

def check_in_sumario(item_id, fecha):
    """Verifica en qué sección está el ítem en el sumario XML."""
    url = f"https://boe.es/datosabiertos/api/boe/sumario/{fecha}"
    try:
        r = session.get(url, timeout=15, headers={"Accept":"application/xml"})
        if item_id not in r.text:
            return None, None
        root = ET.fromstring(r.content)
        for sec in root.iter('seccion'):
            for item in sec.iter('item'):
                if (item.findtext('identificador') or '') == item_id:
                    dept = ''
                    for dept_el in sec.iter('departamento'):
                        for it2 in dept_el.iter('item'):
                            if (it2.findtext('identificador') or '') == item_id:
                                dept = dept_el.get('nombre','')
                    return sec.get('codigo'), sec.get('nombre','')[:50] + (f' | dept: {dept[:30]}' if dept else '')
    except: pass
    return None, None

def check_already_processed(fecha):
    """Verifica si la fecha ya tiene JSON de salida."""
    import os
    path = f"output/energy_extraido_{fecha}.json"
    if os.path.exists(path):
        import json
        data = json.loads(open(path, encoding='utf-8').read())
        n = len([r for r in data.get('resultados',[]) if r.get('es_energetico') and r.get('datos')])
        return True, n
    return False, 0

print("\n" + "="*65)
print("  DIAGNÓSTICO v2 — Fecha real + sección + estado pipeline")
print("="*65)

for item_id in IDS:
    print(f"\n── {item_id}")
    fecha = find_pub_date(item_id)
    print(f"   Fecha publicación: {fecha or 'NO ENCONTRADA'}")
    
    if fecha:
        sec_code, sec_name = check_in_sumario(item_id, fecha)
        print(f"   Sección XML: {sec_code or 'NOT FOUND'} — {sec_name or ''}")
        
        processed, n_results = check_already_processed(fecha)
        print(f"   Pipeline ejecutado: {'SÍ (' + str(n_results) + ' resultados)' if processed else 'NO'}")
        
        if sec_code:
            in_secciones = sec_code in {"1","2A","2B","3","5B","5C"}
            print(f"   En SECCIONES activas: {'✓ SÍ' if in_secciones else '✗ NO ← CAUSA DEL FALLO'}")
