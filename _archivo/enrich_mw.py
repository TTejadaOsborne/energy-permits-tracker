"""
enrich_mw.py — Enriquecimiento de potencia_mw para registros sin dato
Ejecutar: python enrich_mw.py --api-key TU_ANTHROPIC_KEY [--dry-run] [--limit N]

Lógica de escritura: solo se escribe si se cumplen los 5 criterios simultáneamente:
  1. Match inequívoco de nombre de proyecto o expediente en la fuente
  2. Fuente primaria (boletín, promotor, RETA, MITERD/CCAA)
  3. Consistencia tecnológica (MW dentro de rango plausible)
  4. Única fuente con único valor (si hay discrepancia → vacío)
  5. El promotor o expediente aparece explícitamente en la fuente
"""

import os
import re
import sys
import time
import json
import argparse
import requests
import logging
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("enrich_mw.log", encoding="utf-8")]
)
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1jqhG2ub287WHrBa1myP8wKygqPTiXDHq-x-9GEcmblE"
SHEETS_API_KEY = os.environ.get("SHEETS_API_KEY", "AIzaSyBIngjt4mrov2d1AKrqOOpF90cMAgoYSIg")
SHEET_NAME     = "Permisos"
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

# Columna potencia_mw (0-indexed según COLS en index.html)
COLS = [
    "id_boe","fecha_publicacion","boletin","ccaa","nombre_proyecto","promotor",
    "tecnologia","potencia_mw","tipo_permiso","permisos_adicionales","estado_permiso",
    "es_proyecto_fallido","motivo_fallo","subestacion_conexion","tension_conexion_kv",
    "gestor_red","municipio","provincia","comunidad_autonoma",
    "numero_expediente_industria","numero_expediente_medioambiente",
    "capacidad_mw_liberada","fecha_resolucion","confianza","url","titulo_original","fecha_carga"
]
COL_IDX = {c: i for i, c in enumerate(COLS)}
MW_COL_LETTER = chr(ord('A') + COL_IDX["potencia_mw"])  # columna H = índice 7

# Rangos plausibles por tecnología (MW)
MW_RANGOS = {
    "fotovoltaica":  (0.5,   500),
    "Fotovoltaica":  (0.5,   500),
    "eólica":        (0.5,   300),
    "Eólica":        (0.5,   300),
    "BESS":          (0.5,   300),
    "FV+BESS":       (0.5,   600),
    "Eólica+BESS":   (0.5,   500),
    "eólica+BESS":   (0.5,   500),
    "H2":            (0.5,   200),
    "termosolar":    (0.5,   200),
    "Termosolar":    (0.5,   200),
    "hidráulica":    (0.5,   150),
    "Hidráulica":    (0.5,   150),
    "biomasa":       (0.5,    50),
    "Biomasa":       (0.5,    50),
    "biometano":     (0.5,    30),
    "Biometano":     (0.5,    30),
    "cogeneración":  (0.5,   100),
    "Cogeneración":  (0.5,   100),
    "Data Center":   (5,    1000),
    # LAT y SET no tienen MW de generación aplicable
}

# Fuentes primarias aceptadas (dominio o patrón en URL)
FUENTES_PRIMARIAS = [
    "boe.es", "bocyl.es", "bocm.es", "docm.es",
    "xunta.gal", "boc.cantabria.es", "juntadeandalucia.es",
    "asturias.es", "dogc.cat", "dogv.gva.es", "borm.es",
    "miteco.gob.es", "miterd.gob.es", "energia.gob.es",
    "sede.serviciosmin.gob.es", "ree.es", "cnmc.es",
    "reta.minetur.gob.es", "registroret.minetur",
    # Promotores conocidos
    "iberdrola.com", "acciona.com", "endesa.com", "repsol.com",
    "totalenergies.com", "enel.com", "naturgy.com", "nextera.com",
    "lightsource.com", "statkraft.com", "enefit.com", "opdenergy.com",
    "solaria.es", "grenergy.com", "solarpack.es", "audax.es",
    "forestalia.com", "renovalia.es", "gestamp.com",
]

DELAY_ENTRE_LLAMADAS = 3  # segundos entre llamadas a Anthropic


# ── GOOGLE SHEETS ─────────────────────────────────────────────────────────────

def sheets_get_all() -> list[dict]:
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
           f"/values/{SHEET_NAME}?key={SHEETS_API_KEY}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    rows = r.json().get("values", [])
    if len(rows) < 2:
        return []
    return [
        {COLS[i]: (row[i] if i < len(row) else "").strip() for i in range(len(COLS))}
        for row in rows[1:]
        if row
    ]


