"""
validate_extraction.py — Validador de calidad de extracción vs Excel de referencia

Compara los datos extraídos por el pipeline (Google Sheet) contra un Excel de referencia
externo para identificar errores sistemáticos y generar recomendaciones de mejora del prompt.

Uso:
  python validate_extraction.py --excel filtered_projects_2026-05-12.xlsx
  python validate_extraction.py --excel filtered_projects.xlsx --output informe_validacion.json
  python validate_extraction.py --excel filtered_projects.xlsx --api-key TU_KEY  (genera recomendaciones IA)
"""

import os
import re
import sys
import json
import argparse
import unicodedata
import logging
import requests
from typing import Optional
from difflib import SequenceMatcher
from collections import defaultdict
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

try:
    import pandas as pd
except ImportError:
    print("pip install pandas openpyxl")
    sys.exit(1)

# ── CONFIG ────────────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1jqhG2ub287WHrBa1myP8wKygqPTiXDHq-x-9GEcmblE"
SHEETS_API_KEY = os.environ.get("SHEETS_API_KEY", "AIzaSyBIngjt4mrov2d1AKrqOOpF90cMAgoYSIg")
SHEET_NAME     = "Permisos"

COLS_SHEET = [
    "id_boe","fecha_publicacion","boletin","ccaa","nombre_proyecto","promotor",
    "tecnologia","potencia_mw","tipo_permiso","permisos_adicionales","estado_permiso",
    "es_proyecto_fallido","motivo_fallo","subestacion_conexion","tension_conexion_kv",
    "gestor_red","municipio","provincia","comunidad_autonoma",
    "numero_expediente_industria","numero_expediente_medioambiente",
    "capacidad_mw_liberada","fecha_resolucion","confianza","url","titulo_original","fecha_carga"
]

# Mapeo Excel referencia → campos Sheet
# Formato: campo_sheet: (columna_excel, tipo_comparacion)
# tipos: "texto_fuzzy" | "texto_exacto" | "mw" | "estado" | "tecnologia" | "fecha" | "multi_valor"
MAPEO_CAMPOS = {
    "nombre_proyecto":   ("Resumen",                  "texto_fuzzy"),
    "promotor":          ("Promotor",                 "texto_fuzzy"),
    "potencia_mw":       ("Unidad declarada",          "mw"),
    "provincia":         ("Provincia",                "texto_fuzzy"),
    "municipio":         ("Ciudad",                   "texto_fuzzy"),
    "comunidad_autonoma":("Comunidad",                "texto_fuzzy"),
    "estado_permiso":    ("Favorable / Desfavorable", "estado"),
    "tipo_permiso":      ("Tipo de permiso",           "multi_valor"),
    "tecnologia":        ("Tecnología",               "tecnologia"),
    "fecha_resolucion":  ("Fecha Resolución",          "fecha"),
    "url":               ("Link",                     "texto_exacto"),
}

# Normalización de tecnología: Excel → Sheet
TECH_MAP = {
    "solar":               "Fotovoltaica",
    "eólico":              "Eólica",
    "eolico":              "Eólica",
    "hibridaciones":       "FV+BESS",
    "hibridaciónes":       "FV+BESS",
    "almacenamiento":      "BESS",
    "hidrógeno":           "H2",
    "hidrogeno":           "H2",
    "centro de datos":     "Data Center",
    "biometano":           "Biometano",
    "t&d":                 "LAT",
    "otras":               "Otro",
    "autoconsumo":         "Fotovoltaica",
    "infraestrucuturas de gas": "Biometano",
}

# Normalización de estado: Excel → Sheet
ESTADO_MAP = {
    "favorable":        ["favorable", "otorgado", "no_necesario"],
    "desfavorable":     ["desfavorable", "denegado"],
    "desistimiento":    ["desistido"],
    "no se somete a dia": ["no_necesario", "favorable"],
    "se somete a dia":  ["en_tramitacion", "informacion_publica"],
}

# Umbral de similitud para matching de proyectos
MATCH_THRESHOLD = 0.55
MATCH_THRESHOLD_ALTO = 0.75


# ── UTILIDADES ────────────────────────────────────────────────────────────────

