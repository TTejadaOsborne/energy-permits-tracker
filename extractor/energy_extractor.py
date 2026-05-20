"""
Extractor especializado en proyectos de energía renovable, transmisión y distribución.
Extrae el schema completo definido para análisis de capacidad liberada en subestaciones.

Campos extraídos por item:
  - nombre_proyecto
  - numero_expediente (Industria / Medio Ambiente)
  - promotor
  - tecnologia (eólica, FV, BESS, H2, Data Center, LAT, SET...)
  - potencia_mw
  - tipo_permiso (DIA, AA previa, AA construcción, AA explotación, UP, servidumbre...)
  - estado_permiso (favorable, desfavorable, desistido, caducado, en tramitación, otorgado...)
  - subestacion_conexion (nombre SET + tensión si disponible)
  - gestor_red (REE / nombre DSO)
  - municipio
  - provincia
  - ccaa
  - fecha_resolucion
  - capacidad_mw_liberada (inferida cuando estado = desfavorable/desistido/caducado)
  - observaciones
  - confianza (0.0-1.0 por campo crítico)
"""

import anthropic
import json
import os
import re
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ─── TAXONOMÍA COMPLETA DE PERMISOS ──────────────────────────────────────────
# Usada tanto en el prompt como en el dashboard para validación cruzada

TIPOS_PERMISO = {
    # ── TRAMITACIÓN AMBIENTAL ─────────────────────────────────────────────────
    "EsIA":        "Estudio de Impacto Ambiental (sometido a información pública)",
    "DIA":         "Declaración de Impacto Ambiental",
    "AAI":         "Autorización Ambiental Integrada",
    "AAU":         "Autorización Ambiental Unificada",
    "IPA":         "Información Pública Ambiental",
    # ── TRAMITACIÓN ENERGÉTICA ────────────────────────────────────────────────
    "IP":          "Información Pública (energética, sin carácter ambiental)",
    "AAP":         "Autorización Administrativa Previa",
    "AAC":         "Autorización Administrativa de Construcción",
    "AAE":         "Autorización Administrativa de Explotación",
    "AAP_AAC":     "Autorización Administrativa Previa y de Construcción (tramitación conjunta)",
    "ModAAP":      "Modificación de Autorización Administrativa Previa",
    "ModAAC":      "Modificación de Autorización Administrativa de Construcción",
    "ModAAE":      "Modificación de Autorización Administrativa de Explotación",
    # ── UTILIDAD PÚBLICA Y SERVIDUMBRES ──────────────────────────────────────
    "DUP":         "Declaración de Utilidad Pública",
    "LAP":         "Levantamiento de Actas Previas a la Ocupación",
    "Servidumbre": "Servidumbre de Paso (imposición)",
    "OcupacionUP": "Ocupación definitiva / Acta de Replanteo",
    # ── ACCESO Y CONEXIÓN ─────────────────────────────────────────────────────
    "PtoConexion": "Autorización de Punto de Conexión / Acceso y Conexión",
    "ModConexion": "Modificación de Punto de Conexión",
    # ── REGISTRO ──────────────────────────────────────────────────────────────
    "InscReg":     "Inscripción en Registro (RIPRE, RAIPRE, RECORE, REER...)",
    "BajReg":      "Baja en Registro",
    # ── URBANISMO / PLAN ESPECIAL ─────────────────────────────────────────────
    "PlanEsp":     "Plan Especial Urbanístico",
    "LicObras":    "Licencia de Obras",
    # ── OTROS ─────────────────────────────────────────────────────────────────
    "Concesion":   "Concesión de uso de dominio público (hidráulico, marítimo...)",
    "Otro":        "Otro tipo de permiso no clasificado",
}

