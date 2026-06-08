"""
parse_ree.py
Extrae la capacidad disponible neta para MPE en red de transporte de REE desde
el Excel 'references/Mapas_Capacidad_AyC-REE.xlsx'.

Formula:
    disponible_neta = col_disponible_MPE_RdT - col_solicitada_MPE

Por defecto solo procesa hojas desde diciembre 2023 en adelante (--all-dates
para incluir todas las hojas donde las columnas estén disponibles).

Salida: references/ree_capacidad.csv
  fecha, distribuidora, provincia, municipio, subestacion, tension_kv, disponible_neta, ccaa

Uso:
  python parse_ree.py
  python parse_ree.py --all-dates
  python parse_ree.py --summary
"""
import re
import sys
import argparse
from pathlib import Path

try:
    import openpyxl
except ImportError:
    sys.exit("pip install openpyxl --break-system-packages")
try:
    import pandas as pd
except ImportError:
    sys.exit("pip install pandas --break-system-packages")

BASE = Path(__file__).parent
XLSX = BASE / "references" / "Mapas_Capacidad_AyC-REE.xlsx"
OUT  = BASE / "references" / "ree_capacidad.csv"

MESES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
}

_TENSION_RE = re.compile(r'\b(\d{2,4})\s*$')


def parse_sheet_date(name: str):
    m = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})', name.strip())
    if not m:
        return None
    day, mes, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    if mes not in MESES:
        return None
    return f'{year}-{MESES[mes]:02d}-{day:02d}'


def detect_columns(header_row: tuple):
    """
    Detecta índices de columna relevantes en la fila de cabecera.
    Devuelve dict {nombre, ccaa, disp, sol} o None si falta alguna esencial.
    """
    col_nombre = col_ccaa = col_disp = col_sol = None
    sol_candidates = []

    for j, v in enumerate(header_row):
        if not v:
            continue
        s = str(v).strip()
        sl = s.lower()

        # Nombre del nudo
        if col_nombre is None and ('nombre y tens' in sl):
            col_nombre = j

        # Comunidad Autónoma (primer match)
        if col_ccaa is None and ('comunidad aut' in sl):
            col_ccaa = j

        # Disponible MPE RdT
        # Formato A/B: "Capacidad de acceso disponible para MPE RdT\n[MW]"
        if col_disp is None and 'disponible para mpe rdt' in sl:
            col_disp = j
        # Formato C: header exacto "MPE RdT\n[MW]" — tomar el primero encontrado
        if col_disp is None and sl.replace('\n', ' ').strip() == 'mpe rdt\n[mw]'.replace('\n', ' ').strip():
            col_disp = j

        # Solicitada MPE
        if 'solicitad' in sl:
            if sl.endswith(' mpe'):          # "...pendiente resolver MPE" — total MPE
                col_sol = j
            else:
                sol_candidates.append(j)

    # Formato A: todos los "solicitada" tienen mismo texto → usar el último
    if col_sol is None and sol_candidates:
        col_sol = sol_candidates[-1]

    if col_nombre is None or col_disp is None or col_sol is None:
        return None

    return {'nombre': col_nombre, 'ccaa': col_ccaa, 'disp': col_disp, 'sol': col_sol}


def parse_tension(nombre: str):
    if not nombre:
        return None
    m = _TENSION_RE.search(str(nombre).strip())
    return int(m.group(1)) if m else None


def parse_nudo_nombre(nombre: str):
    if not nombre:
        return ''
    s = _TENSION_RE.sub('', str(nombre).strip()).strip()
    return s


def to_float(v):
    if v is None or str(v).strip() in ('', 'N/A', 'N/D', '-', 'NA'):
        return None
    try:
        return float(str(v).replace(',', '.'))
    except (ValueError, TypeError):
        return None


def process_sheet(ws, fecha: str, cols: dict):
    records = []
    for row in ws.iter_rows(min_row=5, values_only=True):
        nombre_raw = row[cols['nombre']] if cols['nombre'] < len(row) else None
        if not nombre_raw:
            continue
        nombre_raw = str(nombre_raw).strip()
        if not nombre_raw or nombre_raw.upper().startswith('NOMBRE') or nombre_raw.upper().startswith('TOTAL'):
            continue
        if nombre_raw in ('For Formula ROW',):
            continue

        disp_val = to_float(row[cols['disp']] if cols['disp'] < len(row) else None)
        if disp_val is None:
            continue

        sol_val = to_float(row[cols['sol']] if cols['sol'] < len(row) else None) or 0.0
        disponible_neta = disp_val - sol_val

        ccaa = ''
        if cols['ccaa'] is not None and cols['ccaa'] < len(row):
            ccaa = str(row[cols['ccaa']] or '').strip()

        tension = parse_tension(nombre_raw)
        subestacion = parse_nudo_nombre(nombre_raw)

        records.append({
            'fecha':           fecha,
            'distribuidora':   'REE',
            'provincia':       '',
            'municipio':       '',
            'subestacion':     subestacion or nombre_raw,
            'tension_kv':      tension,
            'disponible_neta': round(disponible_neta, 4),
            'ccaa':            ccaa,
        })
    return records


# ── main ──────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument('--all-dates', action='store_true',
                    help='Incluir todas las hojas disponibles (no solo desde dic-2023)')
parser.add_argument('--summary', action='store_true',
                    help='Solo estadísticas, no escribe CSV')
args = parser.parse_args()

MIN_DATE = '2023-12-01' if not args.all_dates else '0000-01-01'

if not XLSX.exists():
    sys.exit(f"No se encuentra {XLSX}")

print(f"Leyendo {XLSX.name} …")
wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)

all_records = []
skipped = []

for sname in wb.sheetnames:
    fecha = parse_sheet_date(sname)
    if not fecha:
        continue
    if fecha < MIN_DATE:
        skipped.append((sname, 'antes de ' + MIN_DATE))
        continue

    ws = wb[sname]
    header = list(ws.iter_rows(min_row=4, max_row=4, values_only=True))[0]
    cols = detect_columns(header)

    if cols is None:
        skipped.append((sname, 'columnas no detectadas'))
        continue

    records = process_sheet(ws, fecha, cols)
    all_records.extend(records)
    print(f"  {fecha}  ({sname!r:<22})  →  {len(records):>4} nudos  "
          f"[disp={cols['disp']}, sol={cols['sol']}]")

wb.close()

if skipped:
    print(f"\n  Omitidas ({len(skipped)}):")
    for s, r in skipped[:10]:
        print(f"    {s!r}: {r}")
    if len(skipped) > 10:
        print(f"    … y {len(skipped)-10} más")

if not all_records:
    sys.exit("\nNo se encontraron registros.")

df = pd.DataFrame(all_records)
df['fecha'] = pd.to_datetime(df['fecha'])
df = df.sort_values(['subestacion', 'tension_kv', 'fecha'])

print(f"\n--- RESUMEN ---")
print(f"Total registros  : {len(df):,}")
print(f"Snapshots        : {df['fecha'].nunique()} "
      f"({df['fecha'].min().date()} → {df['fecha'].max().date()})")
print(f"Nudos únicos     : {df['subestacion'].nunique():,}")
print(f"disp_neta (MW)   : min={df['disponible_neta'].min():.0f}  "
      f"max={df['disponible_neta'].max():.0f}  media={df['disponible_neta'].mean():.0f}")

if args.summary:
    sys.exit(0)

df['fecha'] = df['fecha'].dt.strftime('%Y-%m-%d')
df.to_csv(OUT, index=False, encoding='utf-8-sig')
print(f"Guardado en      : {OUT}")
