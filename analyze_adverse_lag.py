"""
analyze_adverse_lag.py
Analiza el tiempo transcurrido entre una publicación de permiso adverso
(AAP/AAP_AAC/DIA denegado/desistido) y la afloración de capacidad disponible
en la subestación correspondiente.

Fuentes de confirmación de afloramiento (en orden de prioridad):
  1. Historial DSO (dso_capacidad_historial.csv): disponible_neta > 0 MW
     tras la fecha adversa en la subestación matchada.
  2. Texto BOE (campo mw_liberados en publicaciones): la propia resolución
     de denegación/desistimiento menciona explícitamente MW liberados.
     Usado como fallback cuando el historial DSO no confirma aún.

Genera:
  references/adverse_lag_cases.csv   — casos históricos con lag medido
  references/adverse_active.csv      — proyectos activos sin lag aún

Uso:
  python analyze_adverse_lag.py [--min-score 0.4]
"""

import sys, json, re, argparse
from pathlib import Path
from datetime import datetime

try:
    import pandas as pd
    import numpy as np
except ImportError:
    sys.exit("pip install pandas numpy")

BASE = Path(__file__).parent
REF  = BASE / "references"

# ── Argumentos ───────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--min-score', type=float, default=0.40,
                    help='Jaccard mínimo para aceptar match de SET (default 0.40)')
args = parser.parse_args()

# ── Carga proyectos (ijson para resistir truncaciones parciales) ──────────────
try:
    import ijson as _ijson
    _projects = []
    with open(BASE / "projects.json", 'rb') as _f:
        try:
            for _p in _ijson.items(_f, 'proyectos.item'):
                _projects.append(_p)
        except Exception:
            pass  # truncación: usar lo que hay
    projects = _projects
    print(f"projects.json: {len(projects)} proyectos cargados (ijson, tolerante a truncaciones)")
except ImportError:
    with open(BASE / "projects.json", encoding='utf-8') as f:
        raw = json.load(f)
    projects = raw['proyectos'] if isinstance(raw, dict) and 'proyectos' in raw else raw
    print(f"projects.json: {len(projects)} proyectos cargados")

ADVERSE_ESTADOS = {'denegado','desistido','desistida','desfavorable','archivado','caducado'}
DECISIVE_TIPOS  = {'AAP_AAC','AAP','DIA'}

def build_adverse_cases(projects):
    cases = []
    for p in projects:
        all_pubs = p.get('publicaciones', [])

        adv_pubs = sorted(
            [pub for pub in all_pubs
             if pub.get('tipo_permiso') in DECISIVE_TIPOS
             and pub.get('estado') in ADVERSE_ESTADOS],
            key=lambda x: x.get('fecha', '')
        )
        if not adv_pubs:
            continue
        latest = adv_pubs[-1]

        # Publicaciones con confirmación textual de MW liberados (cualquier tipo/estado)
        pub_mw_confirmaciones = sorted(
            [{'fecha': pub['fecha'], 'mw': float(str(pub['mw_liberados']))}
             for pub in all_pubs
             if pub.get('mw_liberados') and float(str(pub.get('mw_liberados', 0) or 0)) > 0
             and pub.get('fecha', '') >= latest['fecha']],   # solo después del evento adverso
            key=lambda x: x['fecha']
        )

        cases.append({
            'proyecto_id':           p['id'],
            'proyecto_nombre':       p['nombre'],
            'promotor':              p.get('promotor', ''),
            'subestacion_raw':       (p.get('subestacion') or '').strip(),
            'tension_kv_prj':        p.get('tension_kv'),
            'provincia':             p.get('provincia', '') or '',
            'tecnologia':            p.get('tecnologia', '') or '',
            'mw_proyecto':           p.get('potencia_mw'),
            'fecha_adversa':         latest['fecha'],           # YYYYMMDD
            'tipo_adverso':          latest['tipo_permiso'],
            'estado_adverso':        latest['estado'],
            'boletin':               latest.get('boletin', ''),
            'n_pub_adversas':        len(adv_pubs),
            'pub_mw_confirmaciones': pub_mw_confirmaciones,   # [{fecha, mw}, ...]
        })
    return cases