def normalizar(s: str) -> str:
    if not s:
        return ""
    s = str(s).lower().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def similitud(a: str, b: str) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def extraer_mw(texto: str) -> Optional[float]:
    if not texto:
        return None
    texto = str(texto).replace(',', '.')
    # Extraer el primer valor MW (ignorar MWh)
    m = re.search(r'([\d.]+)\s*MW(?!h)', texto, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def normalizar_url(url: str) -> str:
    if not url:
        return ""
    url = url.lower().strip().rstrip('/')
    # Quitar parámetros de query menores
    url = re.sub(r'\?.*$', '', url)
    return url


def similitud_url(url_sheet: str, url_excel: str) -> float:
    """Compara URLs: exacto=1.0, mismo path=0.9, mismo dominio+parte=0.6"""
    if not url_sheet or not url_excel:
        return 0.0
    us = normalizar_url(url_sheet)
    ue = normalizar_url(url_excel)
    if us == ue:
        return 1.0
    # Mismo dominio y path parcial
    if us[:60] == ue[:60]:
        return 0.9
    # Mismo dominio
    dom_s = re.search(r'https?://([^/]+)', us)
    dom_e = re.search(r'https?://([^/]+)', ue)
    if dom_s and dom_e and dom_s.group(1) == dom_e.group(1):
        return similitud(us, ue) * 0.8
    return 0.0


# ── CARGA DE DATOS ────────────────────────────────────────────────────────────

def cargar_sheet() -> list[dict]:
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}"
           f"/values/{SHEET_NAME}?key={SHEETS_API_KEY}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    rows = r.json().get("values", [])
    if len(rows) < 2:
        return []
    return [
        {COLS_SHEET[i]: (row[i] if i < len(row) else "").strip()
         for i in range(len(COLS_SHEET))}
        for row in rows[1:] if row
    ]


