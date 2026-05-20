#!/usr/bin/env python3
"""
repair_sheets.py
----------------
Limpia entradas incorrectas del Google Sheet de Nodalys:

1. BOLR Najerilla Solar — elimina todos los duplicados, mantiene solo BOLR-anu-577396
   (la publicación real del 20/05/2026)
2. BOPA-20260518-8 "Instalación Energética Carreño" — entrada genérica DUP, eliminar
3. BOJA nombre="de la Delegación Territorial..." — nombre incorrecto, reemplazar con
   nombre construido desde tipo_permiso + municipio/provincia
4. Entradas BOJA/DOG con nombre = texto del título del anuncio (falsos nombres)

Uso:
    python repair_sheets.py [--dry]   # --dry solo muestra lo que haría, sin modificar

Requiere: gspread, google-auth, credentials.json en el mismo directorio
"""

import argparse, json, re, sys
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    sys.exit("pip install gspread google-auth --break-system-packages")

BASE = Path(__file__).parent
SPREADSHEET_ID   = "1jqhG2ub287WHrBa1myP8wKygqPTiXDHq-x-9GEcmblE"
SHEET_NAME       = "Permisos"
CREDENTIALS_FILE = BASE / "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Columnas (mismas que sheets_exporter.py) ────────────────────────────────
COLUMNAS = [
    "id_boe","fecha_publicacion","boletin","ccaa",
    "nombre_proyecto","promotor","tecnologia","potencia_mw",
    "tipo_permiso","permisos_adicionales","estado_permiso",
    "es_proyecto_fallido","motivo_fallo","subestacion_conexion",
    "tension_conexion_kv","gestor_red","municipio","provincia",
    "comunidad_autonoma","numero_expediente_industria",
    "numero_expediente_medioambiente","capacidad_mw_liberada",
    "fecha_resolucion","confianza","url","titulo_original","fecha_carga",
]
COL_IDX = {c: i for i, c in enumerate(COLUMNAS)}


# ── Reglas de limpieza ───────────────────────────────────────────────────────

# 1. IDs a eliminar directamente
IDS_A_ELIMINAR = {
    # Instalación Energética Carreño — DUP genérico, componentes ya incluidos por separado
    "BOPA-20260518-8",
}

# 2. Patrón BOLR Najerilla: todos menos BOLR-anu-577396
BOLR_NAJERILLA_URL = "40473173-1-PDF-577396"   # substring de la URL PDF
BOLR_NAJERILLA_KEEP = "BOLR-anu-577396"

# 3. Nombres que son en realidad texto del título del anuncio (falso nombre)
BAD_NAME_PREFIXES = (
    "de la delegación",
    "del departamento territorial",
    "por el que se",
    "por la que se",
    "por el presente",
    "en virtud",
    "de acuerdo con",
)

TIPO_LABEL = {
    "ModAAC": "ModAAC",
    "ModAAP": "ModAAP",
    "LAP":    "LAP",
    "AAP":    "AAP",
    "AAC":    "AAC",
    "AAE":    "AAE",
    "DUP":    "DUP",
    "EsIA":   "EsIA",
    "DIA":    "DIA",
}

def build_fallback_name(row: dict) -> str:
    """Construye nombre descriptivo cuando el nombre extraído es genérico."""
    tipo = row.get("tipo_permiso") or ""
    mun  = row.get("municipio") or ""
    prov = row.get("provincia") or ""
    tec  = row.get("tecnologia") or ""
    ubicacion = mun or prov
    tipo_lbl  = TIPO_LABEL.get(tipo, tipo)

    if ubicacion and tec and tec.lower() not in ("otro",""):
        return f"{tec} {ubicacion} ({tipo_lbl})" if tipo_lbl else f"{tec} {ubicacion}"
    if ubicacion:
        return f"Instalación Eléctrica {ubicacion} ({tipo_lbl})" if tipo_lbl else f"Instalación Eléctrica {ubicacion}"
    return f"Instalación Eléctrica ({tipo_lbl})" if tipo_lbl else "Instalación Eléctrica"


