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
    return s

def tokens(s, min_len=3):
    return set(t for t in norm(s).split() if len(t) >= min_len and t not in _STOPWORDS)

def jaccard(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb: return 0.0
    return len(ta & tb) / len(ta | tb)

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
    return has_letters and len(e) >= 5

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
    for fname in sorted(os.listdir(output_dir)):
        if not (fname.startswith('energy_extraido_') and fname.endswith('.json')):
            continue
        with open(os.path.join(output_dir, fname), encoding='utf-8') as f:
            data = json.load(f)
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
    exp_conflicts = []  # expedientes con nombres muy distintos → posible falso positivo
    for exp, idxs in exp_idx.items():
        if len(idxs) < 2: continue
        # Verificar que los nombres son similares antes de unir
        for a in idxs:
            for b in idxs:
                if a >= b: continue
                na = records[a].get('nombre_proyecto', '')
                nb = records[b].get('nombre_proyecto', '')
                # Si ambos tienen nombre y son muy distintos, marcar para revisión
                if na and nb and jaccard(na, nb) < 0.15:
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

    # Regla 3: similitud de nombre (Jaccard >= 0.75) + mismo promotor normalizado
    # Solo entre registros con tecnología energética
    ENERGY_TECH = {'Fotovoltaica','Eólica','FV+BESS','BESS','H2','Biometano','SET','LAT','Hidráulica'}
    energy_idx = [i for i, r in enumerate(records)
                  if r.get('tecnologia') in ENERGY_TECH and r.get('nombre_proyecto')]
    for ii, i in enumerate(energy_idx):
        for jj in range(ii+1, len(energy_idx)):
            j = energy_idx[jj]
            if uf.find(i) == uf.find(j): continue  # ya unidos
            ri, rj = records[i], records[j]
            ni = ri.get('nombre_proyecto', '')
            nj = rj.get('nombre_proyecto', '')
            if not ni or not nj: continue
            jac = jaccard(ni, nj)
            if jac < 0.75: continue
            # Confirmar con promotor o subestación
            pi = norm_promotor(ri.get('promotor', ''))
            pj = norm_promotor(rj.get('promotor', ''))
            si = norm(ri.get('subestacion_conexion', '') or '')
            sj = norm(rj.get('subestacion_conexion', '') or '')
            promotor_match = bool(pi and pj and jaccard(pi, pj) >= 0.6)
            sub_match = bool(si and sj and len(si) > 5 and jaccard(si, sj) >= 0.7)
            if promotor_match or sub_match:
                uf.union(i, j)

    # Regla 4: promotor específico + subestación específica
    for i in range(n):
        for j in range(i+1, n):
            if uf.find(i) == uf.find(j): continue
            ri, rj = records[i], records[j]
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
        print(f'\n  Advertencias — expediente compartido, nombres distintos:')
        for exp, na, nb in conflicts:
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