def cargar_excel(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df = df.fillna("")
    return df


# ── MATCHING ──────────────────────────────────────────────────────────────────

def encontrar_match(registro_sheet: dict, df_excel: pd.DataFrame) -> tuple[Optional[pd.Series], float, str]:
    """
    Busca el registro del Excel que mejor corresponde a un registro del Sheet.
    Devuelve (fila_excel, score, metodo_match)
    """
    url_sheet = registro_sheet.get("url", "")
    nombre_sheet = registro_sheet.get("nombre_proyecto", "")
    promotor_sheet = registro_sheet.get("promotor", "")
    provincia_sheet = registro_sheet.get("provincia", "")

    mejor_score = 0.0
    mejor_fila = None
    mejor_metodo = ""

    for _, fila in df_excel.iterrows():
        url_excel = str(fila.get("Link", ""))
        resumen_excel = str(fila.get("Resumen", ""))
        promotor_excel = str(fila.get("Promotor", ""))
        provincia_excel = str(fila.get("Provincia", ""))

        # Método 1: URL directa (máxima fiabilidad)
        score_url = similitud_url(url_sheet, url_excel)
        if score_url >= 0.9:
            return fila, score_url, "url_exacta"

        # Método 2: Nombre + Promotor + Provincia
        score_nombre = similitud(nombre_sheet, resumen_excel)
        score_prov = 1.0 if normalizar(provincia_sheet) == normalizar(provincia_excel) else 0.3
        score_promotor = similitud(promotor_sheet, promotor_excel) if promotor_sheet else 0.5

        # Peso combinado: nombre 60%, provincia 25%, promotor 15%
        score_combo = score_nombre * 0.60 + score_prov * 0.25 + score_promotor * 0.15

        if score_combo > mejor_score:
            mejor_score = score_combo
            mejor_fila = fila
            mejor_metodo = f"nombre+prov+promotor ({score_nombre:.2f}/{score_prov:.2f}/{score_promotor:.2f})"

    if mejor_score >= MATCH_THRESHOLD:
        return mejor_fila, mejor_score, mejor_metodo

    return None, mejor_score, "sin_match"


# ── COMPARACIÓN DE CAMPOS ─────────────────────────────────────────────────────

def comparar_campo(campo: str, val_sheet: str, fila_excel: pd.Series,
                   col_excel: str, tipo: str) -> dict:
    val_excel = str(fila_excel.get(col_excel, "")).strip()

    resultado = {
        "campo": campo,
        "valor_sheet": val_sheet,
        "valor_referencia": val_excel,
        "tipo": tipo,
        "correcto": None,
        "score": None,
        "nota": ""
    }

    if not val_excel:
        resultado["correcto"] = None
        resultado["nota"] = "Sin referencia"
        return resultado

    if tipo == "texto_fuzzy":
        score = similitud(val_sheet, val_excel)
        resultado["score"] = round(score, 2)
        resultado["correcto"] = score >= MATCH_THRESHOLD_ALTO
        if score < MATCH_THRESHOLD_ALTO:
            resultado["nota"] = f"Similitud baja: {score:.2f}"

    elif tipo == "texto_exacto":
        score = similitud_url(val_sheet, val_excel) if campo == "url" else (1.0 if val_sheet == val_excel else 0.0)
        resultado["score"] = round(score, 2)
        resultado["correcto"] = score >= 0.85

    elif tipo == "mw":
        mw_sheet = extraer_mw(val_sheet)
        mw_excel = extraer_mw(val_excel)
        if mw_sheet is None and not val_sheet:
            resultado["correcto"] = None
            resultado["nota"] = "Vacío en Sheet"
        elif mw_sheet is None:
            resultado["correcto"] = False
            resultado["nota"] = f"No parseable: '{val_sheet}'"
        elif mw_excel is None:
            resultado["correcto"] = None
            resultado["nota"] = f"Referencia no en MW: '{val_excel}'"
        else:
            delta_pct = abs(mw_sheet - mw_excel) / max(mw_excel, 0.01) * 100
            resultado["score"] = round(delta_pct, 1)
            resultado["correcto"] = delta_pct <= 5.0  # tolerancia 5%
            resultado["nota"] = f"Sheet={mw_sheet} MW, Ref={mw_excel} MW, Δ={delta_pct:.1f}%"

    elif tipo == "estado":
        estados_validos = ESTADO_MAP.get(normalizar(val_excel), [])
        resultado["correcto"] = normalizar(val_sheet) in [normalizar(e) for e in estados_validos]
        if not resultado["correcto"]:
            resultado["nota"] = f"Sheet='{val_sheet}' no encaja con ref='{val_excel}'"

    elif tipo == "tecnologia":
        tech_ref = TECH_MAP.get(normalizar(val_excel), val_excel)
        resultado["correcto"] = normalizar(val_sheet) == normalizar(tech_ref)
        if not resultado["correcto"]:
            resultado["nota"] = f"Sheet='{val_sheet}', Ref mapeada='{tech_ref}'"

    elif tipo == "multi_valor":
        # tipo_permiso: el Excel tiene varios permisos separados por coma
        tipos_excel = {normalizar(t.strip()) for t in val_excel.split(",")}
        tipo_sheet_norm = normalizar(val_sheet)
        resultado["correcto"] = any(tipo_sheet_norm in t or t in tipo_sheet_norm
                                    for t in tipos_excel)
        if not resultado["correcto"]:
            resultado["nota"] = f"Sheet='{val_sheet}' no en [{val_excel}]"

    elif tipo == "fecha":
        # Comparar fecha ignorando formato
        def norm_fecha(f):
            f = str(f).strip()
            m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', f)
            if m:
                d, mo, y = m.groups()
                y = "20" + y if len(y) == 2 else y
                return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
            return f
        resultado["correcto"] = norm_fecha(val_sheet) == norm_fecha(val_excel)
        if not resultado["correcto"]:
            resultado["nota"] = f"Sheet='{val_sheet}', Ref='{val_excel}'"

    return resultado


# ── ANÁLISIS DE ERRORES ───────────────────────────────────────────────────────

def analizar_errores(comparaciones: list[dict]) -> dict:
    """Agrupa errores por campo y detecta patrones sistemáticos."""
    por_campo = defaultdict(lambda: {"total": 0, "correctos": 0, "incorrectos": 0,
                                     "sin_dato": 0, "sin_ref": 0, "errores": []})

    for comp in comparaciones:
        campo = comp["campo"]
        por_campo[campo]["total"] += 1

        if comp["correcto"] is None:
            if "Vacío" in (comp.get("nota") or ""):
                por_campo[campo]["sin_dato"] += 1
            else:
                por_campo[campo]["sin_ref"] += 1
        elif comp["correcto"]:
            por_campo[campo]["correctos"] += 1
        else:
            por_campo[campo]["incorrectos"] += 1
            por_campo[campo]["errores"].append({
                "sheet": comp["valor_sheet"],
                "ref":   comp["valor_referencia"],
                "nota":  comp.get("nota", "")
            })

    # Calcular precisión por campo
    resumen = {}
    for campo, stats in por_campo.items():
        evaluables = stats["total"] - stats["sin_ref"]
        con_dato = evaluables - stats["sin_dato"]
        precision = stats["correctos"] / max(con_dato, 1)
        vaciado_pct = stats["sin_dato"] / max(evaluables, 1)

        resumen[campo] = {
            "total_comparados": evaluables,
            "con_dato_sheet": con_dato,
            "precision": round(precision, 3),
            "vaciado_pct": round(vaciado_pct, 3),
            "errores_muestra": stats["errores"][:5],  # hasta 5 ejemplos
        }

    return resumen


def generar_recomendaciones_texto(resumen_campos: dict, n_matches: int, n_total: int) -> str:
    """Genera recomendaciones legibles sin necesidad de llamar a la API."""
    lineas = []
    lineas.append("=" * 70)
    lineas.append("INFORME DE CALIDAD DE EXTRACCIÓN")
    lineas.append(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lineas.append("=" * 70)
    lineas.append(f"\nMatches encontrados: {n_matches}/{n_total} registros del Sheet")
    lineas.append("")

    # Ordenar campos por precisión ascendente (peores primero)
    campos_ordenados = sorted(
        resumen_campos.items(),
        key=lambda x: x[1]["precision"]
    )

    lineas.append("PRECISIÓN POR CAMPO (peores primero):")
    lineas.append("-" * 50)
    for campo, stats in campos_ordenados:
        if stats["total_comparados"] == 0:
            continue
        prec = stats["precision"] * 100
        vac  = stats["vaciado_pct"] * 100
        icono = "✓" if prec >= 80 else "⚠" if prec >= 50 else "✗"
        lineas.append(f"  {icono} {campo:<30} precisión={prec:5.1f}%  vacíos={vac:5.1f}%  (n={stats['total_comparados']})")

    lineas.append("\nDETALLE DE ERRORES POR CAMPO:")
    lineas.append("-" * 50)
    for campo, stats in campos_ordenados:
        if not stats["errores_muestra"]:
            continue
        prec = stats["precision"] * 100
        if prec >= 90:
            continue  # No mostrar campos buenos
        lineas.append(f"\n  [{campo}] — precisión {prec:.0f}%")
        for e in stats["errores_muestra"]:
            lineas.append(f"    Sheet:     '{e['sheet']}'")
            lineas.append(f"    Referencia: '{e['ref']}'")
            if e['nota']:
                lineas.append(f"    Nota:      {e['nota']}")
            lineas.append("")

    lineas.append("\nRECOMENDACIONES PARA EL PROMPT DEL EXTRACTOR:")
    lineas.append("-" * 50)

    recomendaciones = []

    for campo, stats in resumen_campos.items():
        prec = stats["precision"]
        vac  = stats["vaciado_pct"]
        errores = stats["errores_muestra"]

        if prec < 0.5 and stats["total_comparados"] >= 3:
            recomendaciones.append(
                f"CRÍTICO [{campo}]: precisión {prec*100:.0f}%. "
                f"Revisar instrucción de extracción. "
                f"Ejemplo de error: {errores[0] if errores else 'ver log'}"
            )
        elif vac > 0.4 and stats["total_comparados"] >= 3:
            recomendaciones.append(
                f"VACÍOS [{campo}]: {vac*100:.0f}% de registros sin dato. "
                f"El extractor no está encontrando este campo con frecuencia."
            )
        elif prec < 0.75 and stats["total_comparados"] >= 3:
            recomendaciones.append(
                f"MEJORA [{campo}]: precisión {prec*100:.0f}%. "
                f"Posibles falsos positivos o formato incorrecto."
            )

    if recomendaciones:
        for i, r in enumerate(recomendaciones, 1):
            lineas.append(f"  {i}. {r}")
    else:
        lineas.append("  ✓ No se detectan problemas críticos.")

    return "\n".join(lineas)


def generar_recomendaciones_ia(resumen_campos: dict, comparaciones_detalle: list,
                                api_key: str) -> str:
    """Llama a Claude para generar recomendaciones de mejora del prompt del extractor."""
    # Preparar resumen compacto para el prompt
    resumen_str = json.dumps({
        campo: {
            "precision": stats["precision"],
            "vaciado_pct": stats["vaciado_pct"],
            "errores_muestra": stats["errores_muestra"][:3]
        }
        for campo, stats in resumen_campos.items()
    }, ensure_ascii=False, indent=2)

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2000,
        "messages": [{
            "role": "user",
            "content": f"""Analiza estos resultados de validación de un extractor de datos de boletines oficiales energéticos españoles (BOE, BOCA, BOCYL, etc.) y genera recomendaciones concretas para mejorar el prompt del extractor.

El extractor usa Claude Haiku para extraer campos como: nombre_proyecto, promotor, tecnologia, potencia_mw, tipo_permiso, estado_permiso, subestacion_conexion, provincia, municipio, fecha_resolucion.

RESULTADOS DE VALIDACIÓN (precisión por campo):
{resumen_str}

Para cada campo con precisión < 80% o vaciado > 30%, proporciona:
1. Diagnóstico del problema (qué está fallando y por qué)
2. Instrucción concreta a añadir/modificar en el prompt del extractor
3. Ejemplos de casos correctos e incorrectos si los hay en los datos

Sé específico y accionable. El output se usará directamente para editar el system prompt del extractor."""
        }]
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    r = requests.post("https://api.anthropic.com/v1/messages",
                      json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    bloques = r.json().get("content", [])
    return "\n".join(b.get("text", "") for b in bloques if b.get("type") == "text")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validador de calidad de extracción")
    parser.add_argument("--excel",   required=True, help="Path al Excel de referencia")
    parser.add_argument("--output",  default="informe_validacion.json", help="Output JSON")
    parser.add_argument("--api-key", help="Anthropic API key para recomendaciones IA (opcional)")
    parser.add_argument("--sin-ia",  action="store_true", help="Solo recomendaciones en texto, sin llamada a API")
    args = parser.parse_args()

    # 1. Cargar datos
    log.info("Cargando Google Sheet...")
    try:
        registros_sheet = cargar_sheet()
    except Exception as e:
        log.error(f"Error leyendo Sheet: {e}")
        sys.exit(1)
    log.info(f"  {len(registros_sheet)} registros en Sheet")

    log.info(f"Cargando Excel de referencia: {args.excel}")
    df_excel = cargar_excel(args.excel)
    log.info(f"  {len(df_excel)} registros en Excel")

    # 2. Matching y comparación
    todas_comparaciones = []
    matches_encontrados = 0
    sin_match = []

    for i, registro in enumerate(registros_sheet):
        if i % 50 == 0:
            log.info(f"  Procesando {i}/{len(registros_sheet)}...")

        fila_excel, score, metodo = encontrar_match(registro, df_excel)

        if fila_excel is None:
            sin_match.append(registro.get("id_boe", ""))
            continue

        matches_encontrados += 1

        # Comparar cada campo mapeado
        for campo_sheet, (col_excel, tipo) in MAPEO_CAMPOS.items():
            val_sheet = registro.get(campo_sheet, "")
            comp = comparar_campo(campo_sheet, val_sheet, fila_excel, col_excel, tipo)
            comp["id_boe"]       = registro.get("id_boe", "")
            comp["match_score"]  = round(score, 2)
            comp["match_metodo"] = metodo
            todas_comparaciones.append(comp)

    log.info(f"Matches: {matches_encontrados}/{len(registros_sheet)} "
             f"({matches_encontrados/max(len(registros_sheet),1)*100:.1f}%)")
    if sin_match:
        log.info(f"Sin match ({len(sin_match)}): {sin_match[:10]}{'...' if len(sin_match)>10 else ''}")

    # 3. Analizar errores
    resumen_campos = analizar_errores(todas_comparaciones)

    # 4. Generar informe texto
    informe_texto = generar_recomendaciones_texto(
        resumen_campos, matches_encontrados, len(registros_sheet)
    )
    print("\n" + informe_texto)

    # 5. Recomendaciones IA (opcional)
    recomendaciones_ia = ""
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if api_key and not args.sin_ia:
        log.info("Generando recomendaciones con IA...")
        try:
            recomendaciones_ia = generar_recomendaciones_ia(
                resumen_campos, todas_comparaciones, api_key
            )
            print("\n" + "=" * 70)
            print("RECOMENDACIONES IA PARA EL PROMPT DEL EXTRACTOR:")
            print("=" * 70)
            print(recomendaciones_ia)
        except Exception as e:
            log.warning(f"Error generando recomendaciones IA: {e}")

    # 6. Guardar JSON completo
    output = {
        "generado": datetime.now().isoformat(),
        "registros_sheet": len(registros_sheet),
        "registros_excel": len(df_excel),
        "matches_encontrados": matches_encontrados,
        "tasa_match": round(matches_encontrados / max(len(registros_sheet), 1), 3),
        "sin_match_ids": sin_match,
        "resumen_por_campo": resumen_campos,
        "recomendaciones_ia": recomendaciones_ia,
        "comparaciones_detalle": todas_comparaciones,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"Informe guardado en {args.output}")


if __name__ == "__main__":
    main()
