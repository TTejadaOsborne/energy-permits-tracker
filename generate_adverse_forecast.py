"""
generate_adverse_forecast.py
Genera adverse_forecast.csv y adverse_forecast_data.js para la UI.

Lógica:
  - Para casos con lag medido: son la evidencia empírica (n pequeño pero real).
  - Para casos activos: estima ventana usando la distribución de lags observada.
  - Confianza = f(n_casos_base, score_match, antiguedad_decision)

Uso:
  python generate_adverse_forecast.py [--min-score 0.4]
"""

import sys, json, re, argparse, unicodedata
from pathlib import Path
from datetime import date, timedelta

try:
    import pandas as pd
    import numpy as np
except ImportError:
    sys.exit("pip install pandas numpy")

BASE = Path(__file__).parent
REF  = BASE / "references"

# ── Helpers para pre-computar sets_capacity_key ───────────────────────────────
_PREFIXES = ['SUBESTACION', 'SUBESTACIO', 'CENTRO DE SECCIONAMIENTO',
             'CENTRO SECCIONAMIENTO', 'STR', 'STS', 'CSEC', 'CT', 'SE',
             'PROMOTORES', 'PROMOTORE', 'NUEVO', 'NEW', 'NUDO',
             'LA', 'EL', 'LOS', 'LAS', 'DE', 'DEL', 'SET']