ESTADOS_PERMISO = {
    # ── ESTADOS POSITIVOS (proyecto avanza) ───────────────────────────────────
    "favorable":           {"label": "Favorable",              "libera": False, "fallido": False},
    "otorgado":            {"label": "Otorgado / Concedido",   "libera": False, "fallido": False},
    "no_necesario":        {"label": "No Necesario",           "libera": False, "fallido": False},
    # ── ESTADOS EN PROCESO ────────────────────────────────────────────────────
    "informacion_publica": {"label": "Información Pública",    "libera": False, "fallido": False},
    "en_tramitacion":      {"label": "En Tramitación",         "libera": False, "fallido": False},
    "suspendido":          {"label": "Suspendido",             "libera": False, "fallido": False},
    # ── ESTADOS NEGATIVOS — LIBERAN CAPACIDAD ────────────────────────────────
    "desfavorable":        {"label": "Desfavorable",           "libera": True,  "fallido": True},
    "denegado":            {"label": "Denegado",               "libera": True,  "fallido": True},
    "desistido":           {"label": "Desistido / Renuncia",   "libera": True,  "fallido": True},
    "caducado":            {"label": "Caducado",               "libera": True,  "fallido": True},
    "archivado":           {"label": "Archivado",              "libera": True,  "fallido": True},
    "revocado":            {"label": "Revocado / Anulado",     "libera": True,  "fallido": True},
    "inadmitido":          {"label": "Inadmitido a trámite",   "libera": True,  "fallido": True},
    # ── ESTADO INDETERMINADO ──────────────────────────────────────────────────
    "otro":                {"label": "Otro",                   "libera": False, "fallido": False},
}

ESTADOS_FALLIDOS = {k for k, v in ESTADOS_PERMISO.items() if v["fallido"]}
ESTADOS_LIBERAN  = {k for k, v in ESTADOS_PERMISO.items() if v["libera"]}

