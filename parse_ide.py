"""parse_ide.py - Extrae series temporales de capacidad i-DE Redes Eléctricas."""
import re, sys
from pathlib import Path
import pandas as pd

BASE = Path(__file__).parent
SRC  = BASE / "references" / "Mapas_Capacidad_AyC-iDE.xlsx"
OUT  = BASE / "references" / "ide_capacidad.csv"

if not SRC.exists():
    sys.exit("ERROR: no se encuentra " + str(SRC))

MESES_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12
}
MAX_MW = 5000.0

# Hojas a ignorar
SKIP_PAT = re.compile(r'^(resumen|demanda_base|generacion_base)', re.IGNORECASE)

def safe_float(val):
    if pd.isna(val): return 0.0
    try:
        return float(str(val).replace(',', '.').strip())
    except (ValueError, TypeError):
        return None

def detect_layout(df):
    """
    Detecta el layout de la hoja buscando dinámicamente el header.
    Devuelve (header_row_idx, col_map) donde col_map tiene:
      provincia, municipio, subestacion, tension_kv, disponible
    o None si no se puede detectar.
    """
    DISP_PATTERNS = [
        r'capacidad.*disponible',
        r'capacidad.*firme.*disponible',
    ]
    for row_idx in range(min(6, len(df))):
        row = df.iloc[row_idx]
        row_str = [str(v).lower().strip() if pd.notna(v) else '' for v in row]
        # Buscar columna de capacidad disponible
        disp_col = None
        for ci, cell in enumerate(row_str):
            if any(re.search(p, cell) for p in DISP_PATTERNS):
                disp_col = ci
                break
        if disp_col is None:
            continue
        # Buscar columnas de provincia, subestacion, tensión
        prov_col = muni_col = set_col = kv_col = None
        for ci, cell in enumerate(row_str):
            if re.search(r'^provincia$|^prov$', cell): prov_col = ci
            elif re.search(r'^municipio$|^muni', cell): muni_col = ci
            elif re.search(r'denominaci.*punto|denominaci.*acceso', cell):
                set_col = ci  # nombre preferido sobre código
            elif re.search(r'^subestaci', cell) and set_col is None:
                set_col = ci  # fallback si no hay denominación
            elif re.search(r'nivel.*tensi|tensi.*kv|tensi.*\(kv\)|^tensi', cell):
                kv_col = ci
        if prov_col is not None and set_col is not None and disp_col is not None:
            return row_idx, {
                'prov': prov_col,
                'muni': muni_col,
                'set':  set_col,
                'kv':   kv_col,
                'disp': disp_col,
            }
    return None, None

print(f"Leyendo {SRC.name} ...")
xl = pd.ExcelFile(SRC)
data_sheets = [s for s in xl.sheet_names if not SKIP_PAT.match(s.strip())]
print(f"  {len(data_sheets)} hojas de datos (excluidas Resumen/BaseDatos)")

records = []
skipped_sheets = []

for sheet in data_sheets:
    parts = sheet.strip().split()
    # Intentar parsear "DD MES YYYY"
    try:
        mes_num = MESES_ES[parts[1].lower()]
        year    = int(parts[2])
        day     = int(parts[0])
        fecha   = f"{year}-{mes_num:02d}-{day:02d}"
    except (IndexError, KeyError, ValueError):
        skipped_sheets.append(sheet)
        continue

    df = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=str)

    hdr_idx, cols = detect_layout(df)
    if hdr_idx is None:
        skipped_sheets.append(f"{sheet} (sin header)")
        continue

    n_ok = n_skip = 0
    for _, row in df.iloc[hdr_idx + 1:].iterrows():
        # Provincia
        prov = str(row.iloc[cols['prov']]).strip() if pd.notna(row.iloc[cols['prov']]) else ''
        if not prov or prov.lower() in ('nan', 'none', 'provincia'):
            n_skip += 1
            continue
        # Subestación
        set_name = str(row.iloc[cols['set']]).strip() if pd.notna(row.iloc[cols['set']]) else ''
        if not set_name or set_name.lower() in ('nan', 'none'):
            n_skip += 1
            continue
        # Tensión
        kv = ''
        if cols['kv'] is not None:
            kv = str(row.iloc[cols['kv']]).strip() if pd.notna(row.iloc[cols['kv']]) else ''
        # Municipio (opcional)
        muni = ''
        if cols['muni'] is not None:
            muni = str(row.iloc[cols['muni']]).strip() if pd.notna(row.iloc[cols['muni']]) else ''
            if muni.lower() in ('nan', 'none'): muni = ''
        # Capacidad disponible (ya es neta per instrucción usuario)
        disp = safe_float(row.iloc[cols['disp']])
        if disp is None or disp > MAX_MW:
            n_skip += 1
            continue
        records.append([fecha, 'iDE', prov, muni, set_name, kv, round(disp, 4)])
        n_ok += 1

    print(f"  {sheet}: {n_ok} filas OK, {n_skip} skip")

if skipped_sheets:
    print(f"\nHojas omitidas: {skipped_sheets}")

cols_out = ['fecha', 'distribuidora', 'provincia', 'municipio', 'subestacion',
            'tension_kv', 'disponible_neta']
df_all = pd.DataFrame(records, columns=cols_out)
df_all.to_csv(OUT, index=False, encoding='utf-8-sig')

print(f"\n--- RESUMEN ---")
print(f"Registros válidos : {len(df_all)}")
print(f"Fechas            : {df_all['fecha'].nunique()}  ({df_all['fecha'].min()} -> {df_all['fecha'].max()})")
print(f"Subestaciones     : {df_all['subestacion'].nunique()}")
print(f"\nProvincias (SETs únicos):")
print(df_all.groupby('provincia')['subestacion'].nunique().sort_values(ascending=False).head(15).to_string())
print(f"\nTop 10 SETs mayor capacidad disponible (último snapshot):")
ultimo = df_all[df_all['fecha'] == df_all['fecha'].max()]
top = ultimo.nlargest(10, 'disponible_neta')[['subestacion','provincia','tension_kv','disponible_neta']]
print(top.to_string(index=False))
print(f"\nGuardado en: {OUT}")
