# Nodalys — Guía de Operación

Última actualización: 2026-06-03

---

## Índice
1. [Carga inicial completa](#1-carga-inicial-completa)
2. [Actualización diaria automática](#2-actualización-diaria-automática)
3. [Actualización mensual de capacidades (Excel Monitor)](#3-actualización-mensual-de-capacidades)
4. [Análisis de afloramientos y nuevos patrones](#4-análisis-de-afloramientos)
5. [Reparación de errores](#5-reparación-de-errores)
6. [Estructura de scripts](#6-estructura-de-scripts)

---

## 1. Carga inicial completa

> Ejecutar una sola vez para sincronizar todo desde cero.  
> Orden obligatorio. Desde la carpeta `Nodalys/`.

### Paso 1 — Procesar fechas sin JSON

```bash
python alimentar_bbdd.py
# → Opción 1 → Todas las pendientes
# Introduce la Anthropic API key cuando se solicite
```

**Qué hace:** ejecuta el pipeline (scraping + extracción LLM) para cada día laborable sin JSON local. Crea `output/energy_extraido_YYYYMMDD.json` por cada fecha.

**Duración estimada:** 1-3 min por fecha con datos (≈ $0.05-0.20 USD/día con datos).

---

### Paso 2 — Reparar JSONs con errores

```bash
python repair_errors.py
# Ver resumen de errores

python repair_errors.py --fix
# Re-procesa todas las fechas con errores (conexión, API, parse)
# También acepta: --fix --year 2023  (solo un año)
```

---

### Paso 3 — Re-scrape retroactivo BOE-B

> Los anuncios de particulares (BOE-B) no se capturaban antes.

```bash
# Ver volumen primero (sin gastar API)
python rescrape_boeb.py --solo-listado --desde 20240101

# Ejecutar extracción
python rescrape_boeb.py --desde 20240101
```

**Qué hace:** raspa el índice HTML `boe.es/boe/dias/YYYY/MM/DD/index.php?s=B` para cada fecha, extrae los proyectos BOE-B nuevos y los combina con los JSONs existentes sin sobreescribir datos BOE-A.

---

### Paso 4 — Sincronizar todo al Sheet y publicar

```bash
python sync_all.py --no-pipeline
```

**Qué hace en orden:**
1. Sube al Sheet las fechas no sincronizadas (salta duplicados automáticamente)
2. Regenera `projects.json` + `projects_data.js`
3. `git commit` + `git push` → actualiza GitHub Pages

---

### Paso 5 — Actualizar capacidades SETs (ver sección 3)

```bash
# Asegúrate de tener el Monitor_ actualizado antes
python parse_monitor.py
python generate_sets_capacity.py
python generate_sets_history.py
```

---

## 2. Actualización diaria automática

> Un solo comando. Ejecutar cada día laborable (o programar con el scheduler).

```bash
python sync_all.py
```

**Flujo completo:**
```
Scraping boletines (BOE + BOE-B + CCAA)
    ↓
Extracción LLM (solo ítems relevantes)
    ↓
Exportar al Sheet (sin duplicados)
    ↓
Regenerar projects.json + projects_data.js
    ↓
git push → GitHub Pages actualizado
```

**Para programar diariamente** (Windows Task Scheduler):
```bash
# El fichero task_scheduler_setup.xml ya está configurado
# Importarlo en el Programador de tareas de Windows:
# Inicio → Programador de tareas → Importar tarea → task_scheduler_setup.xml
```

**Para programar manualmente** (un día específico):
```bash
python pipeline.py --fecha 20260610 --boletines BOE BOCyL BOJA
```

---

## 3. Actualización mensual de capacidades

> Cuando actualices el fichero `Monitor_Capacidad_Red_INTEGRADO_v4.xlsx`.

### Paso 1 — Sustituir el Excel Monitor

Reemplaza el fichero en la carpeta `Nodalys/`:
```
Monitor_Capacidad_Red_INTEGRADO_v4.xlsx  ← nuevo fichero
```

### Paso 2 — Parsear y regenerar capacidades

```bash
# Extraer snapshots de capacidad del Excel consolidado
python parse_monitor.py

# Regenerar sets_capacity.json (capacidades actuales de cada SET)
python generate_sets_capacity.py

# Regenerar sets_history.json (histórico de evolución)
python generate_sets_history.py
```

### Paso 3 — Si tienes nuevos Excels individuales de operadoras (REE/iDE/Endesa/UFD)

```bash
# Solo cuando haya nuevos ficheros descargados de cada operadora
python parse_ree.py      --excel "REE_MPE_*.xlsx"
python parse_eredes.py   --excel "iDE_capacidad_*.xlsx"
python parse_endesa.py   --excel "Endesa_acceso_*.xlsx"
python parse_ufd.py      --excel "UFD_capacidad_*.xlsx"

# Después, reconstruir el histórico consolidado
python build_capacity_history.py
python generate_sets_capacity.py
python generate_sets_history.py
```

### Paso 4 — Publicar

```bash
python sync_all.py --no-pipeline
```

---

## 4. Análisis de afloramientos

> Identificar nuevos patrones y proyectos con capacidad que puede liberarse.

### Afloramientos activos (permisos desfavorables recientes)

```bash
# Analiza el lag entre fecha de denegación y fecha de afloramiento real
python analyze_adverse_lag.py

# Genera previsiones de cuándo aflorarán capacidades pendientes
python generate_adverse_forecast.py

# Ver el resultado en la herramienta → pestaña SETs → panel Afloramientos
```

**Qué buscar en los resultados:**
- SETs con muchos MW denegados en los últimos 6-12 meses → alta probabilidad de afloramiento
- Proyectos con `estado = desfavorable/caducado/archivado` con fechas recientes
- SETs donde la capacidad disponible aumentó respecto al mes anterior

### Proyectos cerca de resolución (patrones históricos)

```bash
# Analiza patrones de tiempo entre IP y resolución por tipo de permiso
python analyze_capacity_patterns.py

# Genera previsión de capacidad futura por SET
python generate_capacity_forecast.py
```

**Señales de alerta a revisar mensualmente:**
1. En la pestaña **SETs**: busca SETs con `capacidad disponible > 50 MW` y `proyectos en tramitación > 200 MW` → saturación inminente
2. En **Búsqueda**: filtra por `Estado = Inf. Pública` + `Permiso = DUP` → proyectos casi al final del proceso
3. En **Dashboard**: pico de `MW tramitados` en una CCAA → actividad regulatoria concentrada

### Informe mensual de nuevos BOE-B

```bash
# Ver qué publicaciones BOE-B nuevas hay en el último mes
python rescrape_boeb.py --solo-listado --desde $(date -d "1 month ago" +%Y%m%d 2>/dev/null || python -c "from datetime import date,timedelta; print((date.today()-timedelta(days=30)).strftime('%Y%m%d'))")
```

---

## 5. Reparación de errores

### JSONs corruptos (energeticos>0, resultados=[])

```bash
python repair_corrupt_jsons.py        # ver cuáles hay
python repair_corrupt_jsons.py --fix  # reparar
```

### JSONs con errores de extracción

```bash
python repair_errors.py               # ver resumen
python repair_errors.py --fix         # reparar todos
python repair_errors.py --fix --year 2023  # solo un año
```

### Sheet desincronizado respecto a la herramienta

```bash
python alimentar_bbdd.py
# → Opción 2: Sincronizar datos locales al Sheet
```

---

## 6. Estructura de scripts

| Script | Cuándo usar | Frecuencia |
|--------|-------------|------------|
| `sync_all.py` | Actualización completa (pipeline + sheet + push) | **Diaria** |
| `alimentar_bbdd.py` | Menú interactivo para tareas específicas | A demanda |
| `parse_monitor.py` | Leer nuevo Excel Monitor_ | **Mensual** |
| `generate_sets_capacity.py` | Regenerar capacidades SETs | Tras parse_monitor |
| `generate_sets_history.py` | Regenerar histórico SETs | Tras parse_monitor |
| `analyze_adverse_lag.py` | Analizar lags denegación→afloramiento | **Mensual** |
| `generate_adverse_forecast.py` | Previsión afloramientos futuros | **Mensual** |
| `analyze_capacity_patterns.py` | Patrones históricos de resolución | Trimestral |
| `generate_capacity_forecast.py` | Previsión capacidad futura por SET | Trimestral |
| `repair_errors.py` | Reparar JSONs con errores de API/red | Tras incidencias |
| `repair_corrupt_jsons.py` | Reparar JSONs con resultados vacíos | Tras incidencias |
| `rescrape_boeb.py` | Re-scrape retroactivo BOE-B | Una vez + a demanda |
| `rescrape_boeb.py --solo-listado` | Ver BOE-B nuevos sin extraer | Semanal |
| `reextract_gaps.py` | Re-extraer gaps en el histórico | A demanda |
| `project_resolver.py` | Regenerar projects.json solo | A demanda |
| `sheets_rebuild.py` | Reconstruir Sheet desde cero | Solo si hay corrupción grave |

---

## Workflow mensual resumido (checklist)

```
□ 1. python sync_all.py                          → procesar días nuevos + push
□ 2. python repair_errors.py --fix               → reparar si hay errores
□ 3. [Sustituir Monitor_Capacidad_Red_*.xlsx]
□ 4. python parse_monitor.py                     → parsear Excel
□ 5. python generate_sets_capacity.py            → actualizar SETs
□ 6. python generate_sets_history.py             → histórico SETs
□ 7. python analyze_adverse_lag.py               → lags afloramientos
□ 8. python generate_adverse_forecast.py         → previsiones
□ 9. python sync_all.py --no-pipeline            → publicar todo
□ 10. Revisar herramienta: Dashboard + SETs + Búsqueda
```

---

## Variables de entorno requeridas

Crea un fichero `.env` en la carpeta `Nodalys/`:
```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx
```

O pásala directamente a los scripts:
```bash
python sync_all.py sk-ant-xxxxxxxxxx
python rescrape_boeb.py --desde 20250101 sk-ant-xxxxxxxxxx
```
