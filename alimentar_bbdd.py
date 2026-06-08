#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NODALYS — Alimentar base de datos (histórico interactivo)

Estados de cada fecha:
  +  JSON local con datos energéticos (en Sheet si se usó el flujo normal)
  .  Sin JSON local — pendiente de procesar con el pipeline
  0  JSON local sin resultados energéticos (día sin publicaciones relevantes)
  ~  Mes parcialmente procesado
  -  Sin días hábiles en ese mes

Uso:
  python alimentar_bbdd.py              # menú interactivo
  python alimentar_bbdd.py <API_KEY>    # salta el prompt de key
  python alimentar_bbdd.py --sync       # sincroniza TODO al Sheet sin procesar
  python alimentar_bbdd.py --rebuild    # reconstruye el Sheet entero desde cero
"""

import os, sys, subprocess, calendar, json
from datetime import date, timedelta
from pathlib import Path

# ── Configuración ──────────────────────────────────────────────────────────────
BOLETINES = [
    "BOE", "BOCyL", "BOCM", "DOCM", "DOG", "BOJA", "BOC",
    "BOA", "BOPV", "DOE", "BON", "BOLR",
]
OUTPUT_DIR   = "output"
FECHA_INICIO = date(2020, 1, 1)

MES_ABBR = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
            'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
MES_FULL = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

FESTIVOS = {
    date(2020,  1,  1), date(2020,  1,  6), date(2020,  4,  9),
    date(2020,  4, 10), date(2020,  5,  1), date(2020,  8, 15),
    date(2020, 10, 12), date(2020, 11,  1), date(2020, 12,  6),
    date(2020, 12,  8), date(2020, 12, 25),
    date(2021,  1,  1), date(2021,  1,  6), date(2021,  4,  1),
    date(2021,  4,  2), date(2021,  5,  1), date(2021,  8, 15),
    date(2021, 10, 12), date(2021, 11,  1), date(2021, 12,  6),
    date(2021, 12,  8), date(2021, 12, 25),
    date(2022,  1,  1), date(2022,  1,  6), date(2022,  4, 14),
    date(2022,  4, 15), date(2022,  5,  1), date(2022,  8, 15),
    date(2022, 10, 12), date(2022, 11,  1), date(2022, 12,  6),
    date(2022, 12,  8), date(2022, 12, 25),
    date(2023,  1,  1), date(2023,  1,  6), date(2023,  4,  6),
    date(2023,  4,  7), date(2023,  5,  1), date(2023,  8, 15),
    date(2023, 10, 12), date(2023, 11,  1), date(2023, 12,  6),
    date(2023, 12,  8), date(2023, 12, 25),
    date(2024,  1,  1), date(2024,  1,  6), date(2024,  3, 28),
    date(2024,  3, 29), date(2024,  4,  1), date(2024,  5,  1),
    date(2024,  8, 15), date(2024, 10, 12), date(2024, 11,  1),
    date(2024, 12,  6), date(2024, 12,  9), date(2024, 12, 25),
    date(2025,  1,  1), date(2025,  1,  6), date(2025,  4, 17),
    date(2025,  4, 18), date(2025,  5,  1), date(2025,  8, 15),
    date(2025, 10, 12), date(2025, 11,  1), date(2025, 12,  6),
    date(2025, 12,  8), date(2025, 12, 25),
    date(2026,  1,  1), date(2026,  1,  6), date(2026,  4,  2),
    date(2026,  4,  3), date(2026,  5,  1), date(2026,  8, 15),
    date(2026, 10, 12), date(2026, 11,  1), date(2026, 12,  6),
    date(2026, 12,  8), date(2026, 12, 25),
    date(2027,  1,  1), date(2027,  1,  6), date(2027,  3, 25),
    date(2027,  3, 26), date(2027,  5,  1), date(2027,  8, 15),
    date(2027, 10, 12), date(2027, 11,  1), date(2027, 12,  6),
    date(2027, 12,  8), date(2027, 12, 25),
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def dias_habiles(inicio: date, fin: date) -> list:
    dias, d = [], inicio
    while d <= fin:
        if d.weekday() < 5 and d not in FESTIVOS:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def dias_habiles_mes(anio: int, mes: int, hoy: date) -> list:
    ultimo = calendar.monthrange(anio, mes)[1]
    inicio = date(anio, mes, 1)
    fin    = min(date(anio, mes, ultimo), hoy)
    if inicio > hoy:
        return []
    return dias_habiles(inicio, fin)


# ── Análisis de datos locales ──────────────────────────────────────────────────
def analizar_locales() -> tuple[set, dict, dict]:
    """
    Lee todos los energy_extraido_*.json.
    Devuelve:
      procesadas  — set[date] de fechas con JSON
      con_datos   — dict[date, int] de fechas con N registros energéticos > 0
      sin_datos   — set[date] de fechas con JSON pero 0 resultados
    """
    procesadas = set()
    con_datos  = {}
    sin_datos  = set()

    if not os.path.exists(OUTPUT_DIR):
        return procesadas, con_datos, sin_datos

    for fname in os.listdir(OUTPUT_DIR):
        if not (fname.startswith('energy_extraido_') and fname.endswith('.json')):
            continue
        s = fname[len('energy_extraido_'):-5]
        if len(s) != 8 or not s.isdigit():
            continue
        try:
            d = date(int(s[:4]), int(s[4:6]), int(s[6:]))
        except Exception:
            continue

        procesadas.add(d)
        try:
            with open(os.path.join(OUTPUT_DIR, fname), encoding='utf-8') as f:
                data = json.load(f)
            energeticos = [r for r in data.get('resultados', [])
                           if r.get('es_energetico') and r.get('datos')
                           and r.get('estado_validacion') != 'error']
            if energeticos:
                con_datos[d] = len(energeticos)
            else:
                sin_datos.add(d)
        except Exception:
            sin_datos.add(d)

    return procesadas, con_datos, sin_datos


def resumir_locales(con_datos: dict, hoy: date):
    """Muestra resumen de datos locales energéticos por año."""
    print()
    print("  Datos energéticos en JSONs locales:")
    anios = list(range(FECHA_INICIO.year, hoy.year + 1))
    total_fechas = total_registros = 0
    for anio in anios:
        fechas_anio = {d: n for d, n in con_datos.items() if d.year == anio}
        if fechas_anio:
            n_f = len(fechas_anio)
            n_r = sum(fechas_anio.values())
            total_fechas += n_f
            total_registros += n_r
            print(f"    {anio}:  {n_f} fechas  ·  {n_r} registros energéticos")
    print(f"    TOTAL: {total_fechas} fechas  ·  {total_registros} registros")
    print()


# ── Tabla de estado ────────────────────────────────────────────────────────────
def estado_mes(dias: list, procesadas: set, con_datos: dict) -> tuple:
    """
    Devuelve (ok, total, simbolo).
      +  todos los días procesados (con o sin datos)
      ~  algunos días procesados
      .  ningún día procesado
      -  sin días hábiles
    """
    if not dias:
        return 0, 0, '-'
    ok    = sum(1 for d in dias if d in procesadas)
    total = len(dias)
    if ok == 0:
        return 0, total, '.'
    if ok == total:
        return ok, total, '+'
    return ok, total, '~'


def mostrar_estado(hoy: date, procesadas: set, con_datos: dict) -> int:
    """Muestra tabla. Devuelve número de días hábiles pendientes."""
    print()
    print("=" * 72)
    print("  ESTADO DEL HISTÓRICO LOCAL — NODALYS")
    print("=" * 72)
    print()
    print("  Leyenda:  + Procesado   ~ Parcial   . Pendiente   - Sin días")
    print("  Nota: + significa que el pipeline corrió, NO garantiza subida al Sheet")
    print()

    total_ok = total_pend = 0
    anios = list(range(FECHA_INICIO.year, hoy.year + 1))

    for anio in anios:
        partes = []
        ok_anio = pend_anio = 0
        for mes in range(1, 13):
            dias = dias_habiles_mes(anio, mes, hoy)
            ok, total, simbolo = estado_mes(dias, procesadas, con_datos)
            ok_anio   += ok
            pend_anio += (total - ok)
            total_ok  += ok
            total_pend += (total - ok)
            partes.append(f"{MES_ABBR[mes]}{simbolo}")
        fila = "  ".join(partes)
        resumen = f"{ok_anio}/{ok_anio + pend_anio}"
        print(f"  {anio}   {fila}   [{resumen}]")

    print()
    total = total_ok + total_pend
    print(f"  Procesados: {total_ok}/{total}   |   Sin procesar: {total_pend}")
    print("=" * 72)
    return total_pend


def mostrar_detalle_mes(anio: int, mes: int, dias: list, procesadas: set):
    pend = sorted(d for d in dias if d not in procesadas)
    ok   = [d for d in dias if d in procesadas]
    barra = "#" * len(ok) + "." * len(pend)
    print(f"\n    {MES_FULL[mes]} {anio}   [{barra}]   {len(ok)}/{len(dias)}")
    if pend:
        nums = "  ".join(d.strftime("%d") for d in pend)
        print(f"    Pendientes: {nums}")


# ── Sincronización al Sheet ────────────────────────────────────────────────────
def _load_seen_sheet():
    """Carga el registro de fechas ya sincronizadas al Sheet."""
    ss_path = Path(__file__).parent / "references" / "seen_sheet.json"
    if ss_path.exists():
        try: return json.loads(ss_path.read_text(encoding='utf-8')), ss_path
        except Exception: pass
    return {}, ss_path

def _mark_seen_sheet(ss_path, d):
    """Marca una fecha como sincronizada en seen_sheet.json."""
    try:
        ss = {}
        if ss_path.exists():
            try: ss = json.loads(ss_path.read_text(encoding='utf-8'))
            except Exception: pass
        ss[str(d)] = {"fecha": d.strftime('%Y-%m-%d')}
        ss_path.parent.mkdir(exist_ok=True)
        ss_path.write_text(json.dumps(ss, ensure_ascii=False), encoding='utf-8')
    except Exception: pass

def sincronizar_al_sheet(con_datos: dict, solo_anio: int = None, solo_nuevas: bool = True):
    """
    Exporta al Sheet los JSONs locales con datos energéticos.
    solo_nuevas=True  → solo fechas NO en seen_sheet.json (delta, rápido)
    solo_nuevas=False → todas las fechas del rango (re-sync forzado)
    """
    import time
    seen_sheet, ss_path = _load_seen_sheet()
    archivos = []
    ya_ok = 0
    for d in sorted(con_datos.keys()):
        if solo_anio and d.year != solo_anio:
            continue
        if solo_nuevas and str(d) in seen_sheet:
            ya_ok += 1
            continue
        fname = f"energy_extraido_{d.strftime('%Y%m%d')}.json"
        fpath_json = os.path.join(OUTPUT_DIR, fname)
        if os.path.exists(fpath_json):
            archivos.append((d, fpath_json))

    if not archivos:
        if ya_ok > 0:
            print(f"  ✓ Sheet al día ({ya_ok} fechas ya sincronizadas).")
        else:
            print("  No hay archivos que sincronizar.")
        return 0

    print(f"\n  Sincronizando {len(archivos)} fechas al Sheet"
          + (f" (saltando {ya_ok} ya sincronizadas)" if ya_ok else ""))
    print("  sheets_exporter.py omite registros duplicados automáticamente.\n")

    ok = errores = 0
    errores_detalle = []
    for i, (d, fpath_json) in enumerate(archivos, 1):
        sys.stdout.write(f"\r  [{i}/{len(archivos)}] {d.strftime('%Y-%m-%d')}...   ")
        sys.stdout.flush()
        intentos = 0
        while intentos < 3:
            result = subprocess.run(
                [sys.executable, "sheets_exporter.py", fpath_json],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                ok += 1
                _mark_seen_sheet(ss_path, d)
                break
            # Reintento si parece rate-limit (429 o quota)
            err_txt = (result.stderr or result.stdout or "").strip()
            if "429" in err_txt or "quota" in err_txt.lower() or "RESOURCE_EXHAUSTED" in err_txt:
                intentos += 1
                if intentos < 3:
                    time.sleep(30)  # esperar 30s y reintentar
                    continue
            # Error no recuperable
            err_lines = [l for l in err_txt.splitlines() if l.strip()]
            err_short = " | ".join(err_lines[-2:]) if err_lines else "(sin mensaje)"
            errores += 1
            errores_detalle.append(f"{d}: {err_short[:120]}")
            break
        else:
            errores += 1
        # Pausa entre llamadas para no saturar la API (max ~60 req/min)
        time.sleep(1.1)

    print(f"\n\n  Resultado: {ok} OK  |  {errores} errores de {len(archivos)} archivos.")
    if errores_detalle:
        print("\n  Errores:")
        for e in errores_detalle[:10]:
            print(f"    {e}")
        if len(errores_detalle) > 10:
            print(f"    ... y {len(errores_detalle)-10} más")
    return ok


def reconstruir_sheet():
    """Llama a sheets_rebuild.py — borra el Sheet y lo reconstruye desde cero."""
    print()
    print("  ADVERTENCIA: Esto borrará el Sheet entero y lo reconstruirá")
    print("  desde todos los JSONs locales con datos energéticos.")
    print("  Es más lento pero garantiza sincronización perfecta.")
    resp = input("\n  Continuar? [s/N]: ").strip().lower()
    if resp != 's':
        print("  Cancelado.")
        return
    print()
    subprocess.run([sys.executable, "sheets_rebuild.py"])


# ── Selector de fechas pendientes ──────────────────────────────────────────────
def seleccionar_fechas_pendientes(hoy: date, procesadas: set):
    """Selecciona fechas sin JSON local para correr el pipeline."""
    anios = list(range(FECHA_INICIO.year, hoy.year + 1))

    pend_por_anio = {}
    pend_por_mes  = {}
    for anio in anios:
        lista = []
        for mes in range(1, 13):
            dias = dias_habiles_mes(anio, mes, hoy)
            pend = [d for d in dias if d not in procesadas]
            if pend:
                pend_por_mes[(anio, mes)] = pend
                lista.extend(pend)
        if lista:
            pend_por_anio[anio] = lista

    todas = sorted(d for v in pend_por_anio.values() for d in v)

    if not todas:
        print("\n  No hay fechas pendientes de procesar.\n")
        return []

    while True:
        print()
        print("  ¿Qué fechas procesar con el pipeline?\n")
        print(f"  1   Todas las pendientes  ({len(todas)} fechas)")
        print()
        n = 2
        ops_anio = {}
        for anio in anios:
            if anio in pend_por_anio:
                print(f"  {n}   Año {anio}  ({len(pend_por_anio[anio])} fechas)")
                ops_anio[str(n)] = anio
                n += 1
        print(f"\n  {n}   Mes específico")
        n_mes = n; n += 1
        print(f"  {n}   Rango personalizado")
        n_rng = n
        print(f"  0   Atrás\n")

        el = input("  Opción: ").strip()
        if el == "0":
            return None
        if el == "1":
            return todas
        if el in ops_anio:
            return sorted(pend_por_anio[ops_anio[el]])
        if el == str(n_mes):
            return _sel_mes(hoy, procesadas, pend_por_mes, anios)
        if el == str(n_rng):
            return _sel_rango(todas)
        print("  Opción no válida.")


def _sel_mes(hoy, procesadas, pend_por_mes, anios):
    print()
    ops_a = {}
    for i, a in enumerate(anios, 1):
        nm = sum(1 for (yr, m) in pend_por_mes if yr == a)
        print(f"  {i}   {a}  ({nm} meses con pendientes)")
        ops_a[str(i)] = a
    print("  0   Atrás\n")
    el = input("  Año: ").strip()
    if el == "0" or el not in ops_a:
        return []
    anio_sel = ops_a[el]
    print()
    ops_m = {}
    n = 1
    for mes in range(1, 13):
        if (anio_sel, mes) in pend_por_mes:
            dias = dias_habiles_mes(anio_sel, mes, hoy)
            mostrar_detalle_mes(anio_sel, mes, dias, procesadas)
            print(f"          -> opción {n}")
            ops_m[str(n)] = (anio_sel, mes)
            n += 1
    print("\n  0   Atrás\n")
    el = input("  Mes: ").strip()
    if el == "0" or el not in ops_m:
        return []
    a, m = ops_m[el]
    return sorted(pend_por_mes[(a, m)])


def _sel_rango(todas):
    print()
    try:
        s = input("  Inicio (YYYYMMDD): ").strip()
        e = input("  Fin    (YYYYMMDD): ").strip()
        sd = date(int(s[:4]), int(s[4:6]), int(s[6:]))
        ed = date(int(e[:4]), int(e[4:6]), int(e[6:]))
        sel = [d for d in todas if sd <= d <= ed]
        if not sel:
            print("  No hay fechas pendientes en ese rango.")
        return sel
    except Exception:
        print("  Formato inválido.")
        return []


# ── Procesado con pipeline ─────────────────────────────────────────────────────
def procesar_fecha(d: date, api_key: str) -> bool:
    fecha = d.strftime("%Y%m%d")
    print(f"\n  -- {fecha}  ({MES_ABBR[d.month]} {d.day}, {d.year}) " + "-" * 28)
    subprocess.run(
        [sys.executable, "pipeline.py", "--fecha", fecha,
         "--boletines"] + BOLETINES + ["--api-key", api_key]
    )
    out = os.path.join(OUTPUT_DIR, f"energy_extraido_{fecha}.json")
    if os.path.exists(out):
        subprocess.run([sys.executable, "sheets_exporter.py", out])
        print(f"  OK  {fecha} exportado")
        return True
    # Pipeline no creó fichero (0 items relevantes o festivo).
    # Crear JSON vacío para que la fecha quede marcada como procesada
    # y no vuelva a aparecer como pendiente en futuros arranques.
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    import json as _json
    with open(out, "w", encoding="utf-8") as _f:
        _json.dump({"fecha": fecha, "total": 0, "energeticos": 0,
                    "descartados": 0, "exitosos": 0, "errores": 0,
                    "tokens": {"input": 0, "output": 0}, "coste_usd": 0.0,
                    "alertas_capacidad_liberada": 0, "mw_totales_liberados": 0.0,
                    "resultados": []}, _f)
    print(f"  --  {fecha}: sin items energéticos (marcado como procesado)")
    return False


def regenerar_projects():
    print()
    print("  Regenerando projects.json...")
    try:
        import project_resolver as pr, json as _json
        records  = pr.load_all_records(pr.OUTPUT_DIR)
        uf, conf = pr.resolve_projects(records)
        projs    = pr.build_projects(records, uf)
        with open('projects.json', 'w', encoding='utf-8') as f:
            _json.dump({'version': '1.0', 'generado': date.today().isoformat(),
                        'total': len(projs), 'proyectos': projs},
                       f, ensure_ascii=False, indent=2)
        multi = sum(1 for p in projs if p['n_publicaciones'] > 1)
        print(f"  OK  {len(projs)} proyectos ({multi} con trazabilidad múltiple)")
    except Exception as e:
        print(f"  WARN  No se pudo regenerar projects.json: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    modo_sync    = "--sync"    in sys.argv
    modo_rebuild = "--rebuild" in sys.argv
    args_key = [a for a in sys.argv[1:] if not a.startswith('--')]

    print()
    print("=" * 72)
    print("  NODALYS — Alimentar base de datos")
    print(f"  Histórico desde {FECHA_INICIO}  |  Boletines: {len(BOLETINES)}  |  Hoy: {date.today()}")
    print("=" * 72)

    hoy = date.today()
    procesadas, con_datos, sin_datos = analizar_locales()

    # Mostrar resumen de datos locales
    resumir_locales(con_datos, hoy)

    # Modo rebuild directo
    if modo_rebuild:
        reconstruir_sheet()
        return

    # Modo sync directo
    if modo_sync:
        sincronizar_al_sheet(con_datos)
        return

    # Tabla de estado (pipeline)
    total_pend = mostrar_estado(hoy, procesadas, con_datos)

    # ── Menú principal ─────────────────────────────────────────────────────────
    n_con_datos = len(con_datos)

    while True:
        print()
        print("  ¿Qué quieres hacer?\n")
        # Detectar JSONs con datos que aún no están en el Sheet (heurístico: comparar con seen_sheet)
        _ss_now, _ = _load_seen_sheet()
        _n_nuevas = sum(1 for d,n in con_datos.items() if str(d) not in _ss_now and n > 0)
        _sync_lbl = f"  ⚠️  {_n_nuevas} pendientes" if _n_nuevas else "  ✓ al día"
        print(f"  1   Procesar fechas pendientes          ({total_pend} fechas sin JSON)")
        print(f"  2   Sincronizar fechas nuevas al Sheet  ({_n_nuevas} fechas){_sync_lbl}")
        print(f"  3   Re-sincronizar año completo         (forzado)")
        print(f"  4   Re-sincronizar rango de fechas      (forzado)")
        print(f"  5   Reconstruir Sheet desde cero")
        print(f"  0   Salir\n")

        el = input("  Opción: ").strip()

        if el == "0":
            print()
            return

        # ── Opción 1: procesar pendientes ──────────────────────────────────────
        if el == "1":
            if total_pend == 0:
                print("  No hay fechas pendientes.")
                continue

            # API key
            api_key = args_key[0] if args_key else ""
            if not api_key:
                env_path = Path(__file__).parent / ".env"
                if env_path.exists():
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        if line.strip().startswith("ANTHROPIC_API_KEY="):
                            api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not api_key:
                api_key = input("\n  Anthropic API key: ").strip()
            if not api_key:
                print("  ERROR: se necesita la API key.")
                continue

            seleccion = seleccionar_fechas_pendientes(hoy, procesadas)
            if not seleccion:
                continue

            primera, ultima = seleccion[0], seleccion[-1]
            print(f"\n  Pipeline: {len(seleccion)} fechas "
                  f"({primera.strftime('%Y-%m-%d')} → {ultima.strftime('%Y-%m-%d')})")
            resp = input("  Comenzar? [Enter=Sí / n=No]: ").strip().lower()
            if resp == "n":
                continue

            ok = 0
            for d in seleccion:
                if procesar_fecha(d, api_key):
                    ok += 1

            regenerar_projects()
            print(f"\n  COMPLETADO: {ok}/{len(seleccion)} fechas con resultados")
            # Actualizar estado
            procesadas, con_datos, sin_datos = analizar_locales()
            total_pend = mostrar_estado(hoy, procesadas, con_datos)

        # ── Opción 2: sincronizar SOLO fechas nuevas (delta) ─────────────────
        elif el == "2":
            _ss, _ssp = _load_seen_sheet()
            _nuevas = sorted(d for d,n in con_datos.items() if str(d) not in _ss and n > 0)
            if not _nuevas:
                print("  ✓ Sheet ya al día — no hay fechas nuevas que sincronizar.")
                print("    Usa opción 3 para forzar re-sync de un año completo.")
                continue
            print(f"\n  {len(_nuevas)} fechas nuevas: {_nuevas[0]} → {_nuevas[-1]}")
            resp = input(f"  Sincronizar ahora? [Enter=Sí / n=No]: ").strip().lower()
            if resp == "n": continue
            ok2 = sincronizar_al_sheet(con_datos, solo_nuevas=True)
            if ok2 > 0: regenerar_projects()

        # ── Opción 3: re-sincronizar año completo (forzado) ───────────────────
        elif el == "3":
            anios_disponibles = sorted(set(d.year for d in con_datos))
            if not anios_disponibles:
                print("  No hay datos locales."); continue
            _ss, _ssp = _load_seen_sheet()
            print()
            for i, a in enumerate(anios_disponibles, 1):
                n_f  = sum(1 for d in con_datos if d.year == a)
                n_ns = sum(1 for d in con_datos if d.year == a and str(d) not in _ss and con_datos[d] > 0)
                flag = f"  ← {n_ns} sin sync" if n_ns else "  ✓ al día"
                print(f"  {i}   {a}  ({n_f} fechas){flag}")
            print("  0   Atrás\n")
            sub = input("  Año (re-sync forzado): ").strip()
            if sub == "0": continue
            try:
                anio_sel = anios_disponibles[int(sub)-1]
                n_f = sum(1 for d in con_datos if d.year == anio_sel)
                resp = input(f"  Re-sincronizar {n_f} fechas de {anio_sel}? [Enter=Sí / n=No]: ").strip().lower()
                if resp == "n": continue
                ok3 = sincronizar_al_sheet(con_datos, solo_anio=anio_sel, solo_nuevas=False)
                if ok3 > 0: regenerar_projects()
            except (ValueError, IndexError):
                print("  Opción no válida.")

        # ── Opción 4: re-sincronizar rango de fechas ──────────────────────────
        elif el == "4":
            print()
            try:
                s = input("  Inicio (YYYYMMDD): ").strip()
                e = input("  Fin    (YYYYMMDD): ").strip()
                sd = date(int(s[:4]),int(s[4:6]),int(s[6:]))
                ed = date(int(e[:4]),int(e[4:6]),int(e[6:]))
                rango = {d:n for d,n in con_datos.items() if sd <= d <= ed and n > 0}
                if not rango:
                    print("  No hay fechas con datos en ese rango."); continue
                print(f"  {len(rango)} fechas en el rango")
                resp = input("  Sincronizar? [Enter=Sí / n=No]: ").strip().lower()
                if resp == "n": continue
                ok4 = sincronizar_al_sheet(rango, solo_nuevas=False)
                if ok4 > 0: regenerar_projects()
            except ValueError:
                print("  Formato de fecha inválido.")

        # ── Opción 5: reconstruir Sheet desde cero ────────────────────────────
        elif el == "5":
            print()
            print("  ADVERTENCIA: Borra y reconstruye el Sheet entero desde cero.")
            resp = input("  ¿Confirmar? [s/N]: ").strip().lower()
            if resp == "s":
                reconstruir_sheet()

        else:
            print("  Opción no válida.")


if __name__ == "__main__":
    main()
