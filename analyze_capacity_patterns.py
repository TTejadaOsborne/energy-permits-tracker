"""
analyze_capacity_patterns.py
Detecta eventos de liberación de capacidad disponible neta por subestación,
identifica patrones temporales y los cruza con publicaciones de permisos
adversos en projects.json.

Salida:
  references/capacity_events.csv       — eventos Δ disponible_neta por SET
  references/capacity_patterns.csv     — SETs con patrón estacional (mes/trimestre)
  references/capacity_set_projects.csv — cruce SET ↔ proyectos con permiso adverso

Uso:
  python analyze_capacity_patterns.py
  python analyze_capacity_patterns.py --min-delta 5 --min-events 3
"""
import json
import sys
import re
import argparse
from pathlib import Path
from collections import defaultdict

try:
    import pandas as pd
    import numpy as np
except ImportError:
    sys.exit("pip install pandas numpy --break-system-packages")

BASE = Path(__file__).parent
REF  = BASE / "references"
HIST = REF / "dso_capacidad_historial.csv"
PROJ = BASE / "projects.json"

# ── args ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--min-delta',  type=float, default=5.0,
                    help='MW mínimos de incremento para considerarlo evento (default: 5)')
parser.add_argument('--min-events', type=int,   default=2,
                    help='Mínimo de eventos para incluir un SET en patrones (default: 2)')
parser.add_argument('--top',        type=int,   default=30,
                    help='Número de SETs a mostrar en el resumen (default: 30)')
args = parser.parse_args()

# ── 1. Cargar histórico ───────────────────────────────────────────────────────
if not HIST.exists():
    sys.exit(f"No se encuentra {HIST}. Ejecuta build_capacity_history.py primero.")

df = pd.read_csv(HIST, encoding='utf-8-sig', dtype={'tension_kv': str})
df['fecha'] = pd.to_datetime(df['fecha'])
df['disponible_neta'] = pd.to_numeric(df['disponible_neta'], errors='coerce').fillna(0)
df['tension_kv'] = pd.to_numeric(df['tension_kv'], errors='coerce')
df['set_id'] = df['distribuidora'] + '|' + df['subestacion'] + '|' + df['tension_kv'].astype(str)

print(f"Histórico cargado: {len(df):,} registros, {df['set_id'].nunique():,} SETs")
print(f"Distribuidoras: {df['distribuidora'].unique().tolist()}")
print(f"Rango: {df['fecha'].min().date()} → {df['fecha'].max().date()}\n")

# ── 2. Calcular eventos de liberación (Δ disponible_neta > threshold) ─────────
df_sorted = df.sort_values(['set_id', 'fecha'])
df_sorted['prev_disp'] = df_sorted.groupby('set_id')['disponible_neta'].shift(1)
df_sorted['delta']     = df_sorted['disponible_neta'] - df_sorted['prev_disp']

events = df_sorted[
    (df_sorted['delta'] >= args.min_delta) &
    df_sorted['prev_disp'].notna()
].copy()

events['mes']      = events['fecha'].dt.month
events['trimestre'] = events['fecha'].dt.quarter
events['año']      = events['fecha'].dt.year

print(f"Eventos de liberación detectados (Δ ≥ {args.min_delta} MW): {len(events):,}")
print(f"SETs con al menos 1 evento: {events['set_id'].nunique():,}\n")

# Guardar eventos
events_out = events[[
    'fecha','distribuidora','provincia','subestacion','tension_kv',
    'disponible_neta','prev_disp','delta','mes','trimestre','año'
]].copy()
events_out['fecha'] = events_out['fecha'].dt.strftime('%Y-%m-%d')
events_out.to_csv(REF / 'capacity_events.csv', index=False, encoding='utf-8-sig')
print(f"  → Guardado: references/capacity_events.csv")

# ── 3. Detectar patrones estacionales por SET ──────────────────────────────────
set_events = events.groupby('set_id').filter(lambda x: len(x) >= args.min_events)

if set_events.empty:
    print("No hay suficientes eventos para análisis de patrones.")
else:
    patterns = []
    for set_id, grp in set_events.groupby('set_id'):
        dist, sub, tension = set_id.split('|', 2)
        prov = grp['provincia'].iloc[0] if 'provincia' in grp.columns else ''
        n_events = len(grp)

        # Mes más frecuente
        mes_counts = grp['mes'].value_counts()
        top_mes    = int(mes_counts.index[0])
        top_mes_pct = float(mes_counts.iloc[0]) / n_events * 100

        # Trimestre más frecuente
        tri_counts  = grp['trimestre'].value_counts()
        top_tri     = int(tri_counts.index[0])
        top_tri_pct = float(tri_counts.iloc[0]) / n_events * 100

        # Media y max de delta
        avg_delta = float(grp['delta'].mean())
        max_delta = float(grp['delta'].max())

        # ¿Patrón claro? (≥50% eventos en el mismo trimestre)
        patron_claro = top_tri_pct >= 50.0

        patterns.append({
            'distribuidora': dist,
            'subestacion':   sub,
            'tension_kv':    tension,
            'provincia':     prov,
            'n_eventos':     n_events,
            'mes_top':       top_mes,
            'mes_top_pct':   round(top_mes_pct, 1),
            'trimestre_top': top_tri,
            'tri_top_pct':   round(top_tri_pct, 1),
            'avg_delta_mw':  round(avg_delta, 1),
            'max_delta_mw':  round(max_delta, 1),
            'patron_claro':  patron_claro,
            'fechas_eventos': '|'.join(grp['fecha'].dt.strftime('%Y-%m-%d').tolist()),
        })

    pat_df = pd.DataFrame(patterns).sort_values(
        ['patron_claro', 'n_eventos', 'avg_delta_mw'], ascending=[False, False, False]
    )
    pat_df.to_csv(REF / 'capacity_patterns.csv', index=False, encoding='utf-8-sig')
    print(f"  → Guardado: references/capacity_patterns.csv  ({len(pat_df):,} SETs)\n")

    n_patron = pat_df['patron_claro'].sum()
    print(f"SETs con patrón claro (≥50% eventos en mismo trimestre): {n_patron}")
    print(f"\nTop {min(args.top, len(pat_df))} SETs por frecuencia de liberación:")
    MESES_ES = {1:'Ene',2:'Feb',3:'Mar',4:'Abr',5:'May',6:'Jun',
                7:'Jul',8:'Ago',9:'Sep',10:'Oct',11:'Nov',12:'Dic'}
    for _, row in pat_df.head(args.top).iterrows():
        patron_str = f"T{row['trimestre_top']}({row['tri_top_pct']:.0f}%)" if row['patron_claro'] else f"T{row['trimestre_top']}({row['tri_top_pct']:.0f}%)*"
        print(f"  [{row['distribuidora']:6}] {row['subestacion']:35} {row['tension_kv']:>6}kV "
              f"  {row['n_eventos']:2}ev  Δavg={row['avg_delta_mw']:6.1f}MW  {patron_str}")

