"""
generate_capacity_forecast.py
Genera ventanas de predicción de liberación de capacidad por SET a partir
de los patrones detectados en capacity_patterns.csv.

Para cada SET con patrón claro (tri_top_pct >= 50%):
  - Calcula la próxima ventana de liberación esperada
  - Estima MW esperados (avg_delta + intervalo de confianza)
  - Cruza con proyectos adversos en projects.json

Salida: references/capacity_forecast.csv

Uso:
  python generate_capacity_forecast.py
  python generate_capacity_forecast.py --min-confidence 0.5
  python generate_capacity_forecast.py --horizon-months 12
"""
import json, sys, re, argparse
from pathlib import Path
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

try:
    import pandas as pd
    import numpy as np
except ImportError:
    sys.exit("pip install pandas numpy python-dateutil --break-system-packages")

BASE = Path(__file__).parent
REF  = BASE / "references"

parser = argparse.ArgumentParser()
parser.add_argument('--min-confidence', type=float, default=0.3,
                    help='Confianza mínima para incluir un SET (0-1, default: 0.3)')
parser.add_argument('--horizon-months', type=int, default=18,
                    help='Meses hacia adelante a incluir (default: 18)')
parser.add_argument('--min-delta',      type=float, default=5.0,
                    help='MW mínimos para mostrar en el forecast (default: 5)')
args = parser.parse_args()

TODAY = date.today()

# ── Cargar datos ──────────────────────────────────────────────────────────────
pat  = pd.read_csv(REF / 'capacity_patterns.csv',  encoding='utf-8-sig')
evts = pd.read_csv(REF / 'capacity_events.csv',    encoding='utf-8-sig')
evts['fecha'] = pd.to_datetime(evts['fecha'])

# Último evento y años cubiertos por SET
ev_stats = evts.groupby(['distribuidora','subestacion','tension_kv']).agg(
    last_event =('fecha','max'),
    first_event=('fecha','min'),
    años_distintos=('fecha', lambda x: x.dt.year.nunique()),
).reset_index()

pat = pat.merge(ev_stats, on=['distribuidora','subestacion','tension_kv'], how='left')
claros = pat[pat['patron_claro'] == True].copy()

# ── Calcular ventana de predicción ────────────────────────────────────────────
TRI_MONTHS = {1: (1, 3), 2: (4, 6), 3: (7, 9), 4: (10, 12)}

def next_window(trimestre, last_event_date, today):
    """
    Devuelve (inicio, fin) del próximo período del trimestre dado
    que sea después de today y del último evento.
    Avanza de año en año hasta encontrar una ventana futura.
    """
    m_ini, m_fin = TRI_MONTHS[trimestre]
    # Referencia: el año del último evento o el actual, lo que sea mayor
    ref_year = max(last_event_date.year, today.year)

    for y in range(ref_year, ref_year + 3):
        ini = date(y, m_ini, 1)
        # Último día del mes fin
        if m_fin == 12:
            fin = date(y, 12, 31)
        else:
            fin = date(y, m_fin + 1, 1) - timedelta(days=1)

        # Aceptar ventanas que: empiecen en el futuro O estén actualmente en curso
        if fin >= today:
            return ini, fin
    return None, None

def confianza(n_eventos, tri_pct, años_distintos):
    """
    Score 0-1 combinando:
    - Concentración trimestral (tri_pct / 100)
    - Número de eventos (log-normalizado, satura en 10)
    - Años distintos con eventos (consistencia interanual)
    """
    c_concentracion = tri_pct / 100.0
    c_frecuencia    = min(n_eventos / 10.0, 1.0)
    c_interanual    = min((años_distintos or 1) / 3.0, 1.0)
    return round(0.4 * c_concentracion + 0.3 * c_frecuencia + 0.3 * c_interanual, 3)

HORIZON_END = TODAY + relativedelta(months=args.horizon_months)

rows_out = []
for _, r in claros.iterrows():
    if r['avg_delta_mw'] < args.min_delta:
        continue

    last_ev = pd.to_datetime(r['last_event']).date() if pd.notna(r['last_event']) else TODAY
    ini, fin = next_window(int(r['trimestre_top']), last_ev, TODAY)
    if ini is None or ini > HORIZON_END:
        continue

    conf = confianza(r['n_eventos'], r['tri_top_pct'], r.get('años_distintos', 1))
    if conf < args.min_confidence:
        continue

    # Estado de la ventana
    if ini <= TODAY <= fin:
        estado_ventana = 'EN_CURSO'
    elif ini > TODAY:
        dias_restantes = (ini - TODAY).days
        estado_ventana = f'en {dias_restantes}d'
    else:
        estado_ventana = 'RECIENTE'

    rows_out.append({
        'distribuidora':     r['distribuidora'],
        'subestacion':       r['subestacion'],
        'tension_kv':        r['tension_kv'],
        'provincia':         r.get('provincia', ''),
        'n_eventos_hist':    int(r['n_eventos']),
        'años_distintos':    int(r.get('años_distintos', 1)),
        'trimestre_patron':  int(r['trimestre_top']),
        'concentracion_pct': r['tri_top_pct'],
        'avg_delta_mw':      r['avg_delta_mw'],
        'max_delta_mw':      r['max_delta_mw'],
        'ultimo_evento':     str(last_ev),
        'ventana_inicio':    str(ini),
        'ventana_fin':       str(fin),
        'estado_ventana':    estado_ventana,
        'confianza':         conf,
        'fechas_historicas': r.get('fechas_eventos', ''),
    })