def is_bad_name(nombre: str) -> bool:
    if not nombre:
        return False
    lo = nombre.lower().strip()
    return any(lo.startswith(p) for p in BAD_NAME_PREFIXES)


def run(dry: bool):
    print("Conectando a Google Sheets…")
    creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=SCOPES)
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

    print("Descargando datos…")
    all_values = ws.get_all_values()
    header     = all_values[0]
    data_rows  = all_values[1:]
    total      = len(data_rows)
    print(f"  {total:,} filas de datos (+ 1 cabecera)")

    # Mapear columnas (puede diferir del orden esperado)
    col_map = {h.lower().strip(): i for i, h in enumerate(header)}
    def gcol(name):
        return col_map.get(name.lower(), COL_IDX.get(name))

    ci_id     = gcol("id_boe")
    ci_nombre = gcol("nombre_proyecto")
    ci_url    = gcol("url")
    ci_tipo   = gcol("tipo_permiso")
    ci_mun    = gcol("municipio")
    ci_prov   = gcol("provincia")
    ci_tec    = gcol("tecnologia")

    rows_to_delete  = []   # list of 1-based sheet row numbers (row 1 = header)
    rows_to_update  = []   # list of (row_number_1based, col_1based, new_value)

    for idx, row in enumerate(data_rows, start=2):   # row 2 = first data row
        def g(ci):
            return row[ci].strip() if ci is not None and ci < len(row) else ""

        iid     = g(ci_id)
        nombre  = g(ci_nombre)
        url     = g(ci_url)
        tipo    = g(ci_tipo)
        mun     = g(ci_mun)
        prov    = g(ci_prov)
        tec     = g(ci_tec)

        # ── Regla 1: IDs directos ────────────────────────────────────
        if iid in IDS_A_ELIMINAR:
            print(f"  [DELETE] {iid} — en lista de eliminación directa")
            rows_to_delete.append(idx)
            continue

        # ── Regla 2: BOLR Najerilla duplicados ───────────────────────
        if BOLR_NAJERILLA_URL in url and iid != BOLR_NAJERILLA_KEEP:
            print(f"  [DELETE] {iid} — duplicado Najerilla Solar BOLR")
            rows_to_delete.append(idx)
            continue

        # ── Regla 3: nombre = texto de anuncio (no nombre de proyecto) ─
        if is_bad_name(nombre):
            new_name = build_fallback_name({"tipo_permiso": tipo, "municipio": mun,
                                            "provincia": prov, "tecnologia": tec})
            print(f"  [FIX]    {iid} — nombre '{nombre[:50]}' → '{new_name}'")
            if ci_nombre is not None:
                rows_to_update.append((idx, ci_nombre + 1, new_name))

    print(f"\nResumen:")
    print(f"  Filas a eliminar:  {len(rows_to_delete)}")
    print(f"  Filas a corregir:  {len(rows_to_update)}")

    if dry:
        print("\n[DRY RUN] No se aplican cambios.")
        return

    # Aplicar actualizaciones primero (sin alterar índices de fila)
    if rows_to_update:
        print("\nAplicando correcciones de nombre…")
        for row_num, col_num, value in rows_to_update:
            ws.update_cell(row_num, col_num, value)
        print(f"  {len(rows_to_update)} celdas actualizadas")

    # Eliminar filas de abajo a arriba (para no desplazar índices)
    if rows_to_delete:
        print("\nEliminando filas duplicadas/inválidas…")
        for row_num in sorted(rows_to_delete, reverse=True):
            ws.delete_rows(row_num)
        print(f"  {len(rows_to_delete)} filas eliminadas")

    print("\nFIN. Datos corregidos en el Sheet.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Limpia entradas incorrectas del Sheet de Nodalys")
    p.add_argument("--dry", action="store_true", help="Solo mostrar, no modificar")
    args = p.parse_args()
    run(dry=args.dry)