# ─── PROMPT SISTEMA — DOMINIO EXPERTO ────────────────────────────────────────
SYSTEM_PROMPT = """Eres un experto en regulación energética española especializado en la tramitación administrativa de instalaciones de generación renovable, almacenamiento energético, hidrógeno verde, centros de datos e infraestructuras de red eléctrica.

Tu función es extraer datos estructurados de resoluciones publicadas en boletines oficiales españoles (BOE, DOGC, BOCM, BOJA, BOCyL y otros).

════════════════════════════════════════════════════════
TAXONOMÍA DE TIPOS DE PERMISO — usa exactamente estas claves
════════════════════════════════════════════════════════

TRAMITACIÓN AMBIENTAL:
  "EsIA"    → Estudio de Impacto Ambiental sometido a información pública
  "DIA"     → Declaración de Impacto Ambiental (resolución final ambiental)
  "AAI"     → Autorización Ambiental Integrada
  "AAU"     → Autorización Ambiental Unificada (algunas CCAA)
  "IPA"     → Información Pública Ambiental (fase previa al EsIA)

TRAMITACIÓN ENERGÉTICA (Industria / MITECO / CCAA):
  "IP"      → Información Pública energética (art. 131 RD 1955/2000 o equivalente autonómico)
  "AAP"     → Autorización Administrativa Previa
  "AAC"     → Autorización Administrativa de Construcción
  "AAE"     → Autorización Administrativa de Explotación
  "AAP_AAC" → Autorización Previa y de Construcción tramitadas conjuntamente
  "ModAAP"  → Modificación de AAP
  "ModAAC"  → Modificación de AAC
  "ModAAE"  → Modificación de AAE

UTILIDAD PÚBLICA Y SERVIDUMBRES:
  "DUP"         → Declaración de Utilidad Pública
  "LAP"         → Levantamiento de Actas Previas a la Ocupación (fase expropiación)
  "Servidumbre" → Imposición de servidumbre de paso
  "OcupacionUP" → Ocupación definitiva / Acta de replanteo

ACCESO Y CONEXIÓN:
  "PtoConexion" → Autorización de punto de conexión / acceso y conexión a la red
  "ModConexion" → Modificación de punto de conexión

REGISTRO:
  "InscReg" → Inscripción en Registro (RIPRE, RAIPRE, RECORE, REER, registros autonómicos)
  "BajReg"  → Baja en Registro

URBANISMO:
  "PlanEsp"  → Plan Especial Urbanístico
  "LicObras" → Licencia de Obras municipal

OTROS:
  "Concesion" → Concesión de uso de dominio público
  "Otro"      → No clasificable en las categorías anteriores

════════════════════════════════════════════════════════
TAXONOMÍA DE ESTADOS — usa exactamente estas claves
════════════════════════════════════════════════════════

POSITIVOS (proyecto avanza):
  "favorable"    → DIA favorable, permiso aprobado con condicionado
  "otorgado"     → Permiso concedido / otorgado sin condiciones especiales
  "no_necesario" → Resolución que declara que el permiso NO es necesario para este proyecto

EN PROCESO:
  "informacion_publica" → Sometido a información pública (cualquier fase)
  "en_tramitacion"      → En tramitación administrativa, sin resolución final
  "suspendido"          → Procedimiento suspendido temporalmente

NEGATIVOS — PROYECTO FALLIDO — LIBERAN CAPACIDAD EN LA SET:
  "desfavorable" → DIA/permiso con resolución desfavorable explícita
  "denegado"     → Permiso denegado (rechazo explícito de la solicitud)
  "desistido"    → Promotor presenta desistimiento o renuncia voluntaria
  "caducado"     → Expediente caducado por transcurso del plazo
  "archivado"    → Expediente archivado (puede incluir casos de falta de subsanación)
  "revocado"     → Permiso previamente otorgado que se revoca o anula
  "inadmitido"   → Solicitud inadmitida a trámite

INDETERMINADO:
  "otro" → Estado no clasificable

════════════════════════════════════════════════════════
TECNOLOGÍAS — mapeo de términos a clave
════════════════════════════════════════════════════════
  "eólica"       → parque eólico, aerogeneradores, turbinas eólicas, wind farm
  "fotovoltaica" → planta solar, fotovoltaico, FV, paneles solares, solar PV
  "BESS"         → almacenamiento, baterías, BESS, sistema de almacenamiento energético
  "H2"           → hidrógeno, electrolizador, H2 verde, hidrógeno renovable
  "Data Center"  → centro de datos, CPD, data center, hyperscaler
  "LAT"          → línea de alta tensión, LAT, LMAT, línea de muy alta tensión, línea de evacuación
  "SET"          → subestación transformadora sin generación propia asociada
  "hidráulica"   → central hidroeléctrica, minicentral, bombeo
  "termosolar"   → central termosolar, CSP, torre solar, cilindro-parabólico
  "biomasa"      → planta de biomasa, biogás, biometano
  "cogeneración" → cogeneración, MCHP
  "FV+BESS"      → solar fotovoltaica con almacenamiento en baterías
  "eólica+BESS"  → parque eólico con almacenamiento en baterías
  "otro"         → no clasificable

════════════════════════════════════════════════════════
IDENTIFICACIÓN DE SUBESTACIONES Y RED
════════════════════════════════════════════════════════
- Busca: "SET [nombre]", "S.E. [nombre]", "subestación [nombre]", "nudo [nombre]"
- Tensiones: 30kV, 45kV, 66kV, 132kV, 220kV, 400kV
- REE/Red Eléctrica Nacional gestiona la red de transporte (≥220kV en general, algunos 132kV)
- Distribuidoras: Endesa Red, E-Distribución, Iberdrola Distribución, UFD, i-DE, Naturgy Distribución, Viesgo
- Si menciona "nudo de REE" o "punto de acceso REE" → gestor_red = "REE"
- El punto de conexión puede estar solo en el título; extráelo igualmente

════════════════════════════════════════════════════════
NUMERACIÓN DE EXPEDIENTES POR CCAA
════════════════════════════════════════════════════════
- Nacional/MITECO: "AT-YYYY/NNNNNN", "EXP-YYYY-NNNN"
- Andalucía: "AT-SE/GR/MA/CO/CA/J/AL/H-YYYY/NNNNN", "2022/EAE/NNNN"
- Catalunya: "IN/YYYY/NNNNN", "2022-IA-NNNN"
- Madrid: "M-AT-YYYY/NNNNN"
- Castilla y León: "BU/VA/LE/ZA/SA/AV/SG/SO/PA-AT-YYYY/NNNNN"
- C. Valenciana: "CS/V/A-AT-YYYY/NNNNN", "EXPTE-YYYY-NNNNN"
- Una misma publicación puede contener expediente de Industria Y de Medio Ambiente

════════════════════════════════════════════════════════
REGLAS CRÍTICAS DE EXTRACCIÓN
════════════════════════════════════════════════════════
1. NOMBRE DEL PROYECTO — regla prioritaria:
   - Busca primero el nombre entre comillas angulares «», comillas "", o precedido de "denominado", "titulado", "proyecto", "instalación"
   - Si no hay nombre explícito, CONSTRUYE uno descriptivo con: tecnología + ubicación principal
     Ejemplos: "Parque Fotovoltaico Arcenillas", "LAT 132kV Perogordo-Valverde del Majano",
               "Subestación Guadalajara Norte", "Planta H2 Siete Iglesias"
   - Usa siempre Título Con Mayúsculas Iniciales (no TODO MAYÚSCULAS)
   - NUNCA dejes nombre_proyecto en null si la tecnología y ubicación son conocidas

2. TECNOLOGÍA — escribe siempre con mayúscula inicial:
   "Eólica", "Fotovoltaica", "BESS", "H2", "Data Center", "LAT", "SET",
   "Hidráulica", "Termosolar", "Biomasa", "Biometano", "Cogeneración", "FV+BESS", "Eólica+BESS", "Otro"
   IMPORTANTE: usa "Biometano" (no "Biomasa") cuando el proyecto produce/inyecta biometano a red

3. Si un dato numérico o de texto no aparece: null — NO INVENTAR

4. "tipo_permiso" y "estado_permiso" DEBEN ser exactamente una de las claves definidas

5. "capacidad_mw_liberada": rellena SOLO si estado ∈ {desfavorable, denegado, desistido, caducado, archivado, revocado, inadmitido} Y potencia_mw está en el texto

6. Una publicación puede tramitar SIMULTÁNEAMENTE varios permisos (ej: AAP+DUP). Usa "permisos_adicionales" para el segundo y sucesivos

7. "es_proyecto_fallido": true si estado ∈ {desfavorable, denegado, desistido, caducado, archivado, revocado, inadmitido}

8. El campo "confianza" (0.0-1.0) refleja tu certeza global

9. Responde ÚNICAMENTE con JSON válido, sin texto adicional, sin bloques markdown

10. "es_proyecto_energetico": true SOLO si el objeto de la publicación es:
    ✓ Generación eléctrica renovable (eólica, solar FV, termosolar, hidráulica, biomasa, biogás, biometano)
    ✓ Almacenamiento de energía (BESS, baterías de gran escala)
    ✓ Hidrógeno verde o renovable (electrolizadores, plantas H2)
    ✓ Infraestructura de red eléctrica de alta tensión (LAT ≥ 66kV, subestaciones de transporte)
    ✓ Centros de datos con impacto significativo en red
    ✓ Cogeneración industrial de alto rendimiento

    false si es cualquier otro tipo de publicación, aunque mencione tecnologías energéticas:
    ✗ Convocatorias de subvenciones, bases reguladoras, programas de ayudas o incentivos
      (aunque sean para proyectos de energía renovable: la convocatoria NO es el proyecto)
    ✗ Redistribución o modificación de créditos presupuestarios para subvenciones energéticas
    ✗ Normativa técnica: proyectos de norma UNE, normas europeas o internacionales (AENOR)
    ✗ Modificaciones de órdenes o decretos sin tramitación de un proyecto concreto
    ✗ Planes de emergencia exterior de instalaciones de combustibles fósiles o gas licuado
    ✗ Concursos de capacidad de acceso (proceso administrativo, no un proyecto)
    ✗ Fábricas (alimentaria, farmacéutica, química, automoción, logística)
    ✗ Gestión de residuos (vertederos, centros de tratamiento, gestores)
    ✗ Infraestructuras portuarias, aeroportuarias, ferroviarias, viarias
    ✗ Líneas de baja/media tensión para alimentar instalaciones puntuales
    ✗ Plantas de tratamiento de agua, depuradoras
    ✗ Planeamiento urbanístico, planes regionales, planes parciales
    ✗ Explotaciones ganaderas, agrícolas o de acuicultura
    ✗ Concentración parcelaria, transformación en regadío
    ✗ Centros de tratamiento de residuos no energéticos
    ✗ Insectos, proteínas, biotecnología no energética

11. "nombre_proyecto": NUNCA uses como nombre del proyecto:
    ✗ Solo una sigla o tecnología: "FV", "H2", "BESS", "Eólica" (sin nombre propio del proyecto)
    ✗ Solo un topónimo: "Madrid", "Sevilla", "Galicia" (sin nombre del proyecto)
    ✗ El nombre de una DG o consejería ("de la Dirección General de...")
    Si no hay nombre propio del proyecto, devuelve nombre_proyecto: null"""

