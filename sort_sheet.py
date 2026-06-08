#!/usr/bin/env python3
"""sort_sheet.py — Ordena el Sheet por fecha_publicacion descendente."""
from sheets_exporter import get_client, SPREADSHEET_ID, SHEET_NAME
gc = get_client()
ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
ws.sort((2, "des"))
print("✓ Sheet ordenado por fecha_publicacion desc — más recientes arriba")