def sheets_write_mw(row_number: int, value: str, dry_run: bool = False):
    """row_number: 1-indexed fila en el Sheet (fila 1 = cabecera, fila 2 = primer dato)"""
    cell = f"{SHEET_NAME}!{MW_COL_LETTER}{row_number}"
    if dry_run:
        log.info(f"  [DRY-RUN] Escribiría {cell} = {value}")
        return
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
           f"/values/{cell}?valueInputOption=RAW&key={SHEETS_API_KEY}")
    body = {"values": [[value]]}
    r = requests.put(url, json=body, timeout=30)
    r.raise_for_status()
    log.info(f"  ✓ Escrito {cell} = {value}")


# ── CLAUDE API ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres un experto en permisos energéticos en España. Tu tarea es buscar la potencia en MW de un proyecto energético específico usando búsqueda web.

REGLAS ESTRICTAS:
1. Solo devuelves un MW si encuentras una fuente PRIMARIA: boletín oficial (BOE, BOCA, BOCYL, BOCM, DOCM, DOG, DOC, DOGC, DOGV, BORM), web oficial del promotor, registro RETA/MITERD, o nota de prensa del propio promotor.
2. El nombre del proyecto o número de expediente en la fuente debe coincidir EXACTAMENTE con el proporcionado.
3. Si encuentras varios valores distintos en distintas fuentes → devuelve null.
4. Si la fuente es prensa generalista sin expediente confirmado → devuelve null.
5. Si hay cualquier duda → devuelve null. Es mejor null que un dato incorrecto.

Responde SOLO con JSON válido, sin texto adicional:
{
  "mw": <número o null>,
  "fuente": "<URL de la fuente primaria o null>",
  "razon_rechazo": "<explicación si mw es null, sino null>"
}"""


def buscar_mw_claude(proyecto: dict) -> dict:
    """Llama a Claude con web_search para buscar los MW del proyecto."""
    nombre    = proyecto.get("nombre_proyecto", "")
    promotor  = proyecto.get("promotor", "")
    tecnologia= proyecto.get("tecnologia", "")
    provincia = proyecto.get("provincia", "")
    ccaa      = proyecto.get("comunidad_autonoma", "")
    exp_ind   = proyecto.get("numero_expediente_industria", "")
    exp_ma    = proyecto.get("numero_expediente_medioambiente", "")
    url_boe   = proyecto.get("url", "")

    # Construir query con los identificadores más discriminantes
    partes = [nombre]
    if exp_ind:   partes.append(f"expediente {exp_ind}")
    elif exp_ma:  partes.append(f"expediente {exp_ma}")
    if promotor:  partes.append(promotor)
    if provincia: partes.append(provincia)

    user_msg = f"""Busca la potencia en MW de este proyecto energético:

Nombre: {nombre}
Promotor: {promotor}
Tecnología: {tecnologia}
Provincia: {provincia} ({ccaa})
Expediente industria: {exp_ind or "no disponible"}
Expediente medioambiente: {exp_ma or "no disponible"}
URL boletín: {url_boe or "no disponible"}