# ─── SCHEMA DE SALIDA ─────────────────────────────────────────────────────────
SCHEMA_CAMPOS = """
{
  "nombre_proyecto": string | null,
  "numero_expediente_industria": string | null,
  "numero_expediente_medioambiente": string | null,
  "promotor": string | null,
  "tecnologia": "Eólica"|"Fotovoltaica"|"BESS"|"H2"|"Data Center"|"LAT"|"SET"|"Hidráulica"|"Termosolar"|"Biomasa"|"Biometano"|"Cogeneración"|"FV+BESS"|"Eólica+BESS"|"Otro" | null,
  "potencia_mw": number | null,
  "tipo_permiso": "EsIA"|"DIA"|"AAI"|"AAU"|"IPA"|"IP"|"AAP"|"AAC"|"AAE"|"AAP_AAC"|"ModAAP"|"ModAAC"|"ModAAE"|"DUP"|"LAP"|"Servidumbre"|"OcupacionUP"|"PtoConexion"|"ModConexion"|"InscReg"|"BajReg"|"PlanEsp"|"LicObras"|"Concesion"|"Otro" | null,
  "permisos_adicionales": [string] | [],
  "estado_permiso": "favorable"|"otorgado"|"no_necesario"|"informacion_publica"|"en_tramitacion"|"suspendido"|"desfavorable"|"denegado"|"desistido"|"caducado"|"archivado"|"revocado"|"inadmitido"|"otro" | null,
  "es_proyecto_fallido": boolean,
  "motivo_fallo": string | null,
  "subestacion_conexion": string | null,
  "tension_conexion_kv": number | null,
  "gestor_red": string | null,
  "municipio": string | null,
  "provincia": string | null,
  "comunidad_autonoma": string | null,
  "fecha_resolucion": string | null,
  "capacidad_mw_liberada": number | null,
  "observaciones": string | null,
  "confianza": number,
  "es_proyecto_energetico": boolean
}"""



