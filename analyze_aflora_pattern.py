#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_aflora_pattern.py — Patron empirico de afloramiento de capacidad
tras permiso desfavorable / caida de proyecto.

Metodologia:
  1. Proyectos fallidos (es_fallido) con SET de conexion vinculada al Monitor
     (set_vinculada) y fecha del permiso adverso decisivo (AAP/AAP_AAC/DIA).
  2. Serie mensual de capacidad disponible de esa SET (sets_history.json,
     cap_gen_disp con fallback cap_gen).
  3. Afloramiento confirmado: primera subida mensual >= 5 MW en los 24 meses
     posteriores cuya magnitud sea 25%-250% de los MW del proyecto caido.
  4. Baseline de control: % de SET-meses con subidas >=5 MW en toda la red
     (para distinguir patron real de coincidencia).

Salidas:
  references/aflora_pattern_cases.csv  — casos confirmados con lag
  stats por consola + bloque ADVERSE_LAG_STATS sugerido
"""
import json, csv, sys
from pathlib import Path
from collections import Counter

BASE = Path(__file__).parent
ADV = {'denegado','desistido','desfavorable','archivado','caducado','inadmitido'}
DEC = {'AAP','AAP_AAC','DIA','AAC'}
UMBRAL_MW = 5.0
RATIO_MIN, RATIO_MAX = 0.4, 2.0
VENTANA_MESES = 18

def fecha_adversa(p):
    fechas = [pub.get('fecha') for pub in (p.get('publicaciones') or [])
              if (pub.get('estado') in ADV) and ((pub.get('tipo_permiso') or '') in DEC)]
    if not fechas:
        fechas = [pub.get('fecha') for pub in (p.get('publicaciones') or []) if pub.get('estado') in ADV]
    return max([f for f in fechas if f], default=None)

def ym(f): return (int(f[:4]), int(f[4:6]))
def mdiff(a, b): return (b[0]-a[0])*12 + (b[1]-a[1])

def main():
    pj = json.load(open(BASE/'projects.json', encoding='utf-8'))
    hist = json.load(open(BASE/'sets_history.json', encoding='utf-8')); hist.pop('_v', None)

    series = {}
    for k, snaps in hist.items():
        s = {}
        for x in snaps:
            d = x[8] if x[8] is not None else x[1]
            if d is not None:
                s[(int(x[0][:4]), int(x[0][5:7]))] = d
        if len(s) >= 6:
            series[k] = s

    tot, up = 0, 0
    for s in series.values():
        keys = sorted(s)
        for i in range(1, len(keys)):
            if mdiff(keys[i-1], keys[i]) == 1:
                tot += 1
                if s[keys[i]] - s[keys[i-1]] >= UMBRAL_MW: up += 1
    baseline = up/tot if tot else 0

    casos, sin_obs, sin_evento = [], 0, 0
    for p in pj['proyectos']:
        if not p.get('es_fallido') or not p.get('set_vinculada'): continue
        key = p['set_vinculada']
        if key not in series: continue
        fa = fecha_adversa(p)
        if not fa: continue
        fa_ym = ym(fa)
        mw = p.get('potencia_mw') or p.get('mw_liberados')
        s = series[key]
        keys = sorted(k2 for k2 in s if 0 < mdiff(fa_ym, k2) <= VENTANA_MESES)
        if len(keys) < 2:
            sin_obs += 1; continue
        prev = max([k2 for k2 in s if mdiff(fa_ym, k2) <= 0], default=None)
        last = s[prev] if prev else s[keys[0]]
        found = None
        for k2 in keys:
            delta = s[k2] - last
            if delta >= UMBRAL_MW:
                ratio = (delta/mw) if mw else None
                if mw is None or RATIO_MIN <= ratio <= RATIO_MAX:
                    found = (mdiff(fa_ym, k2), delta, ratio); break
            last = s[k2]
        if found:
            casos.append({'proyecto': p['nombre'], 'proyecto_id': p['id'], 'set': key,
                          'fecha_adversa': fa, 'lag_meses': found[0],
                          'delta_mw': round(found[1],1), 'mw_proyecto': mw,
                          'ratio': round(found[2],2) if found[2] is not None else ''})
        else:
            sin_evento += 1

    out = BASE/'references'/'aflora_pattern_cases.csv'
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(casos[0].keys()) if casos else
                           ['proyecto','proyecto_id','set','fecha_adversa','lag_meses','delta_mw','mw_proyecto','ratio'],
                           delimiter=';')
        w.writeheader(); w.writerows(sorted(casos, key=lambda c: c['lag_meses']))

    lags = sorted(c['lag_meses'] for c in casos)
    n = len(lags)
    q = lambda p: lags[min(n-1, int(p*n))] if n else 0
    print(f'baseline subidas >={UMBRAL_MW}MW: {baseline*100:.1f}% de SET-meses')
    print(f'fallidos con SET y serie: {n + sin_evento + sin_obs} | confirmados: {n} | sin evento: {sin_evento} | sin observacion: {sin_obs}')
    if n:
        print(f'lag (meses): min={lags[0]} p25={q(0.25)} mediana={q(0.5)} p75={q(0.75)} max={lags[-1]}')
        print('distribucion:', dict(sorted(Counter(lags).items())))
        sem = Counter((l-1)//6 for l in lags)
        print('por semestre: S1=%d S2=%d S3=%d' % (sem.get(0,0), sem.get(1,0), sem.get(2,0)))
        print('\nBloque sugerido para adverse_forecast_data.js:')
        print(f'const ADVERSE_LAG_STATS = {{\n  n: {n}, p25: {q(0.25)*30}, mediana: {q(0.5)*30},\n  p75: {q(0.75)*30}, min: {lags[0]*30}, max: {lags[-1]*30}\n}};')
    print(f'\nCSV: {out}')

if __name__ == '__main__':
    main()