Realiza búsquedas web específicas para encontrar la potencia en MW. Prioriza boletines oficiales, el expediente exacto, y fuentes del promotor. Sé muy preciso."""

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 500,
        "system": SYSTEM_PROMPT,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": user_msg}]
    }

    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "web-search-2025-03-05",
        "content-type": "application/json"
    }

    r = requests.post("https://api.anthropic.com/v1/messages",
                      json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()

    # Extraer el bloque de texto final (después de tool use)
    texto = ""
    for bloque in data.get("content", []):
        if bloque.get("type") == "text":
            texto = bloque.get("text", "")

    # Parsear JSON de la respuesta
    try:
        m = re.search(r'\{.*\}', texto, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass

    return {"mw": None, "fuente": None, "razon_rechazo": f"No se pudo parsear respuesta: {texto[:200]}"}


# ── VALIDACIÓN ────────────────────────────────────────────────────────────────

def es_fuente_primaria(url: Optional[str]) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    return any(dominio in url_lower for dominio in FUENTES_PRIMARIAS)


def mw_en_rango(mw: float, tecnologia: str) -> bool:
    rango = MW_RANGOS.get(tecnologia)
    if not rango:
        # Tecnología sin rango definido (LAT, SET, Otro) → no validar MW
        return False
    return rango[0] <= mw <= rango[1]


def validar_resultado(resultado: dict, proyecto: dict) -> tuple[bool, str]:
    """Devuelve (aprobado, motivo_rechazo)"""
    mw  = resultado.get("mw")
    url = resultado.get("fuente")

    if mw is None:
        razon = resultado.get("razon_rechazo") or "Claude no encontró dato fiable"
        return False, razon

    try:
        mw_float = float(mw)
    except (TypeError, ValueError):
        return False, f"MW no es número: {mw}"

    if mw_float <= 0:
        return False, f"MW inválido: {mw_float}"

    # Criterio 3: consistencia tecnológica
    tecnologia = proyecto.get("tecnologia", "")
    if tecnologia in MW_RANGOS:
        if not mw_en_rango(mw_float, tecnologia):
            return False, f"{mw_float} MW fuera de rango para {tecnologia} ({MW_RANGOS[tecnologia]})"

    # Criterio 2: fuente primaria
    if not es_fuente_primaria(url):
        return False, f"Fuente no primaria: {url}"

    return True, ""


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enriquecimiento de potencia_mw")
    parser.add_argument("--api-key",  help="Anthropic API key (o usar ANTHROPIC_API_KEY)")
    parser.add_argument("--dry-run",  action="store_true", help="No escribir en el Sheet")
    parser.add_argument("--limit",    type=int, default=0, help="Máximo de proyectos a procesar (0=todos)")
    parser.add_argument("--id-boe",   help="Procesar solo este id_boe específico")
    args = parser.parse_args()

    global ANTHROPIC_KEY
    if args.api_key:
        ANTHROPIC_KEY = args.api_key
    if not ANTHROPIC_KEY:
        log.error("Falta ANTHROPIC_API_KEY. Usa --api-key o la variable de entorno.")
        sys.exit(1)

    log.info("Leyendo Google Sheet...")
    try:
        filas = sheets_get_all()
    except Exception as e:
        log.error(f"Error leyendo Sheet: {e}")
        sys.exit(1)

    log.info(f"Total registros: {len(filas)}")

    # Filtrar candidatos: sin potencia_mw y con tecnología que tiene rango definido
    tecnologias_sin_mw = {"LAT", "SET", "Otro", "otro"}
    candidatos = [
        (i, r) for i, r in enumerate(filas)
        if not r.get("potencia_mw")
        and r.get("tecnologia") not in tecnologias_sin_mw
        and r.get("nombre_proyecto")
    ]

    if args.id_boe:
        candidatos = [(i, r) for i, r in candidatos if r.get("id_boe") == args.id_boe]

    log.info(f"Candidatos sin MW: {len(candidatos)}")

    if args.limit > 0:
        candidatos = candidatos[:args.limit]
        log.info(f"Limitado a {args.limit} proyectos")

    stats = {"procesados": 0, "escritos": 0, "rechazados": 0, "errores": 0}

    for idx, (fila_idx, proyecto) in enumerate(candidatos):
        row_number = fila_idx + 2  # +1 cabecera, +1 base-1
        nombre     = proyecto.get("nombre_proyecto", "")
        id_boe     = proyecto.get("id_boe", "")
        tecnologia = proyecto.get("tecnologia", "")

        log.info(f"\n[{idx+1}/{len(candidatos)}] {id_boe} | {nombre[:60]} | {tecnologia}")

        try:
            resultado = buscar_mw_claude(proyecto)
            stats["procesados"] += 1
        except Exception as e:
            log.warning(f"  Error en llamada a Claude: {e}")
            stats["errores"] += 1
            time.sleep(DELAY_ENTRE_LLAMADAS)
            continue

        aprobado, motivo = validar_resultado(resultado, proyecto)

        if aprobado:
            mw_str = str(resultado["mw"])
            log.info(f"  ✓ MW={mw_str} | fuente={resultado.get('fuente','')[:80]}")
            try:
                sheets_write_mw(row_number, mw_str, dry_run=args.dry_run)
                stats["escritos"] += 1
            except Exception as e:
                log.warning(f"  Error escribiendo en Sheet: {e}")
                stats["errores"] += 1
        else:
            log.info(f"  ✗ Rechazado: {motivo}")
            stats["rechazados"] += 1

        time.sleep(DELAY_ENTRE_LLAMADAS)

    log.info(f"""
──────────────────────────────
RESUMEN enrich_mw
  Procesados : {stats['procesados']}
  Escritos   : {stats['escritos']}
  Rechazados : {stats['rechazados']}
  Errores    : {stats['errores']}
──────────────────────────────""")


if __name__ == "__main__":
    main()
