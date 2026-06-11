#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reextract_malos.py — Repara proyectos mal definidos (nombre generico tipo
'ACUERDO de 10 de agosto de 2022', sin potencia/promotor/tecnologia).

Causa: el scraper guardo el titulo truncado y texto vacio en data/energy_raw_*.json.

Proceso (requiere internet y ANTHROPIC_API_KEY):
  1. Detecta proyectos mal definidos en projects.json.
  2. Localiza sus items raw y descarga el TEXTO COMPLETO del boletin
     (DOG/BOJA/xunta HTML; DOE PDF si PyPDF2 esta instalado).
  3. Re-extrae con el extractor IA existente (EnergyExtractor) y actualiza
     output/energy_extraido_<fecha>.json.
  4. Indica como regenerar projects.json.

Uso:
  python reextract_malos.py sk-ant-xxx          # procesar
  python reextract_malos.py --dry                # solo listar
"""
import os, sys, json, re, time, html
from pathlib import Path
from urllib.request import urlopen, Request

os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent))

DATA_DIR, OUTPUT_DIR = Path('data'), Path('output')
CACHE = Path('references/boletin_cache'); CACHE.mkdir(parents=True, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Nodalys research; tomitejada@gmail.com)'}

RE_BAD = re.compile(r'^(?:ACUERDO|RESOLUCI[OÓ]N|ANUNCIO|ORDEN|EDICTO|C[EÉ]DULA|DECRETO|'
                    r'INFORMACI[OÓ]N|EXTRACTO|CORRECCI[OÓ]N|\d+[ªa]?\s+FASE)\b', re.I)

def fetch_texto(url, cache_key):
    f = CACHE / (re.sub(r'[^\w.-]', '_', cache_key)[:120] + '_full.txt')
    if f.exists():
        return f.read_text(encoding='utf-8', errors='replace')
    try:
        raw = urlopen(Request(url, headers=UA), timeout=40).read()
        if url.lower().endswith('.pdf') or raw[:5] == b'%PDF-':
            try:
                import io
                from PyPDF2 import PdfReader
                txt = ' '.join((pg.extract_text() or '') for pg in PdfReader(io.BytesIO(raw)).pages)
            except ImportError:
                print('    WARN: PDF y PyPDF2 no instalado (pip install PyPDF2) — omitido')
                return ''
        else:
            s = raw.decode('utf-8', errors='replace')
            s = re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>', ' ', s)
            txt = html.unescape(re.sub(r'<[^>]+>', ' ', s))
        txt = ' '.join(txt.split())
        f.write_text(txt, encoding='utf-8')
        time.sleep(1.0)
        return txt
    except Exception as e:
        print(f'    WARN fetch: {e}')
        return ''

def main():
    dry = '--dry' in sys.argv
    api_key = next((a for a in sys.argv[1:] if a.startswith('sk-')), None) \
              or os.environ.get('ANTHROPIC_API_KEY')

    pj = json.load(open('projects.json', encoding='utf-8'))
    malos = [p for p in pj['proyectos']
             if RE_BAD.match((p.get('nombre') or '').strip())
             or (not p.get('potencia_mw') and not p.get('promotor') and not p.get('subestacion'))]
    print(f'proyectos mal definidos: {len(malos)}')

    # ids de publicacion afectados -> fechas
    afectados = {}  # fecha -> set(ids)
    for p in malos:
        for pub in (p.get('publicaciones') or []):
            pid, f = pub.get('id_boe'), pub.get('fecha')
            if pid and f:
                afectados.setdefault(f, set()).add(pid)
    print(f'fechas afectadas: {len(afectados)}')
    if dry:
        for f in sorted(afectados): print(' ', f, sorted(afectados[f]))
        return
    if not api_key:
        print('Falta API key: python reextract_malos.py sk-ant-...'); sys.exit(1)

    from extractor.energy_extractor import EnergyExtractor
    ex = EnergyExtractor(api_key=api_key)

    for fecha in sorted(afectados):
        raw_fp = DATA_DIR / f'energy_raw_{fecha}.json'
        if not raw_fp.exists():
            print(f'{fecha}: sin raw — omitido'); continue
        d = json.loads(raw_fp.read_text(encoding='utf-8'))
        items = d.get('items', [])
        objetivo = [it for it in items if it.get('id') in afectados[fecha]]
        if not objetivo: continue
        print(f'== {fecha}: {len(objetivo)} items')

        # 1) completar texto desde la fuente
        cambiado = False
        for it in objetivo:
            if len(it.get('texto') or '') > 500: continue
            url = it.get('url') or it.get('url_pdf')
            if not url: continue
            print(f'  fetch {it["id"]} ...')
            txt = fetch_texto(url, it['id'])
            if len(txt) > 300:
                it['texto'] = txt[:24000]
                cambiado = True
        if cambiado:
            raw_fp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')

        # 2) re-extraer SOLO esos items con IA y fusionar en el extraido
        res = ex.procesar_batch(objetivo, fecha)
        out_fp = OUTPUT_DIR / f'energy_extraido_{fecha}.json'
        if out_fp.exists():
            prev = json.loads(out_fp.read_text(encoding='utf-8'))
            ids_nuevos = {r.get('id_boe') or r.get('id') for r in res.get('resultados', [])}
            prev_res = [r for r in prev.get('resultados', [])
                        if (r.get('id_boe') or r.get('id')) not in ids_nuevos]
            prev['resultados'] = prev_res + res.get('resultados', [])
            prev['exitosos'] = sum(1 for r in prev['resultados'] if r.get('estado_validacion') != 'error')
            out_fp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding='utf-8')
        else:
            out_fp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')

    print('\nHecho. Regenera proyectos:')
    print('  python sync_all.py   (paso 3)  — o bien:')
    print('  python -c "import project_resolver as pr, json; from datetime import date; '
          'rs=pr.load_all_records(pr.OUTPUT_DIR); uf,_=pr.resolve_projects(rs); '
          'ps=pr.build_projects(rs,uf); json.dump({\'version\':\'1.0\',\'generado\':date.today().isoformat(),'
          '\'total\':len(ps),\'proyectos\':ps}, open(\'projects.json\',\'w\',encoding=\'utf-8\'), ensure_ascii=False, indent=2)"')
    print('  python link_projects_sets.py projects.json sets_capacity.json projects.json')

if __name__ == '__main__':
    main()