def _nombre_desde_titulo(titulo: str, datos: dict) -> str:
    """
    Construye un nombre descriptivo del proyecto a partir del título del boletín
    cuando el modelo IA no pudo extraerlo.
    Estrategia: tecnología + ubicación inferida del título.
    """
    import re

    tech = datos.get("tecnologia", "")
    municipio = datos.get("municipio", "")
    provincia = datos.get("provincia", "")

    # Patrones de nombre explícito en el título
    for patron in [
        r"parque\s+(?:e[o\xf3]lico|fotovoltaico|solar)\s+([A-Z][\w\s\-]{2,35}?)(?:\s+de\s|\s+en\s|,|\.|$)",
        r"planta\s+(?:fotovoltaica|solar|biog[a\xe1]s|hidr[o\xf3]geno)\s+([A-Z][\w\s\-]{2,35}?)(?:\s+de\s|,|\.|$)",
        r"instalaci[o\xf3]n\s+[A-Z][\w\s\-]{2,35}?(?=\s+(?:fotovoltai|e[o\xf3]lic|BESS))",
    ]:
        m = re.search(patron, titulo, re.IGNORECASE)
        if m:
            return m.group(1).strip().title()

    # Construir desde tecnología + ubicación
    # IMPORTANTE: solo generar nombre si hay ubicación — evitar "FV" o "Madrid" solos
    partes = []
    ubicacion = municipio or provincia
    if tech and ubicacion:
        tech_map = {
            "Fotovoltaica": "FV", "Eólica": "Parque Eólico",
            "BESS": "Almacenamiento BESS", "H2": "Planta H2",
            "LAT": "LAT", "SET": "Subestación",
            "Biomasa": "Planta Biomasa", "Data Center": "CPD",
            "FV+BESS": "FV+BESS", "Eólica+BESS": "Eólica+BESS",
        }
        partes.append(tech_map.get(tech, tech))
        partes.append(ubicacion.title())

    if partes:
        return " ".join(partes)

    # Fallback: extraer las primeras palabras relevantes del título
    titulo_limpio = re.sub(r'^(Resolución|Orden|Decreto|Anuncio|Extracto|Notificación)\s+(de\s+\d+\s+de\s+\w+\s+de\s+\d+,?\s+)?', '', titulo, flags=re.IGNORECASE)
    titulo_limpio = re.sub(r',.*$', '', titulo_limpio)
    palabras = titulo_limpio.strip()[:60]
    return palabras if len(palabras) > 10 else "Proyecto sin nombre"


