"""
sheets_exporter.py — Vuelca resultados del pipeline a Google Sheets
Usa gspread + cuenta de servicio (credentials.json)
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
SPREADSHEET_ID   = "1jqhG2ub287WHrBa1myP8wKygqPTiXDHq-x-9GEcmblE"
SHEET_NAME       = "Permisos"
CREDENTIALS_FILE = "credentials.json"
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COLUMNAS = [
    "id_boe", "fecha_publicacion", "boletin", "ccaa",
    "nombre_proyecto", "promotor", "tecnologia", "potencia_mw",
    "tipo_permiso", "permisos_adicionales", "estado_permiso",
    "es_proyecto_fallido", "motivo_fallo", "subestacion_conexion",
    "tension_conexion_kv", "gestor_red", "municipio", "provincia",
    "comunidad_autonoma", "numero_expediente_industria",
    "numero_expediente_medioambiente", "capacidad_mw_liberada",
    "fecha_resolucion", "confianza", "url", "titulo_original", "fecha_carga",
]


def get_client():
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def resultado_a_fila(item: dict) -> list:
    d = item.get("datos") or {}
    raiz = {
        "id_boe":            item.get("id", ""),
        "fecha_publicacion": item.get("fecha_publicacion", ""),
        "boletin":           item.get("boletin", ""),
        "ccaa":              item.get("ccaa_boletin", ""),
        "url":               item.get("url", ""),
        "titulo_original":   (item.get("titulo_original") or "")[:200],
        "fecha_carga":       datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    fila = []
    for col in COLUMNAS:
        if col in raiz:
            fila.append(str(raiz[col]))
        else:
            v = d.get(col)
            if v is None:
                fila.append("")
            elif isinstance(v, list):
                fila.append("|".join(str(x) for x in v))
            elif isinstance(v, bool):
                fila.append("SI" if v else "NO")
            else:
                fila.append(str(v))
    return fila


def exportar_a_sheets(output_json: str) -> dict:
    with open(output_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    resultados = [r for r in data.get("resultados", [])
                  if r.get("datos") and r.get("estado_validacion") != "error"
                  and r.get("es_energetico", True)]

    if not resultados:
        logger.info("Sin items validos para exportar")
        return {"exportados": 0, "duplicados": 0}

    try:
        gc = get_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(SHEET_NAME)
    except Exception as e:
        logger.error(f"Error conectando a Sheets: {e}")
        return {"error": str(e)}

    # Limpiar SIEMPRE y reconstruir desde cero para evitar desplazamientos
    # Leer IDs existentes primero para no perder datos anteriores
    existing = ws.get_all_values()

    if not existing or not existing[0] or existing[0][0] != "id_boe":
        # Sheet vacío o sin cabeceras — inicializar limpio
        ws.clear()
        ws.update(range_name="A1", values=[COLUMNAS])
        ids_existentes = set()
        fila_inicio = 2
    else:
        # Sheet con datos — leer IDs y calcular próxima fila disponible
        ids_existentes = {row[0] for row in existing[1:] if row and row[0]}
        fila_inicio = len(existing) + 1

    # Filtrar duplicados
    nuevos = [r for r in resultados if r.get("id", "") not in ids_existentes]
    duplicados = len(resultados) - len(nuevos)

    if not nuevos:
        logger.info(f"Todos los items ya en Sheets ({duplicados} duplicados)")
        return {"exportados": 0, "duplicados": duplicados}

    # Construir filas
    filas = [resultado_a_fila(r) for r in nuevos]

    # Escribir en rango explícito A{fila_inicio}:AA{fila_fin}
    # Esto evita que gspread busque la "última fila con datos" y se desplace
    fila_fin = fila_inicio + len(filas) - 1
    rango = f"A{fila_inicio}:AA{fila_fin}"

    # Expandir el Sheet si faltan filas (gspread nueva API requiere valores primero)
    filas_actuales = ws.row_count
    if fila_fin > filas_actuales:
        ws.add_rows(fila_fin - filas_actuales + 50)  # margen extra
        logger.info(f"Sheet expandido a {fila_fin + 50} filas")

    # Nueva API gspread: valores primero, rango segundo
    ws.update(range_name=rango, values=filas, value_input_option="USER_ENTERED")

    logger.info(f"Sheets: +{len(filas)} filas en {rango} ({duplicados} duplicados)")

    # Ordenar el Sheet por fecha_publicacion (col B) descendente — más recientes arriba
    try:
        ws.sort((2, "des"))  # columna 2 = fecha_publicacion, des = descendente
        logger.info("Sheet ordenado por fecha_publicacion desc")
    except Exception as e_sort:
        logger.warning(f"No se pudo ordenar el Sheet: {e_sort}")

    return {"exportados": len(filas), "duplicados": duplicados}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        outputs = sorted(Path("output").glob("energy_extraido_*.json"))
        if not outputs:
            print("No hay archivos JSON en output/. Ejecuta el pipeline primero.")
            sys.exit(1)
        archivo = str(outputs[-1])
    else:
        archivo = sys.argv[1]

    print(f"Exportando {archivo} -> Google Sheets...")
    resultado = exportar_a_sheets(archivo)
    print(f"Resultado: {resultado}")
