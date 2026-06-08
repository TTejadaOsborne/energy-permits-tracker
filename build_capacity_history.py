"""
build_capacity_history.py
Consolida las series históricas de capacidad disponible neta de todas las
distribuidoras (Endesa, iDE…) en un único CSV estandarizado:

  references/dso_capacidad_historial.csv

Columnas:
  fecha          YYYY-MM-DD del snapshot
  distribuidora  Endesa | iDE | …
  provincia
  municipio
  subestacion    nombre normalizado
  tension_kv
  disponible_neta  MW ya netos (Endesa: disponible-admitida; iDE: directo)

Uso:
  python build_capacity_history.py           # genera el CSV
  python build_capacity_history.py --summary # solo estadísticas

NOTA: requiere que parse_endesa.py y parse_ide.py ya hayan generado sus CSVs.
"""
import sys
import argparse
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("pip install pandas")

BASE = Path(__file__).parent
REF  = BASE / "references"
OUT  = REF / "dso_capacidad_historial.csv"

SOURCES = {
    "Endesa":   REF / "endesa_capacidad.csv",
    "iDE":      REF / "ide_capacidad.csv",
    "REE":      REF / "ree_capacidad.csv",
    "UFD":      REF / "ufd_capacidad.csv",
    "E-Redes":  REF / "eredes_capacidad.csv",   # histórico 2023-2025, carga única
    "Viesgo":   REF / "viesgo_capacidad.csv",   # histórico 2021-2025, absorbida por UFD
    "Monitor":  REF / "monitor_capacidad.csv",
}

def norm_set(s):
    """Normaliza nombre de subestación para comparación."""
    if not isinstance(s, str): return ''
    return s.upper().strip()

def load_source(dist, path):
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str)
    # Endesa usa disponible_neta como columna final
    # iDE también — schema ya unificado por parse_ide.py
    needed = ['fecha', 'subestacion', 'tension_kv', 'disponible_neta']
    if not all(c in df.columns for c in needed):
        print(f"  WARN {dist}: columnas faltantes en {path.name}")
        return None
    # Añadir distribuidora si no existe
    if 'distribuidora' not in df.columns:
        df.insert(1, 'distribuidora', dist)
    # Asegurar columnas opcionales
    if 'municipio' not in df.columns:
        df['municipio'] = ''
    if 'provincia' not in df.columns:
        df['provincia'] = ''
    df['disponible_neta'] = pd.to_numeric(df['disponible_neta'], errors='coerce').fillna(0)
    df['tension_kv']      = pd.to_numeric(df['tension_kv'],      errors='coerce')
    # Eliminar filas con tensión físicamente imposible (< 0 = coordenadas geográficas mal asignadas)
    before = len(df)
    df = df[df['tension_kv'].isna() | (df['tension_kv'] >= 0)]
    dropped = before - len(df)
    if dropped:
        print(f"    WARN {dist}: {dropped} filas con tension_kv negativa eliminadas")
    return df[['fecha','distribuidora','provincia','municipio',
               'subestacion','tension_kv','disponible_neta']]

parser = argparse.ArgumentParser()
parser.add_argument('--summary', action='store_true')
args = parser.parse_args()

frames = []
for dist, path in SOURCES.items():
    if not path.exists():
        print(f"  SKIP {dist}: {path.name} no encontrado (ejecuta parse_{dist.lower()}.py)")
        continue
    df = load_source(dist, path)
    if df is not None:
        frames.append(df)
        print(f"  {dist}: {len(df):,} registros ({df['fecha'].nunique()} snapshots, "
              f"{df['subestacion'].nunique()} SETs)")

if not frames:
    sys.exit("No hay datos. Ejecuta parse_endesa.py y parse_ide.py primero.")

combined = pd.concat(frames, ignore_index=True)
combined['fecha'] = pd.to_datetime(combined['fecha'], errors='coerce')
combined = combined.dropna(subset=['fecha']).sort_values(['distribuidora','subestacion','tension_kv','fecha'])

if args.summary:
    print(f"\n--- RESUMEN CONSOLIDADO ---")
    print(f"Total registros  : {len(combined):,}")
    print(f"Distribuidoras   : {combined['distribuidora'].unique().tolist()}")
    print(f"Rango fechas     : {combined['fecha'].min().date()} → {combined['fecha'].max().date()}")
    print(f"SETs únicos      : {combined['subestacion'].nunique():,}")
    print(f"\nSETs con ≥10 snapshots y mayor variabilidad (std disponible_neta):")
    grp = combined.groupby(['distribuidora','subestacion','tension_kv'])
    stats = grp['disponible_neta'].agg(['count','std','mean','max']).reset_index()
    stats = stats[stats['count'] >= 10].nlargest(15, 'std')
    print(stats.to_string(index=False))
    sys.exit(0)

combined['fecha'] = combined['fecha'].dt.strftime('%Y-%m-%d')
combined.to_csv(OUT, index=False, encoding='utf-8-sig')

print(f"\n--- RESUMEN ---")
print(f"Total registros  : {len(combined):,}")
print(f"Distribuidoras   : {combined['distribuidora'].nunique()}")
print(f"SETs únicos      : {combined['subestacion'].nunique():,}")
print(f"Guardado en      : {OUT}")
