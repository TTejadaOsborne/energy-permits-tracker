"""
dedup_pipeline.py
-----------------
Deduplica y normaliza los datos ya extraidos en output/energy_extraido_*.json

Problemas que resuelve:
  1. URL duplicada: mismo anuncio detectado en multiples fechas
  2. Titulo+boletin duplicado sin URL (BOA/BOPA): mismo anuncio rascado varias veces
  3. Nombres de proyecto con prefijo distinto: solo normaliza si misma tecnologia

Accion:
  - Modifica los JSON in-place (hace backup en output/backup_dedup/)
  - Genera references/dedup_report.csv
  - Genera references/seen_urls.json (usado por pipeline para evitar re-procesar)

Uso:
  python dedup_pipeline.py            # aplica dedup real
  python dedup_pipeline.py --dry      # solo muestra estadisticas
"""

import argparse, json, re, shutil, csv
from pathlib import Path
from collections import defaultdict

BASE    = Path(__file__).parent
OUT_DIR = BASE / "output"
REF_DIR = BASE / "references"
BACKUP_DIR = OUT_DIR / "backup_dedup"
REF_DIR.mkdir(exist_ok=True)

PREFIXES = [
    r"^planta\s+solar\s+fotovoltaica\s+",
    r"^planta\s+solar\s+",
    r"^planta\s+fotovoltaica\s+",
    r"^parque\s+fotovoltaico\s+",
    r"^parque\s+solar\s+fotovoltaico\s+",
    r"^parque\s+solar\s+",
    r"^parque\s+e[oó]lico\s+convencional\s+",
    r"^parque\s+e[oó]lico\s+",
    r"^instalaci[oó]n\s+fotovoltaica\s+",
    r"^instalaci[oó]n\s+solar\s+fotovoltaica\s+",
    r"^instalaci[oó]n\s+solar\s+",
    r"^central\s+fotovoltaica\s+",
    r"^central\s+solar\s+",
    r"^central\s+e[oó]lica\s+",
    r"^proyecto\s+fotovoltaico\s+",
    r"^proyecto\s+e[oó]lico\s+",
    r"^proyecto\s+solar\s+",
    r"^huerta\s+solar\s+",
    r"^pf\s+",
    r"^pfv\s+",
    r"^fv\s+",
]

def normalize_name(name):
    if not name:
        return ""
    n = name.lower().strip()
    for p in PREFIXES:
        n2 = re.sub(p, "", n)
        if n2 != n:
            return n2.strip()
    return n

def tecnologia_bucket(tec):
    if not tec:
        return "unknown"
    t = tec.lower()
    if any(x in t for x in ["fotovoltai", "solar", "fv", "pfv"]):
        return "solar"
    if any(x in t for x in ["eolic", "eolic", "viento", "wind"]):
        return "eolica"
    if any(x in t for x in ["bess", "bateri", "almacen"]):
        return "bess"
    return "otro"

def canonical_name(raw_names):
    """Prefiere nombres con mas palabras y sin abreviaturas (PF, FV, PFV)."""
    def score(nm):
        n_words = len(nm.split())
        is_abbr = bool(re.match(r"^(?:pf|pfv|fv|fvs)\s", nm.lower()))
        return (-n_words, is_abbr, nm.lower())
    return sorted(raw_names, key=score)[0]

def dedup_key_url(item):
    url = (item.get("url") or "").strip()
    return url if url else None

def dedup_key_titulo(item):
    url = (item.get("url") or "").strip()
    if url:
        return None
    titulo = (item.get("titulo_original") or "")[:120].strip()
    boletin = item.get("boletin", "")
    return (boletin, titulo) if titulo else None

# Boletines that re-publish the same anuncio on many consecutive days
# (PDF stays accessible via persistent URL in their catalog pages)
_BOLR_LIKE = {"BOLR", "BON"}

