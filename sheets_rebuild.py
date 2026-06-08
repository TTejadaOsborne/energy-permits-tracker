"""
sheets_rebuild.py
-----------------
Reconstruye el Google Sheet desde cero usando todos los archivos
output/energy_extraido_*.json, aplicando el filtro es_energetico=True.

Uso:
    python sheets_rebuild.py          # reconstruye todo el sheet
    python sheets_rebuild.py --dry    # muestra cuántas filas quedarían sin escribir

ADVERTENCIA: borra todas las filas actuales y las reescribe.
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime

from sheets_exporter import (
    COLUMNAS, SPREADSHEET_ID, SHEET_NAME,
    get_client, resultado_a_fila,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DRY = "--dry" in sys.argv


def cargar_todos_los_resultados() -> list[dict]:
    """Lee todos los energy_extraido_*.json y devuelve solo es_energetico=True."""
    output_dir = Path("output")
    archivos = sorted(output_dir.glob("energy_extraido_*.json"))
    if not archivos:
        logger.error("No hay archivos en output/. Ejecuta el pipeline primero.")
        sys.exit(1)

    resultados = []
    ids_vistos: set[str] = set()

    for archivo in archivos:
        with open(archivo, "r", encoding="utf-8") as f:
            data = json.load(f)

        for r in data.get("resultados", []):
            if not r.get("datos"):
                continue
            if r.get("estado_validacion") == "error":
                continue
            if not r.get("es_energetico", True):
                continue  # falso positivo — excluir

            id_boe = r.get("id", "")
            if id_boe in ids_vistos:
                continue  # deduplicar
            ids_vistos.add(id_boe)
            resultados.append(r)

    logger.info(f"Total registros energéticos únicos encontrados: {len(resultados)}")
    return resultados


def rebuild():
    resultados = cargar_todos_los_resultados()

    if DRY:
        logger.info(f"[DRY] Se escribirían {len(resultados)} filas. Sin cambios.")
        return

    try:
        gc = get_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(SHEET_NAME)
    except Exception as e:
        logger.error(f"Error conectando a Sheets: {e}")
        sys.exit(1)

    logger.info("Borrando Sheet actual…")
    ws.clear()

    # Cabeceras
    ws.update(range_name="A1", values=[COLUMNAS])
    logger.info("Cabeceras escritas.")

    # Construir filas
    filas = [resultado_a_fila(r) for r in resultados]

    # Expandir si hace falta
    filas_necesarias = len(filas) + 1  # +1 cabecera
    if ws.row_count < filas_necesarias:
        ws.add_rows(filas_necesarias - ws.row_count + 100)

    # Escribir en bloques de 1000 para no superar límite de API
    BLOQUE = 1000
    for i in range(0, len(filas), BLOQUE):
        chunk = filas[i:i + BLOQUE]
        fila_inicio = i + 2  # +1 por cabecera, +1 por base-1
        fila_fin = fila_inicio + len(chunk) - 1
        rango = f"A{fila_inicio}:AA{fila_fin}"
        ws.update(range_name=rango, values=chunk, value_input_option="USER_ENTERED")
        logger.info(f"  Bloque {i//BLOQUE + 1}: filas {fila_inicio}–{fila_fin} escritas")

    logger.info(f"✅ Sheet reconstruido: {len(filas)} filas energéticas reales.")
    logger.info(f"   Spreadsheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")


if __name__ == "__main__":
    rebuild()