# ── Normalización de nombres ──────────────────────────────────────────────────
def norm_set(s):
    s = str(s).upper().strip()
    s = re.sub(r'[ÀÁÂÃ]', 'A', s); s = re.sub(r'[ÈÉÊË]', 'E', s)
    s = re.sub(r'[ÌÍÎÏ]', 'I', s); s = re.sub(r'[ÒÓÔÕ]', 'O', s)
    s = re.sub(r'[ÙÚÛÜ]', 'U', s)
    s = re.sub(r'\b(SET|ST|SUB|SUBESTACION|SUBESTACIÓ|TRANSFORMADORA|PARQUE|PLANTA|'
               r'SOLAR|EOLICO|EÓLICO|FOTOVOLTAICA|INSTALACION)\b', '', s)
    s = re.sub(r'\d+\s*/\s*\d+\s*KV', '', s)
    s = re.sub(r'\d+\.?\d*\s*KV', '', s)
    s = re.sub(r'\(REE\)|\(ENDESA\)|\(UFD\)|\(IDE\)|\(EREDES\)', '', s)
    s = re.sub(r'[^A-Z0-9\s]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def tokens(s, min_len=3):
    return {t for t in norm_set(s).split() if len(t) >= min_len and not t.isdigit()}

# ── Carga historial de capacidad ──────────────────────────────────────────────
print("Cargando historial de capacidad…")
cap = pd.read_csv(REF / "dso_capacidad_historial.csv",
                  encoding='utf-8-sig', dtype=str)
cap['disponible_neta'] = pd.to_numeric(cap['disponible_neta'], errors='coerce')
cap['tension_kv']      = pd.to_numeric(cap['tension_kv'], errors='coerce')
cap['fecha']           = pd.to_datetime(cap['fecha'], errors='coerce')
cap['norm_sub']        = cap['subestacion'].apply(norm_set)

# Índice por nombre normalizado
cap_idx = {}
for ns, grp in cap.groupby('norm_sub'):
    cap_idx[ns] = grp.sort_values('fecha').reset_index(drop=True)

def best_match(raw_name, min_score):
    qt = tokens(raw_name)
    if not qt:
        return None, 0.0, None
    best_key, best_score, best_df = None, 0.0, None
    for key, df in cap_idx.items():
        qk = tokens(key)
        if not qk:
            continue
        inter = len(qt & qk)
        union = len(qt | qk)
        j = inter / union if union else 0
        if j > best_score:
            best_score, best_key, best_df = j, key, df
    if best_score >= min_score:
        return best_key, best_score, best_df
    return None, best_score, None

# ── Procesar casos ────────────────────────────────────────────────────────────
cases = build_adverse_cases(projects)
print(f"Casos adversos totales: {len(cases)} "
      f"({sum(1 for c in cases if c['subestacion_raw'])} con SET, "
      f"{sum(1 for c in cases if c['pub_mw_confirmaciones'])} con confirmación BOE texto)")

lag_cases    = []   # lag medido
active_cases = []   # aún sin afloración detectada
no_match     = []   # sin match de SET

cnt_dso       = 0   # confirmados por historial DSO
cnt_boe_texto = 0   # confirmados por texto BOE (fallback)
cnt_boe_noset = 0   # confirmados por texto BOE (sin SET)

for c in sorted(cases, key=lambda x: x['fecha_adversa']):
    pub_confs = c.pop('pub_mw_confirmaciones', [])  # extraer antes de copiar
    adv_dt    = pd.to_datetime(c['fecha_adversa'], format='%Y%m%d')

    # ── Caso sin subestación: solo texto BOE como fallback ────────────────────
    if not c['subestacion_raw']:
        if pub_confs:
            # Confirmación directa por texto BOE, sin historial DSO
            pc = pub_confs[0]
            pc_dt = pd.to_datetime(pc['fecha'], format='%Y%m%d')
            lag_days = int((pc_dt - adv_dt).days)
            row = {
                **c,
                'subestacion_match':   None,
                'match_score':         None,
                'distribuidora':       None,
                'provincia_cap':       c.get('provincia', ''),
                'capacidad_base_mw':   None,
                'lag_dias':            lag_days,
                'delta_mw':            round(pc['mw'], 1),
                'fecha_afloracion':    pc_dt.strftime('%Y-%m-%d'),
                'confirmacion_fuente': 'boe_texto',
            }
            lag_cases.append(row)
            cnt_boe_noset += 1
        else:
            no_match.append({**c, 'motivo_sin_match': 'sin_subestacion'})
        continue

    # ── Caso con subestación: intentar match en historial DSO ─────────────────
    key, score, df = best_match(c['subestacion_raw'], args.min_score)

    lag_days = delta_mw = lag_date = None
    dist = prov_cap = base_cap = None
    confirmacion_fuente = None

    if df is not None:
        post     = df[df['fecha'] > adv_dt].copy()
        pre      = df[df['fecha'] <= adv_dt].copy()
        base_cap = float(pre['disponible_neta'].iloc[-1]) if len(pre) else None
        dist     = df['distribuidora'].iloc[0]
        prov_cap = df['provincia'].iloc[0] if 'provincia' in df.columns else ''

        # Fuente primaria: historial DSO
        for _, r in post.iterrows():
            cap_val = float(r['disponible_neta'])
            if cap_val > 0:
                lag_days = int((r['fecha'] - adv_dt).days)
                delta_mw = round(cap_val, 1)
                lag_date = r['fecha'].strftime('%Y-%m-%d')
                confirmacion_fuente = 'historial_dso'
                cnt_dso += 1
                break

    # Fuente secundaria: texto BOE (si DSO no confirmó aún)
    if lag_days is None and pub_confs:
        pc    = pub_confs[0]
        pc_dt = pd.to_datetime(pc['fecha'], format='%Y%m%d')
        lag_days = int((pc_dt - adv_dt).days)
        delta_mw = round(pc['mw'], 1)
        lag_date = pc_dt.strftime('%Y-%m-%d')
        confirmacion_fuente = 'boe_texto'
        cnt_boe_texto += 1

    # Sin match en historial y sin confirmación textual → no_match
    if df is None and lag_days is None:
        no_match.append({**c,
                         'motivo_sin_match': f'score_bajo_{score:.2f}',
                         'best_score': score})
        continue

    row = {
        **c,
        'subestacion_match':   key,
        'match_score':         round(score, 3) if score else None,
        'distribuidora':       dist,
        'provincia_cap':       prov_cap or c.get('provincia', ''),
        'capacidad_base_mw':   round(base_cap, 1) if base_cap is not None else None,
        'lag_dias':            lag_days,
        'delta_mw':            delta_mw,
        'fecha_afloracion':    lag_date,
        'confirmacion_fuente': confirmacion_fuente,
    }

    if lag_days is not None:
        lag_cases.append(row)
    else:
        active_cases.append(row)

# ── Estadísticas de lag ───────────────────────────────────────────────────────
print(f"\n{'─'*60}")
print(f"CASOS CON LAG MEDIDO: {len(lag_cases)}")
print(f"  Por historial DSO  : {cnt_dso}")
print(f"  Por texto BOE (con SET): {cnt_boe_texto}")
print(f"  Por texto BOE (sin SET): {cnt_boe_noset}")
if lag_cases:
    lags = sorted(c['lag_dias'] for c in lag_cases if c['lag_dias'] is not None)
    if lags:
        print(f"  Lags (días): {lags}")
        print(f"  Mínimo  : {min(lags)} d")
        print(f"  Mediana : {int(np.median(lags))} d")
        print(f"  P25–P75 : {int(np.percentile(lags,25))}–{int(np.percentile(lags,75))} d")
        print(f"  Máximo  : {max(lags)} d")
    for c in lag_cases:
        fuente = c.get('confirmacion_fuente','?')[:3].upper()
        print(f"  [{fuente}] {c['proyecto_nombre'][:38]:38}  {c['fecha_adversa']}→{c.get('fecha_afloracion','?')}"
              f"  lag={c['lag_dias']}d  mw={c['delta_mw']}MW")

print(f"\nCASOS ACTIVOS (sin afloración aún): {len(active_cases)}")
for c in active_cases:
    print(f"  {c['proyecto_nombre'][:40]:40}  adv={c['fecha_adversa']}"
          f"  SET={c['subestacion_match']}")

print(f"\nSIN MATCH: {len(no_match)}")

# ── Guardar CSVs ──────────────────────────────────────────────────────────────
lag_cols = ['proyecto_id','proyecto_nombre','promotor','tecnologia','mw_proyecto',
            'subestacion_raw','subestacion_match','match_score','distribuidora',
            'provincia_cap','tension_kv_prj','fecha_adversa','tipo_adverso',
            'estado_adverso','boletin','capacidad_base_mw',
            'lag_dias','delta_mw','fecha_afloracion','confirmacion_fuente']

act_cols = ['proyecto_id','proyecto_nombre','promotor','tecnologia','mw_proyecto',
            'subestacion_raw','subestacion_match','match_score','distribuidora',
            'provincia_cap','tension_kv_prj','fecha_adversa','tipo_adverso',
            'estado_adverso','boletin','capacidad_base_mw']

if lag_cases:
    pd.DataFrame(lag_cases)[lag_cols].to_csv(REF / "adverse_lag_cases.csv",
                                              index=False, encoding='utf-8-sig')
    print(f"\nGuardado: adverse_lag_cases.csv ({len(lag_cases)} filas)")

if active_cases:
    pd.DataFrame(active_cases)[act_cols].to_csv(REF / "adverse_active.csv",
                                                  index=False, encoding='utf-8-sig')
    print(f"Guardado: adverse_active.csv ({len(active_cases)} filas)")
