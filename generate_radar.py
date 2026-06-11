#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_radar.py — Radar de posicionamiento: score compuesto por SET
combinando 4 pilares de anticipacion de afloramientos.

  P1 VENTANA    MW de proyectos fallidos en ventana de afloramiento (0-6 meses
                desde el permiso adverso; secundaria hasta 18m con peso menor).
  P2 TRAMITE    Caida de "capacidad en tramite" de la SET en los ultimos 3 meses
                sin aumento equivalente de ocupada (liberacion en curso —
                indicador adelantado, se ve ANTES de que suba la disponible).
  P3 ESTANCADOS MW de proyectos en tramitacion sin ninguna publicacion nueva
                en >24 meses (alta probabilidad de caducidad).
  P4 HITOS RDL  MW con hito del RD-ley 23/2020 venciendo en <=6 meses sin la
                publicacion correspondiente. Fecha de acceso estimada por el
                salto de "ocupada" en la SET (o fecha_primera - 9m, conf. baja).

score = 0.35*P1 + 0.30*P2 + 0.20*P3 + 0.15*P4  (cada pilar normalizado a su P95)

Salida: radar_data.js (window.RADAR_DATA)
"""
import json, re
from pathlib import Path
from datetime import date, datetime, timedelta

BASE = Path(__file__).parent
HOY = date.today()
ADV = {'denegado','desistido','desfavorable','archivado','caducado','inadmitido'}
DEC = {'AAP','AAP_AAC','DIA','AAC'}
EN_CURSO = {'en_tramitacion','informacion_publica','favorable'}

def ym(f): return (int(f[:4]), int(f[4:6]))
def mdiff(a, b): return (b[0]-a[0])*12 + (b[1]-a[1])
def f2d(f):
    try: return date(int(f[:4]), int(f[4:6]), int(f[6:8]))
    except Exception: return None

def main():
    pj = json.load(open(BASE/'projects.json', encoding='utf-8'))
    hist = json.load(open(BASE/'sets_history.json', encoding='utf-8')); hist.pop('_v', None)

    # series por SET: tram (3), ocup (2)
    tram_s, ocup_s = {}, {}
    for k, snaps in hist.items():
        t, o = {}, {}
        for x in snaps:
            kk = (int(x[0][:4]), int(x[0][5:7]))
            if x[3] is not None: t[kk] = x[3]
            if x[2] is not None: o[kk] = x[2]
        if t: tram_s[k] = t
        if o: ocup_s[k] = o

    R = {}  # set -> dict de pilares
    def reg(k):
        return R.setdefault(k, {'mw_ventana':0.0,'mw_ventana_18m':0.0,'tram_drop_3m':0.0,
                                'mw_estancado':0.0,'mw_hitos_6m':0.0,
                                'n_fallidos':0,'n_estancados':0,'n_hitos':0,
                                'fallidos':[],'estancados':[],'hitos':[]})

    # ── P1 ventana + P3 estancados + P4 hitos ──
    for p in pj['proyectos']:
        key = p.get('set_vinculada')
        if not key: continue
        mw = p.get('potencia_mw') or p.get('mw_liberados') or 0
        nombre = p.get('nombre') or ''

        def _tipo_cap(tec):
            t = (tec or '').lower()
            if 'h2' in t or 'data center' in t or 'electroliz' in t: return 'dem'
            if 'bess' in t and '+' not in t: return 'ambos'
            if '+bess' in t or 'almacen' in t: return 'ambos'
            return 'gen'

        if p.get('es_fallido'):
            fs = [pub.get('fecha') for pub in (p.get('publicaciones') or [])
                  if pub.get('estado') in ADV and (pub.get('tipo_permiso') or '') in DEC]
            if not fs:
                fs = [pub.get('fecha') for pub in (p.get('publicaciones') or []) if pub.get('estado') in ADV]
            fa = max([f for f in fs if f], default=None)
            d = f2d(fa) if fa else None
            if d:
                dias = (HOY - d).days
                if 0 <= dias <= 180:
                    r = reg(key); r['mw_ventana'] += mw; r['n_fallidos'] += 1
                    tcap = _tipo_cap(p.get('tecnologia'))
                    if tcap in ('gen','ambos'): r['mw_ventana_gen'] = r.get('mw_ventana_gen',0) + mw
                    if tcap in ('dem','ambos'): r['mw_ventana_dem'] = r.get('mw_ventana_dem',0) + mw
                    r['fallidos'].append({'p': nombre[:48], 'mw': round(mw,1), 'dias': dias,
                                          'tec': p.get('tecnologia') or '', 'afecta': tcap})
                elif 180 < dias <= 540:
                    r = reg(key); r['mw_ventana_18m'] += mw
            continue

        if (p.get('estado_actual') or '') in EN_CURSO:
            fu = f2d(p.get('fecha_ultima') or '')
            fp = f2d(p.get('fecha_primera') or '')
            # P3 zombi
            if fu and (HOY - fu).days > 730 and mw:
                r = reg(key); r['mw_estancado'] += mw; r['n_estancados'] += 1
                r['estancados'].append({'p': nombre[:48], 'mw': round(mw,1), 'meses_sin_pub': (HOY-fu).days//30})
            # P4 hitos RDL: estimar fecha de acceso
            if fp and mw:
                acceso, conf = None, 'baja'
                o = ocup_s.get(key)
                if o:
                    fpy = ym(p['fecha_primera'])
                    keys = sorted(k2 for k2 in o if -36 <= mdiff(fpy, k2) <= 3)
                    for i in range(1, len(keys)):
                        dlt = o[keys[i]] - o[keys[i-1]]
                        if dlt >= 5 and 0.5 <= dlt/mw <= 2.0:
                            acceso = date(keys[i][0], keys[i][1], 15); conf = 'ocupada'
                            break
                if not acceso:
                    acceso = fp - timedelta(days=270)
                # hitos desde acceso: AAP 25m, AAC 28m, explotacion 60m
                tiene = {pub.get('tipo_permiso') for pub in (p.get('publicaciones') or [])
                         if pub.get('estado') in ('otorgado','favorable')}
                for meses, hito, falta in ((25,'AAP','AAP' not in tiene and 'AAP_AAC' not in tiene),
                                           (28,'AAC','AAC' not in tiene and 'AAP_AAC' not in tiene),
                                           (60,'Explotación', True)):
                    if not falta: continue
                    venc = acceso + timedelta(days=int(meses*30.44))
                    dias_a_venc = (venc - HOY).days
                    if 0 <= dias_a_venc <= 183:
                        r = reg(key); r['mw_hitos_6m'] += mw; r['n_hitos'] += 1
                        r['hitos'].append({'p': nombre[:48], 'mw': round(mw,1), 'hito': hito,
                                           'vence': venc.isoformat(), 'confianza': conf})
                        break

    # ── P2 caida de tramite (ultimos 3 meses con datos) ──
    for k, t in tram_s.items():
        keys = sorted(t)
        if len(keys) < 4: continue
        ult, ant = keys[-1], None
        for kk in reversed(keys):
            if mdiff(kk, ult) >= 3: ant = kk; break
        if not ant: continue
        drop = t[ant] - t[ult]
        if drop < 5: continue
        o = ocup_s.get(k, {})
        oc_inc = max(0, o.get(ult, 0) - o.get(ant, 0)) if (ult in o and ant in o) else 0
        neto = drop - oc_inc
        if neto >= 5:
            reg(k)['tram_drop_3m'] = round(neto, 1)

    # ── score compuesto ──
    def p95(vals):
        v = sorted(x for x in vals if x > 0)
        return v[int(0.95*(len(v)-1))] if v else 1
    n1 = p95([r['mw_ventana'] + 0.3*r['mw_ventana_18m'] for r in R.values()])
    n2 = p95([r['tram_drop_3m'] for r in R.values()])
    n3 = p95([r['mw_estancado'] for r in R.values()])
    n4 = p95([r['mw_hitos_6m'] for r in R.values()])
    out = []
    for k, r in R.items():
        s = (0.35*min(1, (r['mw_ventana']+0.3*r['mw_ventana_18m'])/n1)
             + 0.30*min(1, r['tram_drop_3m']/n2)
             + 0.20*min(1, r['mw_estancado']/n3)
             + 0.15*min(1, r['mw_hitos_6m']/n4))
        if s <= 0.02: continue
        out.append({'set': k, 'score': round(s*100),
                    'mw_ventana': round(r['mw_ventana']), 'mw_ventana_18m': round(r['mw_ventana_18m']),
                    'mw_ventana_gen': round(r.get('mw_ventana_gen',0)), 'mw_ventana_dem': round(r.get('mw_ventana_dem',0)),
                    'tram_drop_3m': r['tram_drop_3m'], 'mw_estancado': round(r['mw_estancado']),
                    'mw_hitos_6m': round(r['mw_hitos_6m']),
                    'n_fallidos': r['n_fallidos'], 'n_estancados': r['n_estancados'], 'n_hitos': r['n_hitos'],
                    'fallidos': r['fallidos'][:5], 'estancados': sorted(r['estancados'], key=lambda z:-z['mw'])[:5],
                    'hitos': r['hitos'][:5]})
    out.sort(key=lambda x: -x['score'])
    out = out[:200]

    data = {'generado': HOY.isoformat(),
            'pesos': {'ventana': 0.35, 'tramite': 0.30, 'estancados': 0.20, 'hitos': 0.15},
            'sets': out}
    Path(BASE/'radar_data.js').write_text('window.RADAR_DATA = ' + json.dumps(data, ensure_ascii=False) + ';',
                                          encoding='utf-8')
    print(f'SETs en radar: {len(out)}')
    for r in out[:10]:
        print(f"  {r['score']:3d}  {r['set'][:26]:26} vent={r['mw_ventana']:5d}  tram3m={r['tram_drop_3m']:7.1f}  estanc={r['mw_estancado']:5d}  hitos={r['mw_hitos_6m']:5d}")

if __name__ == '__main__':
    main()