class EnergyExtractor:
    def __init__(self, api_key: str = None):
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        # Haiku para coste mínimo; cambiar a claude-sonnet-4-6 para mayor precisión
        self.model = "claude-haiku-4-5-20251001"
        self.output_dir = Path("output")
        self.output_dir.mkdir(exist_ok=True)

    def _build_prompt(self, item: dict, enriquecimiento: bool = False) -> str:
        texto = item.get("texto", "")[:6000]
        boletin = item.get("boletin", "")
        ccaa = item.get("ccaa", "")
        titulo = item.get("titulo", "")

        # Detectar resolución paraguas (agrupa múltiples proyectos sin nombrarlos)
        es_paraguas = any(p in titulo.lower() for p in [
            "hace p\u00FAblico las resoluciones", "se hace p\u00FAblico",
            "relativas a autorizaci\u00F3n ambiental integrada",
            "emitidas por esta direcci\u00F3n general",
            "listado de resoluciones", "relaci\u00F3n de resoluciones",
        ])

        instruccion_especial = ""
        if es_paraguas:
            instruccion_especial = """
AVISO RESOLUCION PARAGUAS: Esta resolucion agrupa multiples expedientes.
- Si el texto lista proyectos individuales, extrae el primero o el mas relevante.
- Si no hay proyectos individuales: nombre_proyecto = "AAI Multiple [periodo]"
- tipo_permiso: "AAI", estado_permiso: "otorgado"
"""
        if enriquecimiento:
            instruccion_especial += """
SEGUNDA PASADA - ENRIQUECIMIENTO:
El modelo anterior no pudo extraer nombre_proyecto o datos clave.
- nombre_proyecto: construye uno con tecnologia + municipio/provincia. NUNCA null.
  Ejemplos: "Parque Fotovoltaico Casarrubios", "LAT 132kV Guadalajara Norte"
- promotor: busca S.A., S.L., S.A.U., S.L.U., nombre de empresa en el texto
- potencia_mw: busca MW, MWp, MWh, kW (convierte kW/1000 a MW)
- Si no hay texto disponible, construye el nombre desde el titulo y departamento
"""

        return f"""Extrae los datos del anuncio publicado en el {boletin} ({ccaa}).

SCHEMA DE SALIDA REQUERIDO:
{SCHEMA_CAMPOS}
{instruccion_especial}
TITULO: {titulo}
DEPARTAMENTO/ORGANISMO: {item.get('departamento', 'No disponible')}
EXPEDIENTE: {item.get('id', '')}
TEXTO COMPLETO:
{texto if texto else "[Texto no disponible - extrae lo posible del titulo y departamento]"}

RECUERDA:
- nombre_proyecto NUNCA debe ser null si conoces tecnologia y ubicacion. Construyelo.
- Tecnologias con mayuscula inicial: Fotovoltaica, Eolica, BESS, H2, LAT, SET...
- Si el texto menciona MW, MWp o kW, extrae potencia_mw siempre.

JSON:"""

    def extraer_item(self, item: dict) -> dict:
        prompt = self._build_prompt(item)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            raw = response.content[0].text.strip()
            # Limpiar markdown fences si las hay
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            datos = json.loads(raw.strip())

            # Garantizar campo es_proyecto_fallido
            estado = datos.get("estado_permiso", "")
            if "es_proyecto_fallido" not in datos:
                datos["es_proyecto_fallido"] = estado in ESTADOS_FALLIDOS

            # Garantizar campo permisos_adicionales
            if "permisos_adicionales" not in datos:
                datos["permisos_adicionales"] = []

            # Inferir capacidad liberada si no la puso el modelo pero tenemos potencia y estado negativo
            if (datos.get("capacidad_mw_liberada") is None and
                    estado in ESTADOS_LIBERAN and
                    datos.get("potencia_mw") is not None):
                datos["capacidad_mw_liberada"] = datos["potencia_mw"]

            # Tecnologías que corresponden a proyectos realmente energéticos
            TECHS_ENERGETICAS = {
                "Eólica","Fotovoltaica","BESS","H2","Data Center",
                "LAT","SET","Hidráulica","Termosolar","Biomasa","Biometano",
                "Cogeneración","FV+BESS","Eólica+BESS"
            }
            tecnologia = datos.get("tecnologia")
            confianza  = datos.get("confianza", 0)

            # Criterio principal: el LLM declara explícitamente que es energético
            llm_dice_energetico = datos.get("es_proyecto_energetico", None)

            if llm_dice_energetico is True:
                es_energetico = True
            elif llm_dice_energetico is False:
                es_energetico = False
            else:
                # Fallback para JSONs legacy sin el campo
                es_energetico = (
                    (tecnologia in TECHS_ENERGETICAS and confianza >= 0.5)
                )

            # ── Segunda llamada de enriquecimiento si faltan campos clave ──
            necesita_enriquecimiento = (
                es_energetico and (
                    datos.get("nombre_proyecto") is None or
                    (datos.get("promotor") is None and datos.get("potencia_mw") is None and
                     datos.get("confianza", 0) < 0.7)
                )
            )

            tokens_enriq = {"input": 0, "output": 0}
            if necesita_enriquecimiento:
                try:
                    prompt_enriq = self._build_prompt(item, enriquecimiento=True)
                    resp2 = self.client.messages.create(
                        model=self.model,
                        max_tokens=800,
                        system=SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt_enriq}]
                    )
                    raw2 = resp2.content[0].text.strip()
                    if "```" in raw2:
                        raw2 = raw2.split("```")[1]
                        if raw2.startswith("json"):
                            raw2 = raw2[4:]
                    datos2 = json.loads(raw2.strip())
                    tokens_enriq = {
                        "input": resp2.usage.input_tokens,
                        "output": resp2.usage.output_tokens
                    }
                    # Mezclar: solo actualizar campos que estaban vacíos
                    for campo in ["nombre_proyecto", "promotor", "potencia_mw",
                                  "subestacion_conexion", "municipio", "provincia",
                                  "tecnologia", "observaciones"]:
                        if datos.get(campo) is None and datos2.get(campo) is not None:
                            datos[campo] = datos2[campo]
                    # Actualizar confianza si mejoró
                    if datos2.get("confianza", 0) > datos.get("confianza", 0):
                        datos["confianza"] = datos2["confianza"]
                    logger.debug(f"Enriquecimiento {item['id']}: nombre={datos.get('nombre_proyecto')}")
                except Exception as e:
                    logger.debug(f"Enriquecimiento fallido {item['id']}: {e}")

            # ── Post-proceso: construir nombre desde título si sigue null ──
            if es_energetico and not datos.get("nombre_proyecto"):
                datos["nombre_proyecto"] = _nombre_desde_titulo(
                    item.get("titulo",""), datos
                )

            # ── Validación final del nombre: rechazar bare siglas y topónimos ──
            _NOMBRES_INVALIDOS = {
                "fv","h2","bess","eólica","eolica","solar","lat","set",
                "biomasa","biometano","biogás","biogas","hidráulica","hidraulica",
                "cogeneración","cogeneracion","termosolar","otro",
                # topónimos frecuentes como fallback name
                "madrid","barcelona","sevilla","bilbao","valencia","zaragoza",
                "málaga","malaga","murcia","palma","las palmas","oviedo",
                "santander","pamplona","logroño","logrono","vitoria","san sebastián",
                "burgos","valladolid","salamanca","segovia","ávila","avila",
                "soria","zamora","palencia","toledo","cuenca","guadalajara",
                "ciudad real","albacete","cáceres","caceres","badajoz",
                "huelva","cádiz","cadiz","córdoba","cordoba","jaén","jaen",
                "almería","almeria","granada","galicia","galende",
            }
            # Fragmentos conocidos de títulos burocrátcos mal extraídos
            _FRAGMENT_PATTERNS = [
                r"^de la delegaci[oó]n",
                r"^de la direcci[oó]n",
                r"^del servicio",
                r"^en concreto",
                r"^otorga a red",
                r"^se otorga",
                r"^se resuelve",
                r"^se autoriza",
                r"^autorizar",
                r"^conceder",
                r"^declarar",
                r"^la utilidad p[uú]blica",
                r"^en el t[eé]rmino",
                r"^trica a \d",
                r"^trativa de",
                r"^taci[oó]n ",
            ]
            nombre_actual = (datos.get("nombre_proyecto") or "").strip().lower()
            _es_invalido = (nombre_actual in _NOMBRES_INVALIDOS or
                any(re.search(p, nombre_actual) for p in _FRAGMENT_PATTERNS))
            if _es_invalido and es_energetico:
                logger.debug(f"Nombre inválido/fragmento: {datos.get('nombre_proyecto')!r} — reconstruyendo")
                nuevo = _nombre_desde_titulo(item.get("titulo",""), datos)
                if nuevo and nuevo != "Proyecto sin nombre":
                    datos["nombre_proyecto"] = nuevo
                else:
                    # Construir desde tecnologia + provincia si hay datos
                    _tec = datos.get("tecnologia","") or ""
                    _prov = datos.get("provincia","") or datos.get("comunidad_autonoma","") or ""
                    if _tec and _prov:
                        datos["nombre_proyecto"] = "{} {}".format(_tec, _prov.title())
                    else:
                        es_energetico = False
                        datos["nombre_proyecto"] = None

            return {
                "id": item["id"],
                "boletin": item["boletin"],
                "ccaa_boletin": item.get("ccaa", ""),
                "fecha_publicacion": item["fecha"],
                "titulo_original": item["titulo"],
                "url": item.get("url", ""),
                "datos": datos,
                "es_energetico": es_energetico,
                "tokens": {
                    "input": response.usage.input_tokens + tokens_enriq["input"],
                    "output": response.usage.output_tokens + tokens_enriq["output"]
                },
                "estado_validacion": "pendiente" if es_energetico else "descartado"
            }

        except json.JSONDecodeError as e:
            logger.warning(f"JSON error {item['id']}: {e}")
            return {"id": item["id"], "titulo_original": item["titulo"],
                    "datos": None, "error": str(e), "estado_validacion": "error"}
        except Exception as e:
            logger.error(f"API error {item['id']}: {e}")
            return {"id": item["id"], "titulo_original": item["titulo"],
                    "datos": None, "error": str(e), "estado_validacion": "error"}

    def procesar_batch(self, items: list, fecha: str) -> dict:
        resultados, tokens_in, tokens_out, errores = [], 0, 0, 0

        for i, item in enumerate(items):
            logger.info(f"[{i+1}/{len(items)}] {item['boletin']} — {item['titulo'][:70]}...")
            r = self.extraer_item(item)
            resultados.append(r)
            if "tokens" in r:
                tokens_in  += r["tokens"]["input"]
                tokens_out += r["tokens"]["output"]
            if r.get("estado_validacion") == "error":
                errores += 1

        coste = (tokens_in / 1e6) * 0.80 + (tokens_out / 1e6) * 4.0

        # Separar energéticos de descartados
        energeticos  = [r for r in resultados if r.get("es_energetico", True)]
        descartados  = [r for r in resultados if not r.get("es_energetico", True)]
        liberados    = [r for r in energeticos
                        if r.get("datos") and r["datos"].get("capacidad_mw_liberada")]
        mw_total_liberados = sum(r["datos"]["capacidad_mw_liberada"] for r in liberados)

        if descartados:
            logger.info(f"🗑  {len(descartados)} items descartados (no energéticos): "
                        + " | ".join(r["titulo_original"][:50] for r in descartados))

        output = {
            "fecha": fecha,
            "total": len(items),
            "energeticos": len(energeticos),
            "descartados": len(descartados),
            "exitosos": len(energeticos) - errores,
            "errores": errores,
            "tokens": {"input": tokens_in, "output": tokens_out},
            "coste_usd": round(coste, 5),
            "alertas_capacidad_liberada": len(liberados),
            "mw_totales_liberados": mw_total_liberados,
            "resultados": resultados
        }

        out_file = self.output_dir / f"energy_extraido_{fecha}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"✓ {len(items)-errores}/{len(items)} items extraídos")
        logger.info(f"⚡ {len(liberados)} alertas capacidad liberada — {mw_total_liberados:.1f} MW")
        logger.info(f"💰 Coste: ${coste:.5f} USD")

        return output

    def upgrade_to_sonnet(self):
        """Llama a esto cuando quieras más precisión (mayor coste)."""
        self.model = "claude-sonnet-4-6"
        logger.info("Modelo actualizado a Sonnet para mayor precisión")
