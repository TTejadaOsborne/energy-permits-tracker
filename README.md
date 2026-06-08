# Energy Permits Tracker — Despliegue completo

## Arquitectura

```
Pipeline Python (local) → Google Sheets → Web pública (GitHub Pages)
                ↑                               ↓
           Ejecución diaria               URL permanente
```

## Setup completo (20-30 minutos, una sola vez)

\---

### PASO 1 — Google Sheets

1. Ve a sheets.google.com y crea una hoja nueva
2. Nómbrala "Energy Permits Tracker"
3. En la pestaña inferior, renombra "Hoja 1" → "Permisos"
4. Copia la URL: `https://docs.google.com/spreadsheets/d/{SPREADSHEET\_ID}/edit`
Guarda el SPREADSHEET\_ID (cadena larga entre /d/ y /edit)
5. Compartir → "Cualquiera con el enlace" → "Lector"

\---

### PASO 2 — Google Cloud API Key (gratuita)

1. Ve a console.cloud.google.com
2. Crea proyecto nuevo (o usa uno existente)
3. Menú → APIs y servicios → Biblioteca
4. Busca "Google Sheets API" → Habilitar
5. Menú → APIs y servicios → Credenciales → Crear credencial → Clave de API
6. Copia la API Key generada
7. (Recomendado) Editar clave → Restricciones de API → Google Sheets API
8. (Recomendado) Restricciones de aplicación → HTTP referrers → añade tu URL de GitHub Pages

\---

### PASO 3 — Configurar el exportador Python

Edita `sheets\_exporter.py` y rellena:

```python
SPREADSHEET\_ID = "tu\_id\_aqui"    # del paso 1
API\_KEY        = "tu\_key\_aqui"   # del paso 2
SHEET\_NAME     = "Permisos"
```

Copia `sheets\_exporter.py` a la carpeta del pipeline (Nodalys/).

\---

### PASO 4 — Integrar el exportador en el pipeline

Abre `pipeline.py` y añade al final de la función `run()`, justo antes del `return resultado`:

```python
    # Exportar a Google Sheets
    try:
        from sheets\_exporter import exportar\_a\_sheets, SPREADSHEET\_ID
        if SPREADSHEET\_ID != "TU\_SPREADSHEET\_ID\_AQUI":
            out\_file = f"output/energy\_extraido\_{fecha}.json"
            sheets\_stats = exportar\_a\_sheets(out\_file)
            print(f"  Sheets: +{sheets\_stats.get('exportados',0)} filas")
    except Exception as e:
        print(f"  Sheets error: {e}")
```

Prueba:

```cmd
python pipeline.py --fecha 20260428 --boletines BOE BOCyL --api-key TU\_KEY
```

Debería aparecer la línea "Sheets: +N filas" y los datos en el Google Sheet.

\---

### PASO 5 — Publicar la web en GitHub Pages (gratis, URL pública)

1. Crea cuenta en github.com si no tienes
2. Crea repositorio nuevo: "energy-permits-tracker" → Public
3. Edita `index.html` y rellena en CONFIG:

```js
   const CONFIG = {
     SPREADSHEET\_ID: "tu\_id\_del\_paso\_1",
     API\_KEY:        "tu\_key\_del\_paso\_2",
     SHEET\_NAME:     "Permisos",
   };
   ```

4. Sube el `index.html` al repositorio (arrastra el archivo en la web de GitHub)
5. Repositorio → Settings → Pages → Source: "Deploy from branch" → branch: main → /root
6. Guardar. En 2-3 minutos tu URL será:
`https://TU\_USUARIO.github.io/energy-permits-tracker/`

\---

### PASO 6 — Automatización diaria (Windows Task Scheduler)

Crea el archivo `run\_daily.bat` en la carpeta Nodalys:

```batch
@echo off
cd /d "C:\\ruta\\a\\tu\\carpeta\\Nodalys"
python pipeline.py --ayer --boletines BOE BOCyL BOCM DOCM --api-key TU\_API\_KEY\_ANTHROPIC
```

Task Scheduler (Programador de tareas de Windows):

1. Busca "Programador de tareas" en el menú inicio
2. Crear tarea básica → Nombre: "Energy BOE Daily"
3. Desencadenador: Diariamente → hora: 09:00
4. Acción: Iniciar un programa → Programa: `C:\\ruta\\a\\Nodalys\\run\_daily.bat`
5. Finalizar

A partir de entonces, cada mañana a las 9:00 el pipeline descarga los boletines del día anterior,
extrae los datos con IA, y los vuelca automáticamente al Google Sheet.
La web se actualiza en tiempo real al refrescar la página.

\---

## Flujo diario automatizado

```
09:00 AM → Task Scheduler ejecuta run\_daily.bat
         → pipeline.py scrape BOE + BOCyL + BOCM + DOCM
         → Claude API extrae datos
         → sheets\_exporter.py vuelca filas nuevas a Google Sheets
         → Tu URL pública muestra los datos actualizados
```

## Coste mensual estimado (20 días laborables) 

* Google Sheets API: GRATIS (límite 300 req/min, uso real \~20/día)
* GitHub Pages: GRATIS
* Claude API (Haiku): \~$0.50-2.00/mes según volumen de publicaciones
* Coste total: < $2/mes