def _norm_cap_key(s):
    """Replica normSetName() de index.html — usa word boundaries para prefijos."""
    s = unicodedata.normalize('NFD', str(s).upper())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    # Eliminar prefijos solo en word boundaries (igual que JS \b)
    for p in _PREFIXES:
        s = re.sub(r'\b' + re.escape(p) + r'\b', ' ', s)
    s = re.sub(r'\d+[.,/]\d+\s*KV?', '', s)
    s = re.sub(r'\b\d+\s*KV?\b', '', s)
    s = re.sub(r'\([^)]+\)', '', s)
    s = re.sub(r'[^A-Z0-9 ]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def _load_cap_keys():
    p = BASE / "sets_capacity.json"
    if not p.exists():
        return {}
    with open(p, encoding='utf-8') as f:
        raw = json.load(f)
    # Construir índice normalizado → clave original
    idx = {}
    for key in raw.keys():
        nk = _norm_cap_key(key)
        for w in [t for t in nk.split() if len(t) >= 4]:
            idx.setdefault(w, []).append(key)
    return {'keys': list(raw.keys()), 'idx': idx}

_CAP_DATA = _load_cap_keys()
_CAP_KEYS = _CAP_DATA.get('keys', [])
_CAP_IDX  = _CAP_DATA.get('idx', {})
print(f"sets_capacity.json: {len(_CAP_KEYS)} claves cargadas para pre-matching")

def find_sets_cap_key(raw_name, tension_kv=None):
    """Devuelve la clave exacta de sets_capacity.json para un nombre de SET."""
    if not raw_name or not _CAP_KEYS:
        return None
    norm = _norm_cap_key(raw_name)
    words = [w for w in norm.split() if len(w) >= 4]
    if not words:
        return None
    # Contar votos usando índice normalizado
    votos = {}
    for w in words:
        for key in _CAP_IDX.get(w, []):
            votos[key] = votos.get(key, 0) + 1
    if not votos:
        return None
    max_v = max(votos.values())
    candidates = [k for k, v in votos.items() if v == max_v]
    # Desempate por tensión kV (busca número al final de la clave)
    if tension_kv and len(candidates) > 1:
        try:
            kv = float(tension_kv)
            def _kv_from_key(k):
                m = re.search(r'(\d+(?:\.\d+)?)\s*$', k)
                return float(m.group(1)) if m else 0
            candidates.sort(key=lambda k: abs(_kv_from_key(k) - kv))
        except (TypeError, ValueError):
            pass
    return candidates[0]

def get_tecnologia_tipo(tecnologia):
    """Clasifica la tecnología: 'gen', 'dem', 'alm', 'gen+alm'."""
    if not tecnologia:
        return 'gen'
    t = str(tecnologia).lower()
    is_gen = any(k in t for k in [
        'fotovoltaica', 'fv', 'eólica', 'eolica', 'termosolar',
        'hidráulica', 'hidrauli', 'biomasa', 'biogás', 'biogas',
        'cogeneración', 'cogeneracion', 'mini', 'solar', 'wind'
    ])
    is_alm = any(k in t for k in [
        'almacenamiento', 'batería', 'bateria', 'bess', 'bombeo', 'storage'
    ])
    is_dem = any(k in t for k in [
        'hidrógeno', 'hidrogeno', 'h2', 'data center', 'datacenter',
        'electrolizador', 'electrolyzer', 'demanda', 'cargador', 'ev ',
        'recarga', 'industria', 'autoconsumo'
    ])
    if is_gen and is_alm:
        return 'gen+alm'
    if is_alm:
        return 'alm'
    if is_dem:
        return 'dem'
    if is_gen:
        return 'gen'
    return 'gen'  # default: generación

parser = argparse.ArgumentParser()
parser.add_argument('--min-score', type=float, default=0.40)
args = parser.parse_args()

# ── Cargar casos ──────────────────────────────────────────────────────────────
lag_path = REF / "adverse_lag_cases.csv"
act_path = REF / "adverse_active.csv"

if not lag_path.exists() or not act_path.exists():
    import subprocess, sys
    r = subprocess.run([sys.executable, str(BASE / "analyze_adverse_lag.py"),
                        f'--min-score={args.min_score}'], capture_output=False)

lag_df = pd.read_csv(lag_path, encoding='utf-8-sig') if lag_path.exists() else pd.DataFrame()
act_df = pd.read_csv(act_path, encoding='utf-8-sig') if act_path.exists() else pd.DataFrame()

# ── Distribución de lag ───────────────────────────────────────────────────────
# Solo casos confirmados por historial DSO para la distribución temporal.
# Los casos boe_texto tienen lag=0 (misma resolución) y no reflejan cuándo
# los mapas del distribuidor actualizan la capacidad disponible.
if len(lag_df):
    dso_df = lag_df[lag_df.get('confirmacion_fuente', pd.Series(['historial_dso']*len(lag_df))) == 'historial_dso']              if 'confirmacion_fuente' in lag_df.columns else lag_df
    lags_dso = dso_df['lag_dias'].dropna().astype(float).tolist()
    lags_all = lag_df['lag_dias'].dropna().astype(float).tolist()
    # Usar DSO para timing, total para conteo de casos confirmados
    if lags_dso:
        lag_n      = len(lags_all)   # total confirmados (incluye BOE-texto)
        lag_median = int(np.median(lags_dso))
        lag_p25    = int(np.percentile(lags_dso, 25))
        lag_p75    = int(np.percentile(lags_dso, 75))
        lag_min    = int(min(lags_dso))
        lag_max    = int(max(lags_dso))
        lag_n_dso  = len(lags_dso)
        print(f"  Casos DSO: {lag_n_dso}  Casos BOE-texto: {lag_n - lag_n_dso}")
    else:
        # Solo hay BOE-texto — usar fallback regulatorio para timing
        lag_n      = len(lags_all)
        lag_n_dso  = 0
        lag_median, lag_p25, lag_p75, lag_min, lag_max = 150, 90, 210, 60, 365
        print("WARN: sin casos DSO; usando estimación regulatoria para timing (90–210d)")
else:
    lag_n, lag_n_dso, lag_median, lag_p25, lag_p75, lag_min, lag_max = 0, 0, 150, 90, 210, 60, 365
    print("WARN: sin casos medidos; usando estimación regulatoria (90–210d)")

print(f"Distribución de lag DSO: n={lag_n_dso if 'lag_n_dso' in dir() else 0}  P25={lag_p25}d  mediana={lag_median}d  P75={lag_p75}d  (total confirmados: {lag_n})")

# ── Construir forecast ────────────────────────────────────────────────────────
today = date.today()
rows  = []

def make_row(r, already_measured=False):
    _fa = str(r['fecha_adversa']).strip()
    if not (len(_fa)==8 and _fa.isdigit()):
        return None  # fecha inválida — fila ignorada
    adv_date = pd.to_datetime(_fa, format='%Y%m%d').date()
    days_since = (today - adv_date).days

    if already_measured:
        # Caso ya confirmado: afloración ya ocurrió
        afl_date   = pd.to_datetime(r['fecha_afloracion']).date() if pd.notna(r.get('fecha_afloracion')) else None
        estado     = 'CONFIRMADO'
        ventana_ini = str(afl_date) if afl_date else ''
        ventana_fin = str(afl_date) if afl_date else ''
        lag_real   = int(r['lag_dias']) if pd.notna(r.get('lag_dias')) else None
        # Confianza alta (caso real)
        confianza  = 0.95
        fuente_conf = r.get('confirmacion_fuente', 'historial_dso') if pd.notna(r.get('confirmacion_fuente','')) else 'historial_dso'
        if fuente_conf == 'boe_texto':
            descripcion = (f"Afloración confirmada por resolución BOE: {r.get('delta_mw','?')} MW liberados "
                           f"en {lag_real}d tras {r['tipo_adverso']} {r['estado_adverso']}.")
        else:
            descripcion = (f"Afloración confirmada (historial DSO): +{r.get('delta_mw','?')} MW "
                           f"en {lag_real}d tras {r['tipo_adverso']} {r['estado_adverso']}.")
    else:
        # Caso activo: estimación
        fuente_conf = None
        ini_date = adv_date + timedelta(days=lag_p25)
        fin_date = adv_date + timedelta(days=lag_p75)
        lag_real = None

        if today > fin_date:
            estado = 'SOBREPLAZO'   # ya superó P75, puede aflorar en cualquier momento
            ini_date = today
            fin_date = adv_date + timedelta(days=lag_max)
        elif today >= ini_date:
            estado = 'EN_VENTANA'
        else:
            dias_para_ini = (ini_date - today).days
            estado = f"en {dias_para_ini}d"

        ventana_ini = str(ini_date)
        ventana_fin = str(fin_date)

        # Confianza: penaliza si n_base pequeño y score bajo
        conf_base  = min(lag_n / 10, 1.0)          # máx 1.0 con 10+ casos medidos
        conf_score = float(r.get('match_score', 0.5))
        conf_time  = min(days_since / lag_median, 1.5) if lag_median > 0 else 1.0  # guard div/0
        confianza  = round(0.4*conf_base + 0.3*conf_score + 0.3*min(conf_time,1.0), 3)
        confianza  = max(0.15, min(0.85, confianza))  # clip

        n_dso = lag_n_dso if 'lag_n_dso' in dir() else lag_n
        descripcion = (f"Estimado: {lag_p25}–{lag_p75}d tras {r['tipo_adverso']} {r['estado_adverso']} "
                       f"(base historial DSO: {n_dso} caso{'s' if n_dso!=1 else ''}  ·  total confirmados: {lag_n}).")

    mw = r.get('mw_proyecto')

    # ── Probabilidad de afloramiento: escala 25/50/75/100 ──────────────────────
    # Criterio justificado en 4 niveles:
    #
    # 100 — CONFIRMADO por historial DSO: la capacidad ya apareció en los mapas
    #        del distribuidor tras la denegación. Evidencia directa y verificable.
    #
    #  75 — Alta probabilidad: proyecto en SOBREPLAZO (ya superó P75 sin aflorar)
    #        o CONFIRMADO por texto BOE (el propio BOE menciona los MW liberados).
    #        Evidencia fuerte pero DSO aún no ha actualizado sus mapas.
    #
    #  50 — Probabilidad media: proyecto EN VENTANA ESTIMADA (P25–P75 histórico)
    #        o SOBREPLAZO con match SET de calidad media-baja.
    #        El timing sugiere que debería aflorar pronto, pero sin confirmación.
    #
    #  25 — Probabilidad baja: proyecto fuera de ventana estimada (aún pronto)
    #        o match SET de baja calidad (< 0.6). Oportunidad potencial pero
    #        con menos evidencia de que la SET vaya a liberar capacidad.
    if already_measured:
        # Confirmado — distinguir fuente
        if fuente_conf == 'historial_dso':
            prob = 100   # observado directamente en mapas DSO
        else:
            prob = 75    # confirmado por texto BOE, DSO aún no actualizado
    else:
        base_cap_val = r.get('capacidad_base_mw')
        match_sc     = float(r.get('match_score') or 0.5)
        congestionada = base_cap_val is not None and float(str(base_cap_val) or 0) <= 0
        buen_match    = match_sc >= 0.60
        if estado == 'SOBREPLAZO':
            prob = 75 if buen_match else 50
        elif estado == 'EN_VENTANA':
            prob = 50
        else:
            # Fuera de ventana estimada (aún en espera)
            prob = 25

    _tech = r.get('tecnologia', '')
    _raw  = r.get('subestacion_raw', '') or r.get('subestacion_match', '')
    _kv   = r.get('tension_kv_prj')
    return {
        'proyecto_id':         r.get('proyecto_id',''),
        'proyecto_nombre':     r.get('proyecto_nombre',''),
        'promotor':            r.get('promotor',''),
        'tecnologia':          _tech,
        'tecnologia_tipo':     get_tecnologia_tipo(_tech),
        'mw_proyecto':         mw,
        'tension_kv':          _kv,
        'distribuidora':       r.get('distribuidora',''),
        'subestacion':         r.get('subestacion_match', r.get('subestacion_raw','')),
        'subestacion_raw':     _raw,
        'sets_capacity_key':   find_sets_cap_key(_raw, _kv),
        'provincia':           r.get('provincia_cap', r.get('provincia','')),
        'fecha_adversa':       str(adv_date),
        'tipo_adverso':        r.get('tipo_adverso',''),
        'estado_adverso':      r.get('estado_adverso',''),
        'boletin':             r.get('boletin',''),
        'lag_p25_dias':        lag_p25,
        'lag_mediana_dias':    lag_median,
        'lag_p75_dias':        lag_p75,
        'lag_real_dias':       lag_real,
        'ventana_inicio':      ventana_ini,
        'ventana_fin':         ventana_fin,
        'estado_ventana':      estado,
        'confianza':           confianza,
        'prob_afloramiento':   prob,
        'descripcion':         descripcion,
        'n_casos_empiricos':   lag_n,
        'confirmacion_fuente': fuente_conf if already_measured else None,
    }

# Casos confirmados
for _, r in lag_df.iterrows():
    row = make_row(r, already_measured=True)
    # Solo incluir si tiene SET identificada y fecha válida
    def _valid_sub(r): s=str(r.get('subestacion','')); return s and s.lower() not in ('nan','none','')
    if row and _valid_sub(row):
        rows.append(row)

# Casos activos
for _, r in act_df.iterrows():
    row = make_row(r, already_measured=False)
    if row and _valid_sub(row):
        rows.append(row)

# ── Deduplicar por subestación: un registro por SET ─────────────────────────
# Criterio: permiso desfavorable más reciente (fecha_adversa máxima) → caso más conservador
# MW: suma de todos los proyectos del SET para reflejar la capacidad total en juego
# Si hay algún CONFIRMADO en el SET, prevalece ese estado.

def dedup_by_set(rows):
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        sub = r.get('subestacion'); sub = str(sub).strip().upper() if sub and str(sub) not in ('', 'nan', 'None') else ''
        key = sub or r.get('proyecto_id', '')
        groups[key].append(r)

    deduped = []
    for key, grp in groups.items():
        # Calcular MW total del SET
        total_mw = sum(float(r['mw_proyecto']) for r in grp if r.get('mw_proyecto') not in (None, float('nan')))

        # Prioridad de estado: CONFIRMADO > EN_VENTANA > SOBREPLAZO > otros
        _est_prio = {'CONFIRMADO': 0, 'EN_VENTANA': 1, 'SOBREPLAZO': 2}
        best_estado = sorted(grp, key=lambda r: _est_prio.get(r['estado_ventana'], 3))[0]

        # Caso representativo: si hay confirmado usarlo, si no el de fecha_adversa más reciente
        if best_estado['estado_ventana'] == 'CONFIRMADO':
            rep = best_estado
        else:
            rep = max(grp, key=lambda r: r.get('fecha_adversa', ''))

        rep = dict(rep)  # copia para no mutar
        rep['mw_proyecto']   = round(total_mw, 2) if total_mw else rep.get('mw_proyecto')
        rep['n_proyectos_set'] = len(grp)
        deduped.append(rep)

    return deduped

rows = dedup_by_set(rows)

# Ordenar: EN_VENTANA primero, luego SOBREPLAZO, luego PENDIENTE/otros, CONFIRMADO al final; por fecha desc
priority = {'EN_VENTANA':0,'SOBREPLAZO':1,'CONFIRMADO':3}
rows.sort(key=lambda r: (
    priority.get(r['estado_ventana'], 2),
    r['ventana_inicio']
))

out_df = pd.DataFrame(rows)
out_path = REF / "adverse_forecast.csv"
out_df.to_csv(out_path, index=False, encoding='utf-8-sig')
print(f"\nGuardado: {out_path} ({len(out_df)} filas)")

# ── Resumen ───────────────────────────────────────────────────────────────────
print(f"\n{'─'*55}")
print(f"RESUMEN ADVERSE FORECAST — {today}")
print(f"{'─'*55}")
ec = out_df['estado_ventana'].value_counts()
for estado, n in ec.items():
    print(f"  {estado:15}: {n}")
print(f"{'─'*55}")
n_multi = int((out_df['n_proyectos_set'] > 1).sum()) if 'n_proyectos_set' in out_df.columns else 0
print(f"SETs monitorizadas       : {len(out_df)}  ({n_multi} con múltiples proyectos agrupados)")
print(f"MW totales en juego      : {out_df['mw_proyecto'].sum():.1f} MW  (acumulado por SET)")
print(f"Lag base empírica (días) : P25={lag_p25}  med={lag_median}  P75={lag_p75}  n={lag_n}")

# ── Generar adverse_forecast_