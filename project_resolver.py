#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NODALYS — Project Resolver
Lee todos los output/energy_extraido_*.json y genera projects.json
agrupando publicaciones por proyecto mediante entity resolution.

Reglas de matching (en orden de prioridad):
  1. Expediente exacto (cuando es específico: >= 6 chars, contiene
     letras, no es solo año o código de departamento)
  2. Nombre normalizado idéntico + misma tecnología
  3. Nombre normalizado similar (Jaccard >= 0.75) + mismo promotor
  4. Mismo promotor + misma subestación (cuando ambos son específicos)

Uso:
  python project_resolver.py [--output projects.json]
"""

import argparse, json, os, re, unicodedata
from datetime import date
from collections import defaultdict

OUTPUT_DIR   = "output"
PROJECTS_OUT = "projects.json"

# ── Normalizacion ──────────────────────────────────────────────
_STOPWORDS = {
    'DE','DEL','LA','EL','LOS','LAS','UN','UNA','Y','E','O','U',
    'SL','SA','SLU','SAU','SLU','SLU','SL','SA','SOCIEDAD',
    'LIMITADA','ANONIMA','PROYECTO','PROYECTOS','PLANTA',
    'INSTALACION','INSTALACIONES','PARQUE','CENTRAL','COMPLEJO',
}

def norm(s):
    """Normaliza string: mayús, sin acentos, solo alfanumérico+espacio."""
    if not s: return ''
    s = s.upper().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # Colapsar variantes tipo 'MER 2' vs 'MER2' → 'MER2'
    s = re.sub(r'([A-Z])\s+(\d)', r'\1\2', s)
    return s

# Patrón para números romanos (I–MMMM)
_ROMAN_PAT = re.compile(
    r'^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$'
)

def tokens(s, min_len=3):
    """
    Tokeniza un nombre normalizado.
    Conserva dígitos y números romanos aunque sean < min_len chars,
    para evitar que 'Solar 1' y 'Solar 2' colapsen al mismo token-set.
    """
    result = set()
    for t in norm(s).split():
        if t in _STOPWORDS:
            continue
        is_short_num = t.isdigit() or (len(t) >= 1 and _ROMAN_PAT.match(t))
        if len(t) >= min_len or is_short_num:
            result.add(t)
    return result

def jaccard(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb: return 0.0
    return len(ta & tb) / len(ta | tb)

# ── Canonicalización de prefijos y sufijos numéricos ──────────
_PREFIX_ALIASES = [
    # (patrón regex, reemplazo canónico)
    # Todas las variantes fotovoltaicas -> un único canon 'PLANTA FOTOVOLTAICA '
    # (PSFV X == Planta Solar Fotovoltaica X == PFV X == FV X == Instalación FV X ...)
    (re.compile(r'^(?:PSFV|PFV|PSF|ISF|FV)\s+', re.I), 'PLANTA FOTOVOLTAICA '),
    (re.compile(r'^(?:PLANTA|PARQUE|INSTALACION)S?\s+(?:SOLAR\s+)?(?:FOTOVOLTAICA|FOTOVOLTAICO|FV)\s+', re.I), 'PLANTA FOTOVOLTAICA '),
    (re.compile(r'^(?:PLANTA\s+)?(?:SOLAR\s+)?(?:FOTOVOLTAICA|SOLAR\s+FV)\s+', re.I), 'PLANTA FOTOVOLTAICA '),
    (re.compile(r'^(?:PARQUE|PLANTA|INSTALACION)S?\s+SOLAR\s+', re.I), 'PLANTA FOTOVOLTAICA '),
    # Eólica
    (re.compile(r'^(?:PARQUE|PLANTA|INSTALACION)S?\s+EOLIC[OA]\s+', re.I), 'PARQUE EOLICO '),
    (re.compile(r'^PE\s+', re.I), 'PARQUE EOLICO '),
]

_ROMAN_TO_INT = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,
                  'IX':9,'X':10,'XI':11,'XII':12,'XIII':13,'XIV':14,'XV':15,
                  'XVI':16,'XVII':17,'XVIII':18,'XIX':19,'XX':20}
_INT_TO_ROMAN = {v:k for k,v in _ROMAN_TO_INT.items()}

def _normalize_suffix(s):
    """Convierte sufijos numéricos al mismo formato: romanos → enteros."""
    def repl(m):
        tok = m.group(0).upper()
        if tok in _ROMAN_TO_INT:
            return str(_ROMAN_TO_INT[tok])
        return tok
    return re.sub(r'\b([IVXLCDM]+|\d+)\b', repl, s, flags=re.I)

def canon_nombre(s):
    """Canonicaliza prefijo y sufijo de un nombre de proyecto para comparación."""
    if not s: return ''
    c = norm(s)
    for _ in range(3):
        changed = False
        for pat, repl in _PREFIX_ALIASES:
            # quitar prefijos redundantes tras el canon (PSFV FV X -> PLANTA FOTOVOLTAICA X)
            c2 = pat.sub(repl.upper(), c, count=1)
            if c2 != c:
                c = c2
                changed = True
                break
        # colapsar canon duplicado: 'PLANTA FOTOVOLTAICA PLANTA FOTOVOLTAICA X'
        c = re.sub(r'^(PLANTA FOTOVOLTAICA |PARQUE EOLICO )(?:FV |FOTOVOLTAICA |PFV |PSFV |EOLIC[OA] )', r'\1', c)
        c = re.sub(r'^(PLANTA FOTOVOLTAICA |PARQUE EOLICO )\1', r'\1', c)
        if not changed:
            break
    c = _normalize_suffix(c)
    return c.strip()

_CANON_PREFIX_RE = re.compile(r'^(?:PLANTA FOTOVOLTAICA|PARQUE EOLICO|PLANTA SOLAR)\s+')

def core_nombre(s):
    """Nucleo del nombre sin prefijo tecnologico: 'PSFV Los Hornillos 1',
    'FV Los Hornillos 1' y 'Los Hornillos 1' comparten nucleo."""
    c = _CANON_PREFIX_RE.sub('', canon_nombre(s)).strip()
    c = re.sub(r'^(?:DE|DEL)\s+', '', c)                                   # 'PB De Biometano X' == 'PB Biometano X'
    c = re.sub(r'\s*\((?:MOD|MODIFICADO|MODIFICACION)[^)]*\)\s*$', '', c) # '(MOD)' final
    c = re.sub(r'\s+(?:MODIFICADO|MODIFICACION)$', '', c)                  # 'X Modificado' == 'X'
    # espaciado consistente del sufijo numerico: 'RENEDO1' == 'RENEDO 1'
    c = re.sub(r'(?<=[A-Z])(\d+)$', r' \1', c)
    return ' '.join(c.split())


def is_specific_expediente(exp):
    """
    True si el expediente parece específico de un proyecto concreto.
    Rechaza: solo dígitos, longitud < 6, solo año, códigos de dpto.
    """
    if not exp or len(exp.strip()) < 5: return False
    e = exp.strip()
    if re.match(r'^\d{4}$', e): return False          # solo año
    if re.match(r'^\d{1,5}$', e): return False         # solo número corto
    has_letters = bool(re.search(r'[A-Za-z]', e))
    if not has_letters or len(e) < 5: return False
    # Rechazar placeholders tipo XXXXX/NNNN (reutilizados en múltiples proyectos)
    if re.search(r'[XN]{4,}', e.upper()): return False
    return True
# ── Normalización nombres biometano ───────────────────────────
_BIOMETANO_VERBOSE_RE = re.compile(
    r'^(?:planta\s+(?:de\s+)?(?:digesti[oó]n|codigesti[oó]n|valoriza[^\s]*|producci[oó]n|biog[aá]s\s+para)'
    r'|^instalaci[oó]n\s+de\s+valoriza)',
    re.IGNORECASE
)

def normalizar_nombre_biometano(nombre, municipio, tecnologia):
    """Si el nombre es un título burocrático largo, simplifica a 'Planta Biometano [municipio]'."""
    if not nombre: return nombre
    if tecnologia not in ('Biometano', 'Biogás', 'Biogas', 'biometano', 'biogás'):
        return nombre
    if not _BIOMETANO_VERBOSE_RE.match(nombre):
        return nombre
    # Usar municipio si disponible
    if municipio:
        # Title-case apropiado
        return 'Planta Biometano ' + municipio
    return nombre


def sufijo_numerico(nombre):
    """
    Devuelve el token numérico/romano diferenciador de un nombre de proyecto,
    o None si no tiene.  Ej: "Valladolid Solar I" → "I", "Solar 3" → "3".
    Ignora stopwords y tokens no numéricos.
    """
    for t in tokens(nombre):
        if t.isdigit():
            return t
        if _ROMAN_PAT.match(t) and t:  # romano no vacío
            return t
    return None


def bloqueado_por_sufijo(na, nb):
    """
    True si ambos nombres tienen sufijos numéricos/romanos DISTINTOS.
    Impide que "Solar I" y "Solar V" se fusionen aunque compartan expediente o SET.
    """
    if not na or not nb:
        return False
    sa = sufijo_numerico(na)
    sb = sufijo_numerico(nb)
    return sa is not None and sb is not None and sa != sb


def norm_promotor(s):
    if not s: return ''
    n = norm(s)
    # Quitar formas jurídicas
    for jur in ['SLU','SAU','SL','SA','SPA','AIE']:
        n = re.sub(r'\b' + jur + r'\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()

# ── Carga de datos ─────────────────────────────────────────────
def load_all_records(output_dir):
    records = []
    skipped = []
    for fname in sorted(os.listdir(output_dir)):
        if not (fname.startswith('energy_extraido_') and fname.endswith('.json')):
            continue
        fpath = os.path.join(output_dir, fname)
        try:
            with open(fpath, encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            skipped.append(fname)
            print(f"  WARN: {fname} — JSON inválido, ignorado ({e})")
            continue
        for item in data.get('resultados', []):
            if not item.get('es_energetico'): continue
            d = item.get('datos') or {}   # guard: datos puede ser null
            rec = {
                'id_boe':             item.get('id', ''),
                'fecha_publicacion':  item.get('fecha_publicacion', ''),
                'boletin':            item.get('boletin', ''),
                'url':                item.get('url', ''),
                'titulo_original':    item.get('titulo_original', ''),
                'confianza':          d.get('confianza'),
                'nombre_proyecto':    d.get('nombre_proyecto'),
                'promotor':           d.get('promotor'),
                'tecnologia':         d.get('tecnologia'),
                'potencia_mw':        d.get('potencia_mw'),
                'provincia':          d.get('provincia'),
                'municipio':          d.get('municipio'),
                'subestacion_conexion': d.get('subestacion_conexion'),
                'tension_conexion_kv': d.get('tension_conexion_kv'),
                'tipo_permiso':       d.get('tipo_permiso'),
                'estado_permiso':     d.get('estado_permiso'),
                'numero_expediente_industria':     d.get('numero_expediente_industria'),
                'numero_expediente_medioambiente': d.get('numero_expediente_medioambiente'),
                'permisos_adicionales': d.get('permisos_adicionales', []),
                'es_proyecto_fallido': d.get('es_proyecto_fallido', False),
                'capacidad_mw_liberada': d.get('capacidad_mw_liberada'),
                'motivo_fallo':       d.get('motivo_fallo'),
                'observaciones':      d.get('observaciones'),
                'comunidad_autonoma': d.get('comunidad_autonoma'),
            }
            records.append(rec)
    if skipped:
        print(f"  WARN: {len(skipped)} ficheros ignorados por JSON inválido")
    return records

# ── Union-Find para clustering ─────────────────────────────────
class UF:
    def __init__(self, n):
        self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb: self.p[ra] = rb

# ── Infraestructura de evacuación ────────────────────────────
_INFRA_EVACUA_RE = re.compile(
    r'\b(LAT|L[ÍI]NEA|STR|SUBESTACI[OÓ]N|SUBESTACION|INFRAESTRUCTURA'
    r'|EVACUACI[OÓ]N|EVACUACION|INTERCONEX|TRANSFORMADORA)\b',
    re.IGNORECASE
)

def es_infraestructura_evacuacion(nombre):
    """True si el nombre es infraestructura AT (LAT/STR/SET), no generación."""
    if not nombre: return False
    return bool(_INFRA_EVACUA_RE.search(nombre))


# ── Lista de exclusión manual ─────────────────────────────────
# Pares (expediente, frozenset{nombre_A, nombre_B}) confirmados como DISTINTOS.
EXCLUSION_PAIRS = [
    ('IE/AT/64-2019', frozenset(['LAT 132kV Hazapierna-Medinaceli II', 'Parque Eólico Torrecilla'])),
    ('IE/AT/64-2019', frozenset(['LAT 132kV Hazapierna-Medinaceli II', 'Parque Eólico Praderas Altas'])),
    ('IE/AT/64-2019', frozenset(['LAT 132kV Hazapierna-Medinaceli II y SET', 'Parque Eólico Torrecilla'])),
    ('IE/AT/64-2019', frozenset(['LAT 132kV Hazapierna-Medinaceli II y SET', 'Parque Eólico Praderas Altas'])),
    ('PE-633', frozenset(['Infraestructuras Comunes de Evacuación Ébora', 'LAT 220 kV SET FV Ébora-SET Ébora'])),
    ('PE-633', frozenset(['Infraestructuras Comunes de Evacuación Sur', 'LAT 220 kV SET FV Ébora-SET Ébora'])),
]

def _in_exclusion_list(exp, na, nb):
    """True si el par está confirmado manualmente como proyectos distintos."""
    pair = frozenset([na.strip(), nb.strip()])
    return any(ex_exp == exp and ex_pair == pair for ex_exp, ex_pair in EXCLUSION_PAIRS)


# ── Fusión forzada ─────────────────────────────────────────────
# Expedientes donde el mismo proyecto aparece con nombres muy distintos
# (imposible detectar por Jaccard). Todos los registros del expediente
# se fusionan sin verificar nombre, sufijo ni infra.
FORCE_MERGE_EXPEDIENTES = {
    'IN407A 2023/326-4',       # LAT 66kV DC Lourizán Cangas II — 3 formulaciones distintas
    '10-EIA-00037.5/2022',     # "Nueva STR Fuente Hito" = "Subestación Transformadora Fuente Hito"
    '570-23-AASG',             # "Biocarbonero" = planta en Carbonero el Mayor
    'EIAA/2024/BU/002',        # "FV El Páramo" = "Planta Solar Hibridada El Páramo"
    'AAI-GU-100',              # "Alcarria H2" = nombre comercial del mismo proyecto H2
    'PRO-CU-20-1042',          # "Planta Solar FV La Encantada I" = "Parque Solar Fotovoltaico La Encantada I"
    'IE/FV/25-2020',           # "Trévago Solar" = "Trévago Solar 1"
    'ATLI-6484',               # "Algiedi Solar - Inst..." = "Algiedi Solar"
    'RI: 22532',               # "Bustillo Solar" = "Instalación Solar Fotovoltaica Bustillo"
    'FV-868',                  # "Adelfa" = "Adelfa Solar"
    'FV-870',                  # "Apamate Solar" = "Apamate"
}


# ── Entity resolution ──────────────────────────────────────────
def resolve_projects(records):
    n = len(records)
    uf = UF(n)

    # Índices por expediente
    exp_idx = defaultdict(list)
    for i, r in enumerate(records):
        for ef in ['numero_expediente_industria', 'numero_expediente_medioambiente']:
            e = r.get(ef, '')
            if is_specific_expediente(e):
                exp_idx[e.strip()].append(i)

    # Regla 1: expediente exacto
    # Une publicaciones del mismo expediente si los nombres son similares (jac >= 0.30),
    # no tienen sufijos numéricos distintos, no están en la lista de exclusión manual,
    # y no mezclan infraestructura de evacuación con proyectos de generación.
    exp_conflicts = []
    for exp, idxs in exp_idx.items():
        if len(idxs) < 2: continue
        for a in idxs:
            for b in idxs:
                if a >= b: continue
                # Fusión forzada: mismo proyecto con nombres muy distintos confirmados manualmente
                if exp in FORCE_MERGE_EXPEDIENTES:
                    uf.union(a, b)
                    continue
                na = records[a].get('nombre_proyecto', '') or ''
                nb = records[b].get('nombre_proyecto', '') or ''
                # Bloqueo 1: sufijos numéricos distintos → proyectos distintos
                # Pero antes canonicalizar ("I" vs "1" → mismo sufijo tras canon)
                if bloqueado_por_sufijo(na, nb):
                    # Segundo intento con nombres canonicalizados
                    ca, cb = canon_nombre(na), canon_nombre(nb)
                    if not bloqueado_por_sufijo(ca, cb) and jaccard(ca, cb) >= 0.30:
                        uf.union(a, b)
                    else:
                        exp_conflicts.append((exp, na, nb))
                    continue
                # Bloqueo 2: par confirmado manualmente como proyectos distintos
                if _in_exclusion_list(exp, na, nb):
                    exp_conflicts.append((exp, na, nb))
                    continue
                # Bloqueo 3: uno es infraestructura de evacuación y el otro no → no fusionar
                infra_a = es_infraestructura_evacuacion(na)
                infra_b = es_infraestructura_evacuacion(nb)
                if infra_a != infra_b:
                    exp_conflicts.append((exp, na, nb))
                    continue
                # Jaccard sobre nombres canonicalizados para mejor matching
                ca, cb = canon_nombre(na), canon_nombre(nb)
                jac = jaccard(ca, cb) if (ca and cb) else (1.0 if (na and nb) else 0.0)
                if jac < 0.30:
                    exp_conflicts.append((exp, na, nb))
                else:
                    uf.union(a, b)

    # Regla 2: nombre normalizado idéntico + tecnología
    name_tech_idx = defaultdict(list)
    for i, r in enumerate(records):
        n_norm = norm(r.get('nombre_proyecto', ''))
        tech   = norm(r.get('tecnologia', '') or '')
        if n_norm and len(n_norm) > 8:  # evitar nombres muy cortos
            name_tech_idx[(n_norm, tech)].append(i)
    for (nm, tech), idxs in name_tech_idx.items():
        for a in idxs:
            for b in idxs:
                if a < b: uf.union(a, b)

    # Regla 2b: mismo nucleo de nombre (sin prefijo tecnologico) + tecnologia compatible
    core_idx = defaultdict(list)
    for i, r in enumerate(records):
        nm = r.get('nombre_proyecto', '')
        tec = r.get('tecnologia') or ''
        if tec in ('Biometano', 'Biogás', 'Biogas'):
            nm = normalizar_nombre_biometano(nm, r.get('municipio') or '', tec) or nm
        c = core_nombre(nm)
        if c and len(c) >= 8:
            core_idx[c].append(i)
    for c, idxs in core_idx.items():
        if len(idxs) < 2: continue
        for a in idxs:
            for b in idxs:
                if a >= b: continue
                ta = norm(records[a].get('tecnologia', '') or '')
                tb = norm(records[b].get('tecnologia', '') or '')
                if ta and tb and ta != tb: continue
                na = records[a].get('nombre_proyecto', '') or ''
                nb = records[b].get('nombre_proyecto', '') or ''
                if es_infraestructura_evacuacion(na) != es_infraestructura_evacuacion(nb): continue
                uf.union(a, b)

    # Regla 3: similitud de nombre (Jaccard >= 0.75) + mismo promotor/SET
    # Indexado por token de promotor para evitar O(n²) completo.
    promotor_bucket = defaultdict(list)
    for i, r in enumerate(records):
        pn = norm_promotor(r.get('promotor', '') or '')
        if len(pn) > 5:
            # Usar primer token significativo como clave de bucket
            first_tok = next((t for t in pn.split() if len(t) >= 4), None)
            if first_tok:
                promotor_bucket[first_tok].append(i)

    set_bucket = defaultdict(list)
    for i, r in enumerate(records):
        sn = norm(r.get('subestacion_conexion', '') or '')
        if len(sn) > 5:
            first_tok = next((t for t in sn.split() if len(t) >= 4), None)
            if first_tok:
                set_bucket[first_tok].append(i)

    def _r3_r4_pairs(bucket_dict):
        """Genera pares (i,j) candidatos dentro de cada bucket."""
        seen = set()
        for idxs in bucket_dict.values():
            for ii, i in enumerate(idxs):
                for j in idxs[ii+1:]:
                    pair = (min(i,j), max(i,j))
                    if pair not in seen:
                        seen.add(pair)
                        yield i, j

    for i, j in _r3_r4_pairs(promotor_bucket):
        if uf.find(i) == uf.find(j): continue
        ri, rj = records[i], records[j]
        ni = ri.get('nombre_proyecto', '') or ''
        nj = rj.get('nombre_proyecto', '') or ''
        if not ni or not nj: continue
        if bloqueado_por_sufijo(ni, nj): continue
        jac = jaccard(ni, nj)
        if jac < 0.75: continue
        pi = norm_promotor(ri.get('promotor', '') or '')
        pj = norm_promotor(rj.get('promotor', '') or '')
        si = norm(ri.get('subestacion_conexion', '') or '')
        sj = norm(rj.get('subestacion_conexion', '') or '')
        promotor_match = bool(pi and pj and jaccard(pi, pj) >= 0.6)
        sub_match = bool(si and sj and len(si) > 5 and jaccard(si, sj) >= 0.7)
        if promotor_match or sub_match:
            uf.union(i, j)

    # Regla 4: promotor específico + subestación específica + nombre similar (>= 0.50)
    # Indexado por bucket de SET para evitar O(n²). Requiere similitud de nombre para
    # evitar fusionar "Solar I", "Solar V", "Valdecarros" del mismo promotor en la misma SET.
    for i, j in _r3_r4_pairs(set_bucket):
        if uf.find(i) == uf.find(j): continue
        ri, rj = records[i], records[j]
        ni = ri.get('nombre_proyecto', '') or ''
        nj = rj.get('nombre_proyecto', '') or ''
        if bloqueado_por_sufijo(ni, nj): continue
        jac_nombre = jaccard(ni, nj) if (ni and nj) else 0.0
        if jac_nombre < 0.50: continue
        pi = norm_promotor(ri.get('promotor', '') or '')
        pj = norm_promotor(rj.get('promotor', '') or '')
        si = norm(ri.get('subestacion_conexion', '') or '')
        sj = norm(rj.get('subestacion_conexion', '') or '')
        if (len(pi) > 8 and len(si) > 8
                and jaccard(pi, pj) >= 0.7
                and jaccard(si, sj) >= 0.75):
            uf.union(i, j)

    return uf, exp_conflicts

# ── Construir entidades proyecto ───────────────────────────────
ESTADO_RANK = {
    'otorgado': 6, 'favorable': 5, 'inf. publica': 4,
    'en tramite': 3, 'denegado': 2, 'caducado': 1,
}

def build_projects(records, uf):
    clusters = defaultdict(list)
    for i, r in enumerate(records):
        clusters[uf.find(i)].append(r)

    projects = []
    for root, pubs in clusters.items():
        pubs_sorted = sorted(pubs, key=lambda x: x.get('fecha_publicacion', ''))

        # --- Nombre canónico: el más largo y con mayor confianza ---
        nombres = [(r.get('nombre_proyecto',''), r.get('confianza') or 0) for r in pubs if r.get('nombre_proyecto')]
        if nombres:
            nombre_can = max(nombres, key=lambda x: (x[1], len(x[0])))[0]
        else:
            nombre_can = pubs_sorted[0].get('titulo_original', 'Sin nombre')[:80]

        # Normalizar nombre biometano si es verboso
        _tech_can = next((r.get('tecnologia') for r in reversed(pubs_sorted) if r.get('tecnologia')), None)
        _mun_can  = next((r.get('municipio')  for r in reversed(pubs_sorted) if r.get('municipio')),  None)
        nombre_can = normalizar_nombre_biometano(nombre_can, _mun_can, _tech_can)

        # --- Estado y tipo: de la misma publicación más reciente con estado definido ---
        # La publicación más reciente con estado marca tanto el estado actual como
        # el tipo de trámite al que hace referencia ese estado.
        estado_actual = None
        ultimo_tipo_permiso_estado = None
        for r in reversed(pubs_sorted):
            e = (r.get('estado_permiso') or '').strip()
            if e:
                estado_actual = e
                ultimo_tipo_permiso_estado = r.get('tipo_permiso') or None
                break
        # Fallback: si ninguna pub tiene estado, el tipo es el de la más reciente con tipo
        if ultimo_tipo_permiso_estado is None:
            ultimo_tipo_permiso_estado = next(
                (r.get('tipo_permiso') for r in reversed(pubs_sorted) if r.get('tipo_permiso')), None
            )

        # --- Otros campos: del registro más reciente con dato ---
        def best(field):
            vals = [r.get(field) for r in reversed(pubs_sorted) if r.get(field)]
            return vals[0] if vals else None

        # Expedientes únicos
        exps = set()
        for r in pubs_sorted:
            for ef in ['numero_expediente_industria','numero_expediente_medioambiente']:
                v = r.get(ef)
                if v and is_specific_expediente(v): exps.add(v.strip())

        proj = {
            'id':              f'prj_{root:05d}',
            'nombre':          nombre_can,
            'promotor':        best('promotor'),
            'tecnologia':      best('tecnologia'),
            'potencia_mw':     best('potencia_mw'),
            'provincia':       best('provincia'),
            'municipio':       best('municipio'),
            'comunidad_autonoma': best('comunidad_autonoma'),
            'subestacion':     best('subestacion_conexion'),
            'tension_kv':      best('tension_conexion_kv'),
            'expedientes':     sorted(exps),
            'estado_actual':   estado_actual,
            'ultimo_tipo_permiso': ultimo_tipo_permiso_estado,
            'ultimo_boletin':      pubs_sorted[-1].get('boletin'),
            'es_fallido':      any(r.get('es_proyecto_fallido') for r in pubs_sorted),
            'mw_liberados':    best('capacidad_mw_liberada'),
            'fecha_primera':   pubs_sorted[0].get('fecha_publicacion'),
            'fecha_ultima':    pubs_sorted[-1].get('fecha_publicacion'),
            'n_publicaciones': len(pubs_sorted),
            'publicaciones': [
                {
                    'id_boe':        r.get('id_boe'),
                    'fecha':         r.get('fecha_publicacion'),
                    'boletin':       r.get('boletin'),
                    'tipo_permiso':  r.get('tipo_permiso'),
                    'estado':        r.get('estado_permiso'),
                    'url':           r.get('url'),
                    'titulo':        (r.get('titulo_original') or '')[:500],
                    'permisos_adicionales': r.get('permisos_adicionales', []),
                    'es_fallido':    r.get('es_proyecto_fallido', False),
                    'mw_liberados':  r.get('capacidad_mw_liberada'),
                    'observaciones': r.get('observaciones'),
                }
                for r in pubs_sorted
            ],
        }
        projects.append(proj)

    # Ordenar: primero los que tienen más publicaciones, luego por fecha reciente
    projects.sort(key=lambda p: (-p['n_publicaciones'], -(p['fecha_ultima'] or '').__len__()))
    return projects

# ── Main ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=PROJECTS_OUT)
    parser.add_argument('--output-dir', default=OUTPUT_DIR)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    print(f'\nCargando registros de {args.output_dir}...')
    records = load_all_records(args.output_dir)
    print(f'  {len(records)} publicaciones cargadas')

    print('Resolviendo entidades...')
    uf, conflicts = resolve_projects(records)

    projects = build_projects(records, uf)
    multi = [p for p in projects if p['n_publicaciones'] > 1]

    print(f'\nResultado:')
    print(f'  {len(projects)} proyectos únicos')
    print(f'  {len(multi)} con múltiples publicaciones')

    if conflicts:
        # Deduplicar por (exp, par-canónico) para evitar entradas duplicadas
        seen_conflicts = set()
        dedup = []
        for exp, na, nb in conflicts:
            key = (exp, frozenset([na.strip(), nb.strip()]))
            if key not in seen_conflicts:
                seen_conflicts.add(key)
                dedup.append((exp, na, nb))
        print(f'\n  Advertencias — expediente compartido, nombres distintos:')
        for exp, na, nb in dedup:
            print(f'    [{exp}] "{na[:40]}" vs "{nb[:40]}"')

    if args.verbose:
        print(f'\nProyectos con múltiples publicaciones:')
        for p in sorted(multi, key=lambda x: -x['n_publicaciones'])[:20]:
            tec=p['tecnologia'] or '?'; est=p['estado_actual'] or '?'
            print(f'  [{p["n_publicaciones"]}x] {p["nombre"][:55]:55} | {tec[:12]:12} | {est}')
            for pub in p['publicaciones']:
                print(f'      {pub["fecha"]} {pub["boletin"]:8} {pub["tipo_permiso"] or "?":12} {pub["estado"] or "?"}')

    out = {
        'version':   '1.0',
        'generado':  date.today().isoformat(),
        'total':     len(projects),
        'proyectos': projects,
    }
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\nGuardado en {args.output}')

    # Auto-generate projects_data.js for file:// loading in browser
    js_path = 'projects_data.js'
    with open(args.output, 'r', encoding='utf-8') as fj:
        raw = fj.read()
    with open(js_path, 'w', encoding='utf-8') as fj:
        fj.write('window.PROJECTS_INLINE = ' + raw + ';')
    print(f'Generado {js_path}')

if __name__ == '__main__':
    main()