def dedup_key_crossurl(item):
    """
    Catches BOLR-style duplicates: same anuncio scraped on different dates
    with same or different URL. Normalises titulo, strips date prefix.
    Returns None for boletines not known to have this problem.
    """
    boletin = item.get("boletin","")
    if boletin not in _BOLR_LIKE:
        return None
    titulo = (item.get("titulo_original") or "").strip()
    if not titulo:
        return None
    # Strip leading date phrase so same anuncio matches across re-pub dates
    titulo_norm = re.sub(
        r'^(?:Anuncio|Resolución|Orden|Notificación)\s+de\s+\d+\s+de\s+\w+\s+de\s+\d{4}[,\s]*',
        '', titulo, flags=re.IGNORECASE).strip()
    key = titulo_norm[:150]
    return (boletin, "__cu__", key) if len(key) > 15 else None

def _prefer(a_id, b_id):
    """True if a is preferred over b (anu- format beats date-based id)."""
    return ("-anu-" in a_id) or ("-anu-" not in b_id and a_id < b_id)

def load_all():
    files = sorted(OUT_DIR.glob("energy_extraido_*.json"))
    result = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        result.append((f, data))
    return result

def run(dry=False):
    print("Cargando JSONs de output/ ...")
    all_files = load_all()
    print("  {} archivos encontrados".format(len(all_files)))

    # Paso 1: recopilar nombres para normalizacion por (norm, tec_bucket)
    grupo_raw = defaultdict(set)
    for _, data in all_files:
        for it in data.get("resultados", []):
            if not it.get("es_energetico") or not isinstance(it.get("datos"), dict):
                continue
            d = it["datos"]
            nm  = (d.get("nombre_proyecto") or "").strip()
            tec = (d.get("tecnologia") or "").strip()
            norm = normalize_name(nm)
            if norm and nm:
                grupo_raw[(norm, tecnologia_bucket(tec))].add(nm)

    nombre_canonico = {}
    grupos_multiples = {}
    for (norm, tbucket), raw_names in grupo_raw.items():
        if len(raw_names) > 1:
            canon = canonical_name(list(raw_names))
            for rn in raw_names:
                if rn != canon:
                    nombre_canonico[rn] = canon
            grupos_multiples[(norm, tbucket)] = {
                "raw": sorted(raw_names), "canon": canon, "bucket": tbucket
            }

    print("\nGrupos con variantes de nombre (misma tecnologia):")
    for (norm, tb), info in sorted(grupos_multiples.items()):
        print("  [{}]  {}  -->  '{}'".format(tb, info["raw"], info["canon"]))

    # Paso 1b: pre-pass para cross-URL (BOLR mismo anuncio distintas fechas/URLs)
    # Agrupar por clave crossurl → elegir winner (anu- preferido, si no: más reciente)
    crossurl_loser_ids = set()
    crossurl_groups = defaultdict(list)
    for f, data in all_files:
        fecha = data.get("fecha","")
        for it in data.get("resultados",[]):
            if not it.get("es_energetico"): continue
            kx = dedup_key_crossurl(it)
            if kx:
                crossurl_groups[kx].append((fecha, it.get("id",""), it))
    for kx, members in crossurl_groups.items():
        if len(members) < 2: continue
        # Sort: anu- first, then by date ascending (keep oldest non-anu as fallback)
        members.sort(key=lambda x: (0 if "-anu-" in x[1] else 1, x[0]))
        winner_id = members[0][1]
        for fecha, iid, _ in members[1:]:
            crossurl_loser_ids.add(iid)
    print(f"  Cross-URL duplicados identificados: {len(crossurl_loser_ids)}")

    # Paso 2: recorrer cronologicamente, marcar duplicados
    seen_urls    = {}
    seen_titulos = {}
    discarded    = []
    total_before = 0
    total_after  = 0

    for f, data in all_files:
        resultados = data.get("resultados", [])
        total_before += len(resultados)
        new_resultados = []
        fecha = data.get("fecha", "")

        for it in resultados:
            item_id = it.get("id", "?")
            is_en = it.get("es_energetico") and isinstance(it.get("datos"), dict)

            if is_en:
                # Cross-URL loser (BOLR same-anuncio different date/url)
                if item_id in crossurl_loser_ids:
                    discarded.append({
                        "razon": "TITULO_CROSS_URL",
                        "id": item_id, "fecha": fecha,
                        "url": (it.get("url") or "")[:120],
                        "nombre_proyecto": it["datos"].get("nombre_proyecto",""),
                        "primera_vez": "-", "primer_id": "-",
                    })
                    continue

                ku = dedup_key_url(it)
                if ku:
                    if ku in seen_urls:
                        prev = seen_urls[ku]
                        discarded.append({
                            "razon": "URL_DUPLICADA",
                            "id": item_id, "fecha": fecha,
                            "url": ku[:120],
                            "nombre_proyecto": it["datos"].get("nombre_proyecto", ""),
                            "primera_vez": prev["fecha"],
                            "primer_id": prev["id"],
                        })
                        continue
                    seen_urls[ku] = {"file": str(f), "id": item_id, "fecha": fecha}

                kt = dedup_key_titulo(it)
                if kt:
                    if kt in seen_titulos:
                        prev = seen_titulos[kt]
                        discarded.append({
                            "razon": "TITULO_DUPLICADO_SIN_URL",
                            "id": item_id, "fecha": fecha,
                            "url": "",
                            "nombre_proyecto": it["datos"].get("nombre_proyecto", ""),
                            "primera_vez": prev["fecha"],
                            "primer_id": prev["id"],
                        })
                        continue
                    seen_titulos[kt] = {"file": str(f), "id": item_id, "fecha": fecha}

                nm = (it["datos"].get("nombre_proyecto") or "").strip()
                if nm in nombre_canonico:
                    it["datos"]["_nombre_original"] = nm
                    it["datos"]["nombre_proyecto"]  = nombre_canonico[nm]

            new_resultados.append(it)

        data["resultados"] = new_resultados
        data["total"] = len(new_resultados)
        total_after += len(new_resultados)

    print("\nDEDUP RESULTADO:")
    print("  Items antes   : {:,}".format(total_before))
    print("  Items despues : {:,}".format(total_after))
    print("  Eliminados    : {:,}".format(total_before - total_after))
    by_razon = defaultdict(int)
    for d in discarded:
        by_razon[d["razon"]] += 1
    for r, c in by_razon.items():
        print("    {}: {}".format(r, c))
    print("  Nombres normalizados: {}".format(len(nombre_canonico)))

    if dry:
        print("\n[DRY RUN] No se escriben cambios.")
        url_disc = [d for d in discarded if d["razon"] == "URL_DUPLICADA"]
        by_url = defaultdict(list)
        for d in url_disc:
            by_url[d["url"]].append(d["fecha"])
        print("\nURLs con duplicados:")
        for url, fechas in sorted(by_url.items(), key=lambda x: -len(x[1])):
            print("  x{}  {}".format(len(fechas), url[:90]))
        return

    BACKUP_DIR.mkdir(exist_ok=True)
    print("\nEscribiendo cambios (backup en backup_dedup/) ...")
    for f, data in all_files:
        shutil.copy2(f, BACKUP_DIR / f.name)
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    print("  {} archivos actualizados".format(len(all_files)))

    seen_path = REF_DIR / "seen_urls.json"
    with open(seen_path, "w", encoding="utf-8") as fh:
        json.dump(seen_urls, fh, ensure_ascii=False, indent=2)
    print("  seen_urls.json: {} URLs registradas".format(len(seen_urls)))

    if discarded:
        report_path = REF_DIR / "dedup_report.csv"
        with open(report_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "razon", "id", "fecha", "primera_vez", "primer_id",
                "nombre_proyecto", "url"
            ])
            w.writeheader()
            w.writerows(discarded)
        print("  dedup_report.csv: {} filas".format(len(discarded)))

    print("\nFIN.")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true",
                   help="Solo mostrar estadisticas, no modificar archivos")
    args = p.parse_args()
    run(dry=args.dry)
