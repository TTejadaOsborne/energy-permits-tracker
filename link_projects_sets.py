#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enriquece projects.json:
1. Backfill potencia_mw / promotor / subestacion desde titulos de publicaciones.
2. Vincula subestacion a una SET del Monitor (claves de sets_capacity.json)
   -> campos: set_vinculada, set_match ('exacto'|'tension'|'prefijo'|'fuzzy').
Uso: python link_projects_sets.py <projects.json> <sets_capacity.json> <out.json>
"""
import json, re, sys, unicodedata
from difflib import SequenceMatcher

def deaccent(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')

def norm_name(s):
    s = deaccent(str(s or '').upper())
    s = re.sub(r'\b(?:SET|S\.?E\.?|SUBESTACION|SUB\.?|ST|NUDO|CT|CD)\b\.?', ' ', s)
    s = re.sub(r'\d+(?:[.,]\d+)?\s*(?:/\s*\d+(?:[.,]\d+)?)*\s*KV', ' ', s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return ' '.join(s.split())

def extract_kvs(s):
    kvs = set()
    for m in re.finditer(r'(\d+(?:[.,]\d+)?)\s*(?:/\s*(\d+(?:[.,]\d+)?))?\s*KV',
                         deaccent(str(s or '').upper())):
        for g in m.groups():
            if g:
                try: kvs.add(float(g.replace(',', '.')))
                except ValueError: pass
    return kvs

RE_MW = re.compile(r'(\d{1,4}(?:[.,]\d{1,3})?)\s*(?:MWP?|MWN)\b', re.I)
RE_SET = re.compile(
    r'(?:SET|S\.E\.|SUBESTACI[OÓ]N(?:\s+EL[EÉ]CTRICA)?)\s+(?:DE\s+)?'
    r'[«"]?([A-ZÁ-Ÿ][\w\sÁ-ÿ\'.-]{2,38}?)[»"]?'
    r'(?=\s*(?:[,;.)(]|\s\d+(?:[/.,]\d+)?\s*kV|\sde\s\d|$))', re.I)
RE_PROM = re.compile(
    r'(?:otorga(?:da)?\s+a|promovid[oa]\s+por|titularidad\s+de|'
    r'solicitad[oa]\s+por|a\s+favor\s+de)\s+'
    r'([A-ZÁ-Ÿ][\w\sÁ-ÿ&.,\'-]{4,90}?(?:S\.?[LA]\.?U?\.?|SLU|SL|SA|SAU))', re.I)

def backfill(p):
    """Rellena campos null desde los titulos de publicaciones (mas reciente primero)."""
    titles = [pub.get('titulo') or '' for pub in (p.get('publicaciones') or [])]
    titles.sort(key=len, reverse=True)
    blob = '  '.join(titles)
    filled = []
    if not p.get('potencia_mw'):
        cands = [float(m.group(1).replace(',', '.')) for m in RE_MW.finditer(blob)]
        cands = [c for c in cands if 0.05 <= c <= 2000]
        if cands:
            p['potencia_mw'] = max(cands)
            filled.append('potencia')
    if not p.get('promotor'):
        m = RE_PROM.search(blob)
        if m:
            p['promotor'] = ' '.join(m.group(1).split()).strip(' ,.')
            filled.append('promotor')
    if not p.get('subestacion'):
        m = RE_SET.search(blob)
        if m:
            nombre = ' '.join(m.group(1).split()).strip(' ,.')
            if len(nombre) >= 3 and not nombre.upper().startswith(('TRANSFORMADORA', 'ELEVADORA')):
                p['subestacion'] = 'SET ' + nombre
                filled.append('subestacion')
    return filled

RE_MENCION = re.compile(
    r"(?:SET|S\.E\.|SE|SUBESTACI[OÓ]N(?:\s+EL[EÉ]CTRICA)?|NUDO)\s+(?:DE\s+)?"
    r"[«\"]?([A-ZÁ-Ÿ][\w\sÁ-ÿ'.-]{2,38}?)[»\"]?"
    r"(?=\s*(?:[,;.)(]|\s\d+(?:[/.,]\d+)?\s*kV|\sde\s|\spropiedad|\stitularidad|$))", re.I)
RE_CTX = re.compile(
    r"conexi[oó]n|evacuaci[oó]n|\bnudo\b|propiedad\s+de|titularidad\s+de|"
    r"\bREE\b|Red\s+El[eé]ctrica|i-?DE\b|Iberdrola|UFD|E-?Distribuci[oó]n|Endesa|Viesgo|Naturgy|E-?Redes", re.I)

def harvest_candidatos(p):
    """Menciones de SET en titulos + observaciones, priorizadas por contexto de conexion/titular de red."""
    parts = []
    for pub in (p.get('publicaciones') or []):
        parts.append(pub.get('titulo') or '')
        parts.append(pub.get('observaciones') or '')
    cands = []
    seen = set()
    for txt in parts:
        for m in RE_MENCION.finditer(txt):
            nombre = ' '.join(m.group(1).split()).strip(' ,.')
            if len(nombre) < 3: continue
            ctx = txt[max(0, m.start()-70): m.end()+70]
            score = 1 if RE_CTX.search(ctx) else 0
            # tension cercana a la mencion
            kvtxt = txt[m.start(): m.end()+25]
            k = nombre + '|' + str(score)
            if k in seen: continue
            seen.add(k)
            cands.append((nombre, kvtxt, score))
    cands.sort(key=lambda c: -c[2])
    return cands

def build_monitor_index(caps):
    """key 'NOMBRE KV' -> (nombre_sin_kv, kv). Indices por nombre."""
    idx = {}
    for key in caps:
        if key.startswith('_'): continue
        m = re.match(r'^(.*?)[ ]+(\d+(?:\.\d+)?)$', key)
        if not m: continue
        nombre = norm_name(m.group(1))
        kv = float(m.group(2))
        idx.setdefault(nombre, []).append((key, kv))
    return idx

def link_set(p, idx, names, no_fuzzy=False):
    sub = p.get('subestacion')
    if not sub: return None, None
    if re.search(r'centro\s+de\s+(seccionamiento|transformaci[oó]n)|\bCS\b|\bCT[- ]?\d', str(sub), re.I):
        return None, None
    nombre = norm_name(sub)
    if len(nombre) < 3: return None, None
    kvs = extract_kvs(sub)
    if p.get('tension_kv'):
        try: kvs.add(float(p['tension_kv']))
        except (TypeError, ValueError): pass

    # 1) nombre exacto + tension
    if nombre in idx:
        cands = idx[nombre]
        with_kv = [c for c in cands if c[1] in kvs]
        if with_kv:
            return max(with_kv, key=lambda c: c[1])[0], 'exacto'
        return max(cands, key=lambda c: c[1])[0], 'tension'
    # 2) prefijo (nombres truncados en Monitor, ej. AGUADULC)
    pref = [n for n in names if len(n) >= 5 and (nombre.startswith(n) or n.startswith(nombre))]
    if pref:
        best = max(pref, key=len)
        cands = idx[best]
        with_kv = [c for c in cands if c[1] in kvs]
        pick = max(with_kv or cands, key=lambda c: c[1])
        return pick[0], 'prefijo'
    # 3) sin articulos (LA ELIANA == ELIANA)
    strip_art = lambda s: ' '.join(w for w in s.split() if w not in ('LA','EL','LOS','LAS','DE','DEL'))
    nom2 = strip_art(nombre)
    if nom2 and nom2 != nombre:
        for n in names:
            if strip_art(n) == nom2:
                cands = idx[n]
                with_kv = [c for c in cands if c[1] in kvs]
                pick = max(with_kv or cands, key=lambda c: c[1])
                return pick[0], 'exacto'
    # 4) tokens del Monitor contenidos en la subestacion (con tension obligatoria)
    toks = set(nombre.split())
    if kvs:
        tcands = []
        for n in names:
            ntoks = set(n.split())
            if ntoks and ntoks <= toks:
                for key, kv in idx[n]:
                    if kv in kvs:
                        tcands.append((key, kv, len(n)))
        if tcands:
            tcands.sort(key=lambda c: (-c[2], -c[1]))
            return tcands[0][0], 'prefijo'
    # 5) fuzzy
    if no_fuzzy: return None, None
    best, best_r = None, 0.0
    for n in names:
        if abs(len(n) - len(nombre)) > 6: continue
        r = SequenceMatcher(None, nombre, n).ratio()
        if r > best_r:
            best, best_r = n, r
    if best and best_r >= 0.94:
        with_kv = [c for c in idx[best] if c[1] in kvs]
        if with_kv:
            return max(with_kv, key=lambda c: c[1])[0], 'fuzzy'
    return None, None

RE_ESSET = re.compile(r"^(?:AMPLIACI[OÓ]N|NUEVA?\s+)?(?:SUBESTACI[OÓ]N|SET\b|S\.E\.|ST\b)", re.I)
RE_LINEA = re.compile(r"^(?:L[IÍ]NEAS?\b|LAT\b|LAAT\b|LSAT\b|L\.A\.A?\.?T|REFORMA\s+DE\s+L|MODIFICACI[OÓ]N\s+DE\s+L|SUSTITUCI[OÓ]N\s+DE)|L[IÍ]NEA\s+A[EÉ]REA", re.I)
RE_AMPLIA = re.compile(r"AMPLIACI[OÓ]N|NUEVA\s+POSICI[OÓ]N|BAH[IÍ]A|TRANSFORMADOR|BLINDAJE|\bY\s+(?:NUEVA\s+)?(?:SUBESTACI[OÓ]N|SET\b)|Y\s+AMPLIACI", re.I)

def es_relevante(p):
    """Excluye reformas/modificaciones de lineas puras. Mantiene generacion,
    SETs y lineas que incluyen ampliacion/mejora de capacidad de una SET."""
    nm = (p.get('nombre') or '').strip()
    tec = p.get('tecnologia') or ''
    es_set = tec == 'SET' or RE_ESSET.search(nm)
    es_linea = (not es_set) and ((tec == 'LAT') or bool(RE_LINEA.search(nm)))
    return not (es_linea and not RE_AMPLIA.search(nm))

def main():
    pj_path, caps_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    pj = json.load(open(pj_path, encoding='utf-8'))
    caps = json.load(open(caps_path, encoding='utf-8'))
    idx = build_monitor_index(caps)
    names = list(idx.keys())
    # indices rapidos para la cosecha de texto
    import collections
    tok1 = collections.defaultdict(list)   # primer token -> nombres monitor
    for n_ in names:
        t = n_.split()[0] if n_.split() else ''
        if t: tok1[t].append(n_)
    strip_art_g = lambda s: ' '.join(w for w in s.split() if w not in ('LA','EL','LOS','LAS','DE','DEL'))
    art_idx = collections.defaultdict(list)
    for n_ in names:
        art_idx[strip_art_g(n_)].append(n_)

    def fast_link(nombre, kvs):
        '''exacto / sin articulos / prefijo-tokens, solo O(bucket).'''
        if nombre in idx:
            cands = idx[nombre]
            wk = [c for c in cands if c[1] in kvs]
            if wk: return max(wk, key=lambda c: c[1])[0], 'exacto'
            return max(cands, key=lambda c: c[1])[0], 'tension'
        na = strip_art_g(nombre)
        if na in art_idx:
            n_ = art_idx[na][0]
            cands = idx[n_]
            wk = [c for c in cands if c[1] in kvs]
            return max(wk or cands, key=lambda c: c[1])[0], 'exacto'
        t = nombre.split()[0] if nombre.split() else ''
        best = None
        for n_ in tok1.get(t, []):
            if len(n_) >= 5 and (nombre.startswith(n_) or n_.startswith(nombre)):
                if best is None or len(n_) > len(best): best = n_
        if best and kvs:
            cands = idx[best]
            wk = [c for c in cands if c[1] in kvs]
            if wk: return max(wk, key=lambda c: c[1])[0], 'prefijo'
        return None, None

    antes = len(pj['proyectos'])
    pj['proyectos'] = [p for p in pj['proyectos'] if es_relevante(p)]
    pj['total'] = len(pj['proyectos'])
    print(f"filtro lineas puras: {antes} -> {len(pj['proyectos'])} (-{antes-len(pj['proyectos'])})")

    stats = {'potencia': 0, 'promotor': 0, 'subestacion': 0,
             'exacto': 0, 'tension': 0, 'prefijo': 0, 'fuzzy': 0, 'sin_match': 0}
    for p in pj['proyectos']:
        for f in backfill(p):
            stats[f] += 1
        key, how = link_set(p, idx, names)
        fuente = 'subestacion' if key else None
        if not key:
            # cosechar menciones en titulos/observaciones (solo matchean SETs REE/DSO del Monitor)
            for nombre, kvtxt, score in harvest_candidatos(p):
                kvs2 = extract_kvs(kvtxt)
                if p.get('tension_kv'):
                    try: kvs2.add(float(p['tension_kv']))
                    except (TypeError, ValueError): pass
                k2, h2 = fast_link(norm_name(nombre), kvs2)
                if k2:
                    key, how, fuente = k2, h2, 'texto'
                    p.setdefault('set_conexion_detectada', 'SET ' + nombre)
                    break
        p['set_vinculada'] = key
        p['set_match'] = how
        p['set_fuente'] = fuente
        if how: stats[how] += 1
        elif p.get('subestacion'): stats['sin_match'] += 1

    json.dump(pj, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    n = len(pj['proyectos'])
    cov = lambda f: sum(1 for p in pj['proyectos'] if p.get(f))
    print(f"proyectos          : {n}")
    print(f"backfill potencia  : +{stats['potencia']} -> {cov('potencia_mw')} ({cov('potencia_mw')*100//n}%)")
    print(f"backfill promotor  : +{stats['promotor']} -> {cov('promotor')} ({cov('promotor')*100//n}%)")
    print(f"backfill subestac. : +{stats['subestacion']} -> {cov('subestacion')} ({cov('subestacion')*100//n}%)")
    print(f"SET vinculada      : {cov('set_vinculada')} ({cov('set_vinculada')*100//n}%)")
    print(f"  exacto={stats['exacto']} tension={stats['tension']} prefijo={stats['prefijo']} fuzzy={stats['fuzzy']} sin_match={stats['sin_match']}")
    tx = sum(1 for p in pj['proyectos'] if p.get('set_fuente') == 'texto')
    print(f"  desde texto (obs/titulos): {tx}")

if __name__ == '__main__':
    main()
