#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_sets_history.py v2 — añade cap_gen_ocup, cap_gen_tram, cap_dem_ocup, cap_dem_tram"""

import argparse, json, re, sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("pip install openpyxl"); sys.exit(1)

MESES_ES = {"ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,
            "jul":7,"ago":8,"sep":9,"oct":10,"nov":11,"dic":12}
HIST_RE  = re.compile(r'^(DSO|REE)\s+([A-Za-z]+)(\d{2})$', re.IGNORECASE)

def to_float(v):
    if v is None or v == "" or v == "N/A": return None
    try: return float(v)
    except: return None

def add_floats(*vals):
    """Sum ignoring None; returns None if ALL are None."""
    nums = [v for v in vals if v is not None]
    return round(sum(nums), 4) if nums else None

def parse_sheet(name):
    m = HIST_RE.match(name.strip())
    if not m: return None
    tipo = m.group(1).upper()
    mes  = MESES_ES.get(m.group(2).lower()[:3])
    year = 2000 + int(m.group(3))
    return (tipo, year, mes) if mes else None

def label(y, m): return f"{y:04d}-{m:02d}"

def extract_dso(ws, year, mes):
    """
    DSO columns (0-indexed):
      DEMANDA section (r4 header "DEMANDA"):
        11: disponible (cap firme disponible)
        15: ocupada dem (cap acceso firme demanda ocupada)
        16: trámite dem (cap acceso firme admitida y no evaluada)
      GENERACIÓN section (r4 header "GENERACIÓN"):
        21: disponible gen (cap disponible)
        25: ocupada gen (cap ocupada)
        26: trámite gen (cap admitida y no resuelta)
    """
    entries = {}
    lbl = label(year, mes)
    for row in ws.iter_rows(min_row=6, values_only=True):
        if not row or len(row) < 27: continue
        key = row[10]
        if not key or not str(key).strip(): continue
        key = str(key).strip()
        entries[key] = {
            "date":        lbl,
            "cap_gen":     to_float(row[21]),   # GEN disponible
            "cap_dem":     to_float(row[11]),   # DEM disponible
            "cap_gen_ocup":to_float(row[25]),   # GEN ocupada
            "cap_gen_tram":to_float(row[26]),   # GEN en trámite
            "cap_dem_ocup":to_float(row[15]),   # DEM ocupada
            "cap_dem_tram":to_float(row[16]),   # DEM en trámite
            "acept":       None,
        }
    return entries

def extract_ree(ws, year, mes):
    """
    REE columns (0-indexed, data from row 9):
      1:  nombre_nudo (key)
      4:  cap_gen disponible (NETO GENERACIÓN ALM)
      7:  cap_dem disponible (NETO DEMANDA ALM)
      10: aceptabilidad neta
      GEN ocupada:  col[33]  Capacidad de acceso otorgada MPE
      GEN trámite:  col[40]  Capacidad solicitada en curso y pendiente MPE
      DEM ocupada:  col[89] (otorgada demanda RdT) + col[93] (otorgada almacenamiento RdT)
      DEM trámite:  col[100] (solicitada en curso demanda RdT) + col[101] (solicitada en curso alm RdT)
    """
    entries = {}
    lbl = label(year, mes)
    for row in ws.iter_rows(min_row=9, values_only=True):
        if not row or len(row) < 102: continue
        key = row[1]
        if not key or not str(key).strip(): continue
        key = str(key).strip()

        gen_ocup = to_float(row[33])
        gen_tram = to_float(row[40])
        dem_ocup = add_floats(to_float(row[89]), to_float(row[93]))
        dem_tram = add_floats(to_float(row[100]), to_float(row[101]))

        entries[key] = {
            "date":        lbl,
            "cap_gen":     to_float(row[4]),
            "cap_dem":     to_float(row[7]),
            "cap_gen_ocup":gen_ocup,
            "cap_gen_tram":gen_tram,
            "cap_dem_ocup":dem_ocup,
            "cap_dem_tram":dem_tram,
            "acept":       to_float(row[10]),
        }
    return entries

def build_history(wb):
    hist = [(y,m,t,n) for n in wb.sheetnames
            for res in [parse_sheet(n)] if res
            for t,y,m in [res]]
    if not hist:
        print("No historical sheets found."); return {}
    hist.sort(key=lambda x:(x[0],x[1]))
    print(f"\nHistorical sheets ({len(hist)}):")
    for y,m,t,n in hist:
        print(f"  [{t}] {n} → {label(y,m)}")

    raw = {}  # key → {date: snap}
    for y,m,t,n in hist:
        ws = wb[n]
        lbl = label(y,m)
        entries = extract_dso(ws,y,m) if t=="DSO" else extract_ree(ws,y,m)
        print(f"  '{n}': {len(entries)} entries")
        for key, snap in entries.items():
            if key not in raw: raw[key] = {}
            if lbl in raw[key]:
                ex = raw[key][lbl]
                for f in ("cap_gen","cap_dem","cap_gen_ocup","cap_gen_tram",
                          "cap_dem_ocup","cap_dem_tram","acept"):
                    if ex[f] is None and snap[f] is not None:
                        ex[f] = snap[f]
            else:
                raw[key][lbl] = snap

    return {k: sorted(v.values(), key=lambda s:s["date"]) for k,v in raw.items()}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", default="Monitor_Capacidad_Red_INTEGRADO_v4.xlsx")
    parser.add_argument("--out",   default="sets_history.json")
    args = parser.parse_args()
    excel_path = Path(args.excel)
    if not excel_path.exists():
        print(f"ERROR: {excel_path}"); sys.exit(1)
    print(f"Reading {excel_path} ...")
    wb = openpyxl.load_workbook(excel_path, read_only=False, data_only=True)
    history = build_history(wb)

    # Stats
    print(f"\nSETs: {len(history)}")
    print(f"Snapshots: {sum(len(v) for v in history.values())}")
    has_gen_ocup = sum(1 for v in history.values() if any(s["cap_gen_ocup"] is not None for s in v))
    has_dem_ocup = sum(1 for v in history.values() if any(s["cap_dem_ocup"] is not None for s in v))
    print(f"SETs with gen_ocup: {has_gen_ocup}")
    print(f"SETs with dem_ocup: {has_dem_ocup}")

    # Sample
    sample = next((k for k,v in history.items() if v and v[0].get("cap_gen_ocup") is not None), None)
    if sample:
        print(f"\nSample ({sample}): {history[sample][0]}")

    out = Path(args.out)
    with open(out,"w",encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",",":"))
    print(f"\n✓ {out}  ({out.stat().st_size/1024:.0f} KB, {len(history)} SETs)")

if __name__ == "__main__":
    main()
