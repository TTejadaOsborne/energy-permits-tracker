#!/usr/bin/env python3
"""
reclasificar_lat_set.py — Post-procesado de registros LAT/SET sin re-extraer

Reclasifica como es_energetico=False los LAT/SET que son infraestructura
de evacuación privada de promotores (no REE/distribuidoras).

Uso:
  python reclasificar_lat_set.py           # preview (sin modificar)
  python reclasificar_lat_set.py --apply   # aplica cambios a los JSONs
  python reclasificar_lat_set.py --apply --year 2024  # solo un año
"""

import json, sys, re
from pathlib import Path
from datetime import date

OUTPUT_DIR = Path(__file__).parent / "output"

# ── Promotores de red regulada ────────────────────────────────────────────────
RED_KEYWORDS = [
    'red eléctrica', 'ree ', 'r.e.e', 'red electrica',
    'i-de redes', 'ide redes', 'i-de redes eléctricas',
    'ufd distribución', 'ufd distribucion', 'ufd distribución electricidad',
    'iberdrola distribución', 'iberdrola distribucion', 'iberdrola redes',
    'endesa distribución', 'endesa distribucion', 'edistribución', 'e-distribución',
    'naturgy distribución', 'naturgy distribucion',
    'unión fenosa distribución', 'union fenosa distribucion',
    'begasa', 'viesgo', 'adif',  # adif es infraestructura pública
]

# ── Palabras que delatan evacuación privada ───────────────────────────────────
EVACUACION_KEYWORDS = [
    'evacuación', 'evacuacion', 'línea de evacuación', 'linea de evacuacion',
    'infraestructura de evacuación', 'infraestructura de evacuacion',
    'infraestructuras comunes de evacuación', 'infraestructuras comunes',
    'colectora', 'línea colectora', 'linea colectora',
    'líneas de evacuación', 'lineas de evacuacion',
    'lasat', 'lsmt',  # acrónimos frecuentes en evacuación privada
]

# ── Palabras que confirman infraestructura de red (conservar) ─────────────────
RED_INFRA_KEYWORDS = [
    'refuerzo de red', 'mallado', 'integración set', 'integracion set',
    'ampliación subestación', 'ampliacion subestacion',
    'ampliación de la subestación', 'nueva subestación', 'nueva set',
    'reforma línea', 'reforma linea', 'modificación línea', 'modificacion linea',
    'sustitución apoyo', 'sustitucion apoyo',
    'incremento de un circuito', 'nuevo circuito',
]


def es_promotor_red(promotor: str) -> bool:
    if not promotor:
        return False
    p = promotor.lower()
    return any(k in p for k in RED_KEYWORDS)


def es_gestor_red(gestor: str) -> bool:
    if not gestor:
        return False
    g = gestor.lower()
    return any(k in g for k in RED_KEYWORDS + ['ree', 'ufd', 'ide', 'i-de', 'iberdrola', 'endesa', 'naturgy', 'fenosa', 'begasa', 'viesgo'])


def tiene_evacuacion(texto: str) -> bool:
    t = texto.lower()
    return any(k in t for k in EVACUACION_KEYWORDS)


def tiene_red_infra(texto: str) -> bool:
    t = texto.lower()
    return any(k in t for k in RED_INFRA_KEYWORDS)


def clasificar(r: dict) -> tuple[bool, str]:
    """
    Devuelve (debe_descartar, razon).
    Solo actúa sobre registros es_energetico=True con tecnologia LAT o SET.
    """
    datos = r.get('datos') or {}
    tech = datos.get('tecnologia', '')
    if tech not in ('LAT', 'SET'):
        return False, ''

    promotor = datos.get('promotor') or ''
    gestor = datos.get('gestor_red') or ''
    nombre = datos.get('nombre_proyecto') or ''
    titulo = r.get('titulo_original') or ''
    texto = f"{nombre} {titulo}".strip()

    # Conservar si promotor/gestor es red regulada
    if es_promotor_red(promotor):
        return False, ''
    if es_gestor_red(gestor):
        # Salvo que el nombre diga claramente "evacuación" (error de gestor_red)
        if not tiene_evacuacion(texto):
            return False, ''

    # Conservar si el texto habla de infraestructura de red (aunque promotor sea null)
    if tiene_red_infra(texto) and not tiene_evacuacion(texto):
        return False, ''

    # Descartar si hay señales de evacuación privada
    if tiene_evacuacion(texto):
        if es_promotor_red(promotor):
            return False, ''  # REE/distribuidora puede tener "evacuación" en nombre
        return True, f"evacuación privada: promotor='{promotor[:50]}'"

    # Promotor privado sin señales de red → descartar
    if promotor and not es_promotor_red(promotor):
        # Excepciones conocidas: ADIF, Microsoft (data center con impacto en red)
        p_low = promotor.lower()
        if 'microsoft' in p_low or 'data center' in p_low:
            return False, ''
        if 'adif' in p_low:
            return False, ''
        return True, f"promotor privado sin evacuación explícita: '{promotor[:50]}'"

    # Promotor null sin señales claras → conservar (duda razonable)
    return False, ''


def procesar(apply=False, solo_anio=None):
    archivos = sorted(OUTPUT_DIR.glob("energy_extraido_*.json"))
    if solo_anio:
        archivos = [f for f in archivos if f.stem[16:20] == str(solo_anio)]

    total_revisados = 0
    total_descartados = 0
    cambios_por_archivo = {}

    for fpath in archivos:
        try:
            data = json.loads(fpath.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"  ERROR leyendo {fpath.name}: {e}")
            continue

        cambios = []
        for r in data.get('resultados', []):
            if not r.get('es_energetico', False):
                continue
            total_revisados += 1
            descartar, razon = clasificar(r)
            if descartar:
                total_descartados += 1
                cambios.append({
                    'id': r.get('id', ''),
                    'tech': (r.get('datos') or {}).get('tecnologia', ''),
                    'nombre': ((r.get('datos') or {}).get('nombre_proyecto') or '')[:70],
                    'razon': razon,
                })
                if apply:
                    r['es_energetico'] = False
                    r['estado_validacion'] = 'descartado'
                    if r.get('datos'):
                        r['datos']['observaciones'] = (
                            (r['datos'].get('observaciones') or '') +
                            f' [reclasificado: {razon}]'
                        ).strip()

        if cambios:
            cambios_por_archivo[fpath.name] = cambios
            if apply:
                fpath.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )

    # Reporte
    print(f"\n{'APLICADO' if apply else 'PREVIEW (sin cambios)'}")
    print(f"{'─'*60}")
    print(f"Archivos procesados : {len(archivos)}")
    print(f"Registros LAT/SET revisados: {total_revisados}")
    print(f"Descartados como evacuación privada: {total_descartados}")
    print()

    for fname, cambios in sorted(cambios_por_archivo.items()):
        print(f"  {fname}:")
        for c in cambios:
            print(f"    [{c['tech']}] {c['id']} — {c['nombre']}")
            print(f"           → {c['razon']}")

    return total_descartados


if __name__ == '__main__':
    apply = '--apply' in sys.argv
    anio = None
    for a in sys.argv[1:]:
        if a.startswith('--year'):
            try:
                anio = int(a.split('=')[1]) if '=' in a else int(sys.argv[sys.argv.index(a)+1])
            except:
                pass

    n = procesar(apply=apply, solo_anio=anio)
    if not apply and n > 0:
        print(f"\nEjecuta con --apply para aplicar los {n} cambios.")
