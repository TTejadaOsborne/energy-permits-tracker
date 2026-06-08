#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rescrape_boeb.py — Re-scrape retroactivo de publicaciones BOE-B.

Problema: el scraper anterior solo capturaba secciones 1-5 del BOE (BOE-A).
La sección 6 (BOE-B, anuncios de particulares/promotores) fue ignorada.
Este script:
  1. Para cada fecha en el rango, obtiene SOLO los ítems BOE-B nuevos
  2. Los extrae con el LLM
  3. COMBINA los resultados con el JSON existente (sin sobreescribir BOE-A)
  4. Al final regenera projects.json + projects_data.js

Uso:
  python rescrape_boeb.py --desde 20250101 --hasta 20260601
  python rescrape_boeb.py --desde 20250101 --hasta 20260601 sk-ant-xxx
  python rescrape_boeb.py --solo-listado --desde 20250101  # ver qué encontraría
"""

import os, sys, json, subprocess, time
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent))

OUTPUT_DIR   = Path("output")
DATA_DIR     = Path("data")
SEEN_PATH    = Path("references") / "seen_urls.json"
BOLETINES    = ["BOE"]  # solo BOE para este re-scrape

# ── Festivos nacionales para evitar días sin boletín ─────────────────────────
FESTIVOS = {
    date(2025,1,1),date(2025,1,6),date(2025,4,17),date(2025,4,18),
    date(2025,5,1),date(2025,8,15),date(2025,10,12),date(2025,11,1),
    date(2025,12,6),date(2025,12,8),date(2025,12,25),
    date(2026,1,1),date(2026,1,6),date(2026,4,2),date(2026,4,3),
    date(2026,5,1),date(2026,8,15),date(2026,10,12),date(2026,11,1),
    date(2026,12,7),date(2026,12,8),date(2026,12,25),
}

def dias_laborables(desde: date, hasta: date):
    d, out = desde, []
    while d <= hasta:
        if d.weekday() < 5 and d not in FESTIVOS:
            out.append(d)
        d += timedelta(days=1)
    return out

def load_seen():
    if SEEN_PATH.exists():
        try: return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        except: pass
    return {}

def save_seen(seen):
    SEEN_PATH.parent.mkdir(exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")

def scrape_boeb_dia(fecha_str: str) -> list:
    """Devuelve lista de ítems BOE-B para esa fecha usando el scraper."""
    from scrapers.multi_scraper import MultiBoletinScraper
    import requests
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    scraper = MultiBoletinScraper(output_dir=str(DATA_DIR))
    all_items = scraper.scrape_dia(fecha=fecha_str, boletines=["BOE"])
    # Filtrar solo BOE-B
    return [it for it in all_items if it.get("id","").startswith("BOE-B")]

def merge_into_existing(fecha_str: str, new_results: list) -> int:
    """Añade new_results al JSON existente de esa fecha. Devuelve nº añadidos."""
    out_file = OUTPUT_DIR / f"energy_extraido_{fecha_str}.json"
    if out_file.exists():
        existing = json.loads(out_file.read_text(encoding="utf-8"))
    else:
        existing = {"fecha": fecha_str, "total": 0, "energeticos": 0,
                    "descartados": 0, "exitosos": 0, "errores": 0,
                    "tokens": {"input": 0, "output": 0}, "coste_usd": 0.0,
                    "alertas_capacidad_liberada": 0, "mw_totales_liberados": 0.0,
                    "resultados": []}
    
    existing_ids = {r.get("id","") for r in existing.get("resultados", [])}
    added = 0
    for r in new_results:
        if r.get("id","") not in existing_ids and r.get("es_energetico") and r.get("datos"):
            existing["resultados"].append(r)
            existing["energeticos"] = existing.get("energeticos", 0) + 1
            existing["exitosos"]    = existing.get("exitosos", 0) + 1
            tok = r.get("tokens", {})
            existing["tokens"]["input"]  += tok.get("input", 0)
            existing["tokens"]["output"] += tok.get("output", 0)
            existing["coste_usd"] = round(existing.get("coste_usd", 0) + r.get("coste_usd", 0), 5)
            added += 1
    
    if added > 0:
        out_file.parent.mkdir(exist_ok=True)
        out_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return added

def main():
    args = sys.argv[1:]
    solo_listado = "--solo-listado" in args
    
    # Parse dates
    desde_str = "20250101"
    hasta_str = date.today().strftime("%Y%m%d")
    for i, a in enumerate(args):
        if a == "--desde" and i+1 < len(args): desde_str = args[i+1]
        if a == "--hasta" and i+1 < len(args): hasta_str = args[i+1]
    desde = date(int(desde_str[:4]), int(desde_str[4:6]), int(desde_str[6:]))
    hasta = date(int(hasta_str[:4]), int(hasta_str[4:6]), int(hasta_str[6:]))
    
    api_key = next((a for a in args if a.startswith("sk-")), "")
    if not api_key and not solo_listado:
        env = Path(".env")
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=",1)[1].strip().strip('"\'')
        if not api_key:
            api_key = input("\n  Anthropic API key: ").strip()
        if not api_key:
            print("  ERROR: API key necesaria."); sys.exit(1)

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║  Re-scrape retroactivo BOE-B             ║")
    print("  ╚══════════════════════════════════════════╝")
    print(f"\n  Rango: {desde_str} → {hasta_str}")

    dias = dias_laborables(desde, hasta)
    print(f"  Días laborables: {len(dias)}")
    
    seen = load_seen()

    # ── FASE 1: Descubrir cuántos BOE-B hay por fecha ─────────────────────────
    print(f"\n  Escaneando fechas en busca de BOE-B nuevos...")
    fechas_con_boeb = []
    total_nuevos = 0

    for i, d in enumerate(dias):
        fecha_str = d.strftime("%Y%m%d")
        sys.stdout.write(f"\r  [{i+1}/{len(dias)}] {fecha_str}...   ")
        sys.stdout.flush()
        try:
            items_boeb = scrape_boeb_dia(fecha_str)
            nuevos = [it for it in items_boeb
                      if it.get("url","") not in seen and it.get("id","") not in seen]
            if nuevos:
                fechas_con_boeb.append((d, fecha_str, nuevos))
                total_nuevos += len(nuevos)
        except Exception as e:
            pass  # silenciar errores de red individuales
        time.sleep(0.3)

    print(f"\n\n  Fechas con BOE-B nuevos: {len(fechas_con_boeb)}")
    print(f"  Total ítems BOE-B nuevos: {total_nuevos}")

    if not fechas_con_boeb or solo_listado:
        print()
        for d, fecha_str, items in fechas_con_boeb[:30]:
            print(f"  {fecha_str}: {len(items)} ítems")
            for it in items[:3]:
                print(f"    {it.get('id','')} | {it.get('titulo','')[:60]}")
        if solo_listado:
            print("\n  (modo --solo-listado, sin extracción)")
        return

    resp = input(f"\n  Extraer y añadir {total_nuevos} ítems? [Enter=Sí / n=No]: ").strip().lower()
    if resp == "n":
        return

    # ── FASE 2: Extraer y combinar ────────────────────────────────────────────
    from extractor.energy_extractor import EnergyExtractor
    extractor = EnergyExtractor(api_key=api_key)

    total_added = total_errors = 0
    for i, (d, fecha_str, items_nuevos) in enumerate(fechas_con_boeb, 1):
        print(f"\n  [{i}/{len(fechas_con_boeb)}] {fecha_str} — {len(items_nuevos)} ítems BOE-B")
        
        resultados = []
        for item in items_nuevos:
            # Get full text
            try:
                item["texto"] = extractor._enrich_item(item) if hasattr(extractor, '_enrich_item') else ""
            except: pass
            r = extractor.extraer_item(item)
            resultados.append(r)
            # Mark as seen
            url = item.get("url","")
            if url: seen[url] = {"file": "rescrape_boeb", "id": item.get("id",""), "fecha": fecha_str}
            iid = item.get("id","")
            if iid: seen[iid] = {"file": "rescrape_boeb", "fecha": fecha_str}
            if r.get("estado_validacion") == "error":
                total_errors += 1
                print(f"    ✗ {item.get('id','')} — {str(r.get('error',''))[:60]}")
            elif r.get("es_energetico") and r.get("datos"):
                print(f"    ✓ {item.get('id','')} | {r['datos'].get('nombre_proyecto','?')[:40]}")
        
        # Merge into existing JSON
        energeticos = [r for r in resultados if r.get("es_energetico") and r.get("datos")]
        added = merge_into_existing(fecha_str, energeticos)
        total_added += added
        
        # Export to Sheet
        if added > 0:
            out = OUTPUT_DIR / f"energy_extraido_{fecha_str}.json"
            subprocess.run([sys.executable, "sheets_exporter.py", str(out)], capture_output=True)
        
        # Save seen_urls periodically
        if i % 10 == 0:
            save_seen(seen)

    save_seen(seen)

    print(f"\n\n  RESULTADO:")
    print(f"    ✓ Ítems energéticos añadidos: {total_added}")
    print(f"    ✗ Errores de extracción:       {total_errors}")

    # ── FASE 3: Regenerar ─────────────────────────────────────────────────────
    print(f"\n  Regenerando projects.json + projects_data.js...")
    try:
        import project_resolver as pr
        records = pr.load_all_records(pr.OUTPUT_DIR)
        uf, _   = pr.resolve_projects(records)
        projs   = pr.build_projects(records, uf)
        with open("projects.json","w",encoding="utf-8") as f:
            json.dump({"version":"1.0","generado":date.today().isoformat(),
                       "total":len(projs),"proyectos":projs},f,ensure_ascii=False,indent=2)
        pj = json.loads(Path("projects.json").read_text())
        Path("projects_data.js").write_text(
            "window.PROJECTS_INLINE = " + json.dumps(pj, ensure_ascii=False) + ";", encoding="utf-8")
        print(f"  OK  {len(projs)} proyectos")
    except Exception as e:
        print(f"  WARN: {e}")

    # ── FASE 4: Git push ──────────────────────────────────────────────────────
    print(f"\n  Publicando en GitHub Pages...")
    try:
        today = date.today().strftime("%Y%m%d")
        subprocess.run(["git","add","projects.json"], check=True)
        subprocess.run(["git","add","-f","projects_data.js"], check=True)
        r = subprocess.run(["git","diff","--cached","--quiet"], capture_output=True)
        if r.returncode != 0:
            subprocess.run(["git","commit","-m",f"data: BOE-B rescrape {today}"], check=True)
            subprocess.run(["git","push"], check=True)
            print("  OK  Publicado")
        else:
            print("  Sin cambios nuevos")
    except Exception as e:
        print(f"  WARN git: {e}")

    print(f"\n  ✓ Re-scrape BOE-B completado\n")

if __name__ == "__main__":
    main()
