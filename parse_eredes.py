"""
parse_eredes.py
Extrae series temporales de capacidad de acceso de generación de
E-Redes Distribución Eléctrica (Electra del Llobregat) desde el Excel
'references/Mapas_Capacidad_AyC-EREDES.xlsx'.

Estructura del Excel (consistente en todas las hojas):
  Fila 1 : Nombre empresa
  Fila 2 : Etiqueta sección "Coordenadas UTM H30"
  Fila 3 : Cabecera → PROVINCIA | X | Y | NUDO AFECCIÓN RdT | SUBESTACIÓN |
                        TENSIÓN (kV) | POSICIÓN | CONCATENATE |
                        CAPACIDAD OCUPADA | EÓLICA | SOLAR | OTRAS |
                        CAPACIDAD DISPONIBLE (MW)
  Fila 4+: Datos

  cols (0-indexed): 0=PROVINCIA, 4=SUBESTACIÓN, 5=TENSIÓN, 12=DISPONIBLE

Salida: references/eredes_capacidad.csv
  fecha, distribuidora, provincia, municipio, subestacion, tension_kv, disponible_neta

Uso:
  python parse_eredes.py
  python parse_eredes.py --summary
"""
import re, sys, argparse
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("pip install pandas --break-system-packages")
try:
    import openpyxl
except ImportError:
    sys.exit("pip install openpyxl --break-system-packages")

BASE = Path(__file__).parent
SRC  = BASE / "references" / "Mapas_Capacidad_AyC-EREDES.xlsx"
OUT  = BASE / "references" / "eredes_capacidad.csv"

MESES_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12
}
MAX_MW = 5000.0
SKIP_PAT = re.compile(r'^(resumen|notas|base)', re.IGNORECASE)

def safe_float(val):
    if pd.isna(val): return None
    try:
        return float(str(val).replace(',', '.').strip())
    except (ValueError, TypeError):
        return None

def parse_sheet_date(name):
    """'27 septiembre 2023' → '2023-09-27'"""
    parts = name.strip().split()
    if len(parts) < 3:
        return None
    try:
        day  = int(parts[0])
        mes  = MESES_ES.get(parts[1].lower().rstrip('.'))
        year = int(parts[2])
        if not mes:
            return None
        return f"{year}-{mes:02d}-{day:02d}"
    except (ValueError, IndexError):
        return None

def detect_layout(df):
    """
    Busca dinámicamente la fila de cabecera con SUBESTACIÓN y CAPACIDAD DISPONIBLE.
    Devuelve (header_row_idx, col_map) o (None, None).
    """
    for row_idx in range(min(8, len(df))):
        row = df.iloc[row_idx]
        row_str = [str(v).lower().strip().replace('\n', ' ') if pd.notna(v) else '' for v in row]
        
        disp_col = next((ci for ci, c in enumerate(row_str)
                         if re.search(r'capacidad.*disponible', c)), None)
        set_col  = next((ci for ci, c in enumerate(row_str)
                         if re.search(r'^subestaci', c)), None)
        kv_col   = next((ci for ci, c in enumerate(row_str)
                         if re.search(r'tensi.*kv|tensi.*\(kv\)', c)), None)
        prov_col = next((ci for ci, c in enumerate(row_str)
                         if re.search(r'^provincia$', c)), None)

        if disp_col is not None and set_col is not None:
            return row_idx, {
                'prov': prov_col,
                'set':  set_col,
                'kv':   kv_col,
                'disp': disp_col,
            }
    return None, None


if not SRC.exists():
    sys.exit(f"ERROR: no se encuentra {SRC}")

print(f"Leyendo {SRC.name} ...")
xl = pd.ExcelFile(SRC)
data_sheets = [s for s in xl.sheet_names if not SKIP_PAT.match(s.strip())]
print(f"  {len(data_sheets)} hojas de datos")

records = []
skipped = []

for sheet in data_sheets:
    fecha = parse_sheet_date(sheet)
    if not fecha:
        skipped.append(f"{sheet} (fecha no parseable)")
        continue

    df = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=str)
    hdr_idx, cols = detect_layout(df)
    if hdr_idx is None:
        skipped.append(f"{sheet} (sin layout reconocible)")
        continue

    n_ok = n_skip = 0
    for _, row in df.iloc[hdr_idx + 1:].iterrows():
        prov = str(row.iloc[cols['prov']]).strip() if cols['prov'] is not None and pd.notna(row.iloc[cols['prov']]) else ''
        if not prov or prov.lower() in ('nan', 'none', 'provincia'):
            n_skip += 1
            continue
        set_name = str(row.iloc[cols['set']]).strip() if pd.notna(row.iloc[cols['set']]) else ''
        if not set_name or set_name.lower() in ('nan', 'none'):
            n_skip += 1
            continue
        kv = ''
        if cols['kv'] is not None and pd.notna(row.iloc[cols['kv']]):
            kv = str(row.iloc[cols['kv']]).strip()
        disp = safe_float(row.iloc[cols['disp']])
        if disp is None or disp > MAX_MW:
            n_skip += 1
            continue
        records.append([fecha, 'E-Redes', prov, '', set_name, kv, round(disp, 4)])
        n_ok += 1

    print(f"  {sheet}: {n_ok} filas OK, {n_skip} skip")

if skipped:
    print(f"\nHojas omitidas: {skipped}")

cols_out = ['fecha', 'distribuidora', 'provincia', 'municipio', 'subestacion',
            'tension_kv', 'disponible_neta']
df_all = pd.DataFrame(records, columns=cols_out)
df_all.to_csv(OUT, index=False, encoding='utf-8-sig')

print(f"\n--- RESUMEN ---")
print(f"Registros válidos : {len(df_all):,}")
if len(df_all):
    print(f"Fechas            : {df_all['fecha'].nunique()}  ({df_all['fecha'].min()} → {df_all['fecha'].max()})")
    print(f"Subestaciones     : {df_all['subestacion'].nunique()}")
print(f"Guardado en       : {OUT}")