# ── 4. Cruce con proyectos (projects.json) ────────────────────────────────────
if not PROJ.exists():
    print("\nNo se encuentra projects.json — omitiendo cruce con proyectos.")
    sys.exit(0)

with open(PROJ, encoding='utf-8') as f:
    raw = json.load(f)
    projects = raw["proyectos"] if isinstance(raw, dict) and "proyectos" in raw else raw

print(f"\n{'='*60}")
print(f"Cruce con proyectos ({len(projects)} proyectos en projects.json)")

def norm(s):
    if not s: return ''
    s = str(s).upper().strip()
    s = re.sub(r'\bS\.?E\.?\b|\bSUBESTACION\b|\bSUBESTACIÓN\b', '', s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def tokens(s, min_len=3):
    """Tokens de texto puro — excluye números (tensión se trata por separado)."""
    return {t for t in norm(s).split() if len(t) >= min_len and not t.isdigit()}

# Build project → subestacion index
proj_sub_idx = defaultdict(list)  # subestacion_token_set → [project_ids]
for p in projects:
    sub_raw = p.get('subestacion') or ''
    if not sub_raw:
        continue
    toks = tokens(sub_raw)
    if toks:
        proj_sub_idx[frozenset(toks)].append(p['id'])

# Index all project subestaciones for fuzzy match
proj_subs = [(p['id'], p.get('subestacion',''), tokens(p.get('subestacion','')),
              p.get('estado_actual',''), p.get('ultimo_tipo_permiso',''),
              p.get('promotor',''), p.get('potencia_mw',''))
             for p in projects if p.get('subestacion')]

# For each event SET, find matching projects
if not set_events.empty:
    cross_records = []
    for set_id, grp in set_events.groupby('set_id'):
        dist, sub, tension = set_id.split('|', 2)
        sub_toks = tokens(sub)
        if not sub_toks:
            continue

        matches = []
        for pid, psub, ptoks, estado, tipo, promotor, potencia in proj_subs:
            if not ptoks:
                continue
            # Jaccard similarity
            inter = len(sub_toks & ptoks)
            union = len(sub_toks | ptoks)
            jac   = inter / union if union > 0 else 0
            # Requiere Jaccard ≥0.6 Y que ambos lados tengan ≥2 tokens no-numéricos
            if jac >= 0.6 and len(sub_toks) >= 2 and len(ptoks) >= 2:
                matches.append((pid, psub, jac, estado, tipo, promotor, potencia))

        if not matches:
            continue

        matches.sort(key=lambda x: -x[2])
        event_dates = '|'.join(grp['fecha'].dt.strftime('%Y-%m-%d').tolist())
        n_events_set = len(grp)
        avg_delta = float(grp['delta'].mean())

        for pid, psub, jac, estado, tipo, promotor, potencia in matches[:5]:
            cross_records.append({
                'distribuidora': dist,
                'subestacion_hist': sub,
                'tension_kv': tension,
                'n_eventos': n_events_set,
                'avg_delta_mw': round(avg_delta, 1),
                'event_dates': event_dates,
                'project_id': pid,
                'subestacion_project': psub,
                'jaccard': round(jac, 3),
                'estado_actual': estado,
                'tipo_permiso': tipo,
                'promotor': promotor,
                'potencia_mw': potencia,
            })

    if cross_records:
        cross_df = pd.DataFrame(cross_records)
        cross_df.to_csv(REF / 'capacity_set_projects.csv', index=False, encoding='utf-8-sig')
        print(f"  → Guardado: references/capacity_set_projects.csv  ({len(cross_df):,} matches)")
        print(f"  SETs con proyectos coincidentes: {cross_df['subestacion_hist'].nunique()}")
        print(f"  Proyectos únicos implicados:     {cross_df['project_id'].nunique()}")

        # Mostrar top matches con permiso adverso activo
        adverse = cross_df[cross_df['estado_actual'].str.contains('desfavorable|denegad|inadmitido', case=False, na=False)]
        if not adverse.empty:
            print(f"\n  SETs con proyectos en estado adverso ({len(adverse)} matches):")
            for _, r in adverse.head(20).iterrows():
                print(f"    [{r['distribuidora']:6}] {r['subestacion_hist']:30} → {r['project_id']} "
                      f"({r['estado_actual'][:30]}) jac={r['jaccard']:.2f}")
    else:
        print("  No se encontraron coincidencias SET ↔ proyectos.")

print("\nAnálisis completado.")
