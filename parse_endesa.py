"""parse_endesa.py v2 - Extrae series temporales de capacidad Endesa."""
import re, sys
from pathlib import Path
import pandas as pd

BASE = Path(__file__).parent
SRC  = BASE / "references" / "Mapas_Capacidad_AyC-e_distribucion.xlsx"
OUT  = BASE / "references" / "endesa_capacidad.csv"

if not SRC.exists():
    sys.exit("ERROR: no se encuentra " + str(SRC))

MESES_ES = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12
}
CCAA_PAT = re.compile(r'^\d{2}\s*[-]')
MAX_MW   = 5000.0

def safe_float(val):
    if pd.isna(val):
        return 0.0
    try:
        return float(str(val).replace(',', '.').strip())
    except (ValueError, TypeError):
        return None

print("Leyendo " + SRC.name + " ...")
xl = pd.ExcelFile(SRC)
data_sheets = [s for s in xl.sheet_names if s.strip().lower() != 'notas']
print("  " + str(len(data_sheets)) + " hojas de datos")

records = []
skipped_ccaa = 0
skipped_range = 0

for sheet in data_sheets:
    parts = sheet.strip().split()
    try:
        mes_num = MESES_ES[parts[1].lower()]
        year    = int(parts[2])
        fecha   = str(year) + "-" + str(mes_num).zfill(2) + "-01"
    except (IndexError, KeyError, ValueError):
        print("  SKIP: " + sheet)
        continue

    df = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=str)
    n_ok = 0
    for _, row in df.iloc[4:].iterrows():
        ccaa = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
        if not CCAA_PAT.match(ccaa):
            skipped_ccaa += 1
            continue
        set_name = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ''
        if not set_name or set_name.lower() == 'nan':
            skipped_ccaa += 1
            continue
        disp = safe_float(row.iloc[6])
        ocup = safe_float(row.iloc[7])
        adm  = safe_float(row.iloc[18])
        if disp is None or ocup is None or adm is None:
            skipped_ccaa += 1
            continue
        if disp > MAX_MW or ocup > MAX_MW or adm > MAX_MW:
            skipped_range += 1
            continue
        lat = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ''
        lon = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else ''
        kv  = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ''
        records.append([
            fecha, ccaa,
            str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else '',
            set_name, kv, lat, lon,
            disp, ocup, adm, round(disp - adm, 4)
        ])
        n_ok += 1
    print("  " + sheet + ": " + str(n_ok) + " filas validas")

cols = ['fecha','ccaa','provincia','subestacion','tension_kv','lat','lon',
        'disponible','ocupada_total','admitida_total','disponible_neta']
df_all = pd.DataFrame(records, columns=cols)
df_all.to_csv(OUT, index=False, encoding='utf-8-sig')

print("\n--- RESUMEN ---")
print("Registros validos : " + str(len(df_all)))
print("Descartados CCAA  : " + str(skipped_ccaa))
print("Descartados rango : " + str(skipped_range))
print("Fechas            : " + str(df_all['fecha'].nunique()) + "  (" + df_all['fecha'].min() + " -> " + df_all['fecha'].max() + ")")
print("Subestaciones     : " + str(df_all['subestacion'].nunique()))
print("\nCCAA (SETs unicos):")
print(df_all.groupby('ccaa')['subestacion'].nunique().sort_values(ascending=False).to_string())
print("\nStats disponible_neta (MW):")
print(df_all['disponible_neta'].describe().round(1).to_string())
print("\nTop 10 SETs mayor disponible_neta (ultimo snapshot):")
ultimo = df_all[df_all['fecha'] == df_all['fecha'].max()]
top = ultimo.nlargest(10, 'disponible_neta')[['subestacion','provincia','tension_kv','disponible_neta']]
print(top.to_string(index=False))
print("\nGuardado en: " + str(OUT))
