#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Busqueda avanzada de SET de conexion en el texto completo de los boletines.

Para proyectos sin set_vinculada, descarga el texto completo de sus publicaciones
(BOE via API XML; resto de boletines via HTML) y extrae menciones de subestaciones,
vinculandolas contra las SETs del Monitor (sets_capacity.json).

Ejecutar en un equipo con acceso a internet:
    python fetch_boletin_sets.py                 # solo proyectos fallidos (prioritarios)
    python fetch_boletin_sets.py --todos         # todos los proyectos sin SET
    python fetch_boletin_sets.py --max 50        # limitar numero de proyectos

Cache de textos en references/boletin_cache/ (reanudable).
Al terminar regenera projects_data.js.
"""
import json, re, sys, time, html, unicodedata
from pathlib import Path
from urllib.request import urlopen, Request

from link_projects_sets import (norm_name, extract_kvs, build_monitor_index,
                                RE_MENCION, RE_CTX)

CACHE = Path('references/boletin_cache')
CACHE.mkdir(parents=True, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Nodalys capacity research; contacto: tomitejada@gmail.com)'}

def fetch(url, cache_key):
    f = CACHE / (re.sub(r'[^\w.-]', '_', cache_key)[:120] + '.txt')
    if f.exists():
        return f.read_text(encoding='utf-8', errors='replace')
    try:
        # BOE: usar API XML (texto limpio)
        m = re.search(r'id=(BOE-[A-Z]-\d{4}-\d+)', url)
        if m:
            url = 'https://www.boe.es/diario_boe/xml.php?id=' + m.group(1)
        raw = urlopen(Request(url, headers=UA), timeout=30).read().decode('utf-8', errors='replace')
        # quitar tags
        txt = re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>', ' ', raw)
        txt = html.unescape(re.sub(r'<[^>]+>', ' ', txt))
        txt = ' '.join(txt.split())
        f.write_text(txt, encoding='utf-8')
        time.sleep(1.0)  # rate limit
        return txt
    except Exception as e:
        print(f'    WARN fetch {url[:60]}: {e}')
        return ''

def make_linker(caps):
    idx = build_monitor_index(caps)
    import collections
    tok1 = collections.defaultdict(list)
    for n in idx:
        t = n.split()[0] if n.split() else ''
        if t: tok1[t].append(n)
    strip_art = lambda s: ' '.join(w for w in s.split() if w not in ('LA','EL','LOS','LAS','DE','DEL'))
    art_idx = {}
    for n in idx:
        art_idx.setdefault(strip_art(n), n)

    def link(nombre, kvs):
        if nombre in idx:
            cands = idx[nombre]
            wk = [c for c in cands if c[1] in kvs]
            if wk: return max(wk, key=lambda c: c[1])[0], 'exacto'
            return max(cands, key=lambda c: c[1])[0], 'tension'
        na = strip_art(nombre)
        if na in art_idx:
            cands = idx[art_idx[na]]
            wk = [c for c in cands if c[1] in kvs]
            return max(wk or cands, key=lambda c: c[1])[0], 'exacto'
        t = nombre.split()[0] if nombre.split() else ''
        best = None
        for n in tok1.get(t, []):
            if len(n) >= 5 and (nombre.startswith(n) or n.startswith(nombre)):
                if best is None or len(n) > len(best): best = n
        if best and kvs:
            wk = [c for c in idx[best] if c[1] in kvs]
            if wk: return max(wk, key=lambda c: c[1])[0], 'prefijo'
        return None, None
    return link

def main():
    solo_fallidos = '--todos' not in sys.argv
    maxn = None
    if '--max' in sys.argv:
        maxn = int(sys.argv[sys.argv.index('--max') + 1])

    pj = json.load(open('projects.json', encoding='utf-8'))
    caps = json.load(open('sets_capacity.json', encoding='utf-8'))
    link = make_linker(caps)

    targets = [p for p in pj['proyectos']
               if (not p.get('set_vinculada') or not p.get('potencia_mw'))
               and (p.get('tecnologia') or '') not in ('SET', 'LAT')
               and (not solo_fallidos or p.get('es_fallido'))]
    # prioridad: fallidos con mas MW primero
    targets.sort(key=lambda p: -(p.get('potencia_mw') or 0))
    if maxn: targets = targets[:maxn]
    print(f'objetivo: {len(targets)} proyectos ({"solo fallidos" if solo_fallidos else "todos"})')

    encontrados = 0
    for i, p in enumerate(targets, 1):
        print(f'[{i}/{len(targets)}] {p["nombre"][:60]}')
        blob = ''
        for pub in (p.get('publicaciones') or []) + (p.get('publicaciones_infra') or []):
            u = pub.get('url')
            if u:
                blob += '  ' + fetch(u, pub.get('id_boe') or u)
        if not blob.strip():
            continue
        # backfill potencia / promotor desde el texto completo
        if not p.get('potencia_mw'):
            from link_projects_sets import RE_MW
            cands = [float(m.group(1).replace(',', '.')) for m in RE_MW.finditer(blob)]
            cands = [c for c in cands if 0.05 <= c <= 2000]
            if cands:
                p['potencia_mw'] = max(cands)
                print(f'    potencia: {p["potencia_mw"]} MW (texto completo)')
        if not p.get('promotor'):
            from link_projects_sets import RE_PROM
            m2 = RE_PROM.search(blob)
            if m2:
                p['promotor'] = ' '.join(m2.group(1).split()).strip(' ,.')
        # candidatos con contexto de conexion priorizados
        cands = []
        for m in RE_MENCION.finditer(blob):
            nombre = ' '.join(m.group(1).split()).strip(' ,.')
            if len(nombre) < 3: continue
            ctx = blob[max(0, m.start()-90): m.end()+90]
            score = 1 if RE_CTX.search(ctx) else 0
            kvtxt = blob[m.start(): m.end()+30]
            cands.append((score, nombre, kvtxt))
        cands.sort(key=lambda c: -c[0])
        for score, nombre, kvtxt in cands:
            kvs = extract_kvs(kvtxt)
            if p.get('tension_kv'):
                try: kvs.add(float(p['tension_kv']))
                except (TypeError, ValueError): pass
            key, how = link(norm_name(nombre), kvs)
            if key:
                p['set_vinculada'] = key
                p['set_match'] = how
                p['set_fuente'] = 'boletin_texto'
                p['set_conexion_detectada'] = 'SET ' + nombre
                print(f'    OK -> {key} ({how}, "{nombre}")')
                encontrados += 1
                break

    json.dump(pj, open('projects.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    Path('projects_data.js').write_text(
        'window.PROJECTS_INLINE = ' + json.dumps(pj, ensure_ascii=False) + ';', encoding='utf-8')
    n = len(pj['proyectos'])
    cv = sum(1 for x in pj['proyectos'] if x.get('set_vinculada'))
    print(f'\nencontrados: {encontrados} | SET vinculada total: {cv}/{n} ({cv*100//n}%)')

if __name__ == '__main__':
    main()