df_out = pd.DataFrame(rows_out)
if df_out.empty:
    sys.exit("No se generaron predicciones con los filtros actuales.")

df_out = df_out.sort_values(['confianza', 'avg_delta_mw'], ascending=[False, False])

# ── Cruce con proyectos ───────────────────────────────────────────────────────
proj_path = BASE / 'projects.json'
proj_matches = {}

if proj_path.exists():
    with open(proj_path, encoding='utf-8') as f:
        raw = json.load(f)
    projects = raw['proyectos'] if isinstance(raw, dict) and 'proyectos' in raw else raw

    def norm(s):
        if not s: return ''
        s = str(s).upper().strip()
        s = re.sub(r'\bS\.?E\.?\b|\bSUBESTACION\b|\bSUBESTACIÓN\b|\bSET\b', '', s)
        s = re.sub(r'[^A-Z0-9 ]', ' ', s)
        return re.sub(r'\s+', ' ', s).strip()

    def tokens(s):
        return {t for t in norm(s).split() if len(t) >= 3 and not t.isdigit()}

    for p in projects:
        psub = p.get('subestacion') or ''
        ptoks = tokens(psub)
        if len(ptoks) < 2:
            continue
        for _, r in df_out.iterrows():
            stoks = tokens(r['subestacion'])
            if len(stoks) < 2:
                continue
            inter = len(stoks & ptoks)
            union = len(stoks | ptoks)
            jac = inter / union if union > 0 else 0
            if jac >= 0.6:
                key = (r['distribuidora'], r['subestacion'], r['tension_kv'])
                if key not in proj_matches:
                    proj_matches[key] = []
                proj_matches[key].append({
                    'id': p['id'],
                    'estado': p.get('estado_actual',''),
                    'tipo': p.get('ultimo_tipo_permiso',''),
                    'potencia': p.get('potencia_mw',''),
                    'promotor': p.get('promotor',''),
                })

    # Añadir info de proyectos al forecast
    df_out['proyectos_ids']    = df_out.apply(
        lambda r: '|'.join(m['id'] for m in proj_matches.get((r['distribuidora'],r['subestacion'],r['tension_kv']),[]))
        , axis=1)
    df_out['proyectos_estados'] = df_out.apply(
        lambda r: '|'.join(m['estado'] for m in proj_matches.get((r['distribuidora'],r['subestacion'],r['tension_kv']),[]))
        , axis=1)

# ── Guardar ───────────────────────────────────────────────────────────────────
df_out.to_csv(REF / 'capacity_forecast.csv', index=False, encoding='utf-8-sig')

# ── Resumen en consola ────────────────────────────────────────────────────────
en_curso = df_out[df_out['estado_ventana'] == 'EN_CURSO']
proximos = df_out[df_out['estado_ventana'].str.startswith('en ')]
con_proyectos = df_out[df_out['proyectos_ids'] != '']

print(f"{'='*68}")
print(f" FORECAST DE LIBERACIÓN DE CAPACIDAD  —  generado {TODAY}")
print(f"{'='*68}")
print(f" Horizonte: {TODAY} → {HORIZON_END}  |  Confianza mín: {args.min_confidence}")
print(f" SETs con predicción                : {len(df_out):,}")
print(f" Ventanas EN CURSO ahora (T{TODAY.month//4+1})      : {len(en_curso):,}")
print(f" Ventanas próximas (dentro horizonte): {len(proximos):,}")
print(f" SETs con proyectos cruzados         : {len(con_proyectos):,}")
print()

TRI_LABEL = {1:'T1 Ene-Mar', 2:'T2 Abr-Jun', 3:'T3 Jul-Sep', 4:'T4 Oct-Dic'}

# Ventanas EN CURSO
if not en_curso.empty:
    print(f"── VENTANAS EN CURSO (T2 Abr-Jun 2026) {'─'*30}")
    for _, r in en_curso.head(20).iterrows():
        pid = r['proyectos_ids']; proj_str = ('  [' + pid + ']') if pid else ''
        print(f"  [{r['distribuidora']:7}] {r['subestacion']:35} {r['tension_kv']:>6}kV  "
              f"Δavg={r['avg_delta_mw']:6.0f}MW  conf={r['confianza']:.2f}{proj_str}")

# Próximas por trimestre
print()
for tri in [3, 4, 1]:
    sub = df_out[df_out['trimestre_patron'] == tri].head(15)
    if sub.empty: continue
    sample = sub.iloc[0]
    label  = TRI_LABEL[tri]
    ini_y  = pd.to_datetime(sample['ventana_inicio']).year
    print(f"── PRÓXIMAS  {label} {ini_y}  {'─'*35}")
    for _, r in sub.iterrows():
        pid = r['proyectos_ids']; proj_str = ('  [' + pid + ']') if pid else ''
        print(f"  [{r['distribuidora']:7}] {r['subestacion']:35} {r['tension_kv']:>6}kV  "
              f"Δavg={r['avg_delta_mw']:6.0f}MW  conf={r['confianza']:.2f}  {r['estado_ventana']}{proj_str}")
    print()

print(f"Guardado en: references/capacity_forecast.csv  ({len(df_out)} SETs)")
