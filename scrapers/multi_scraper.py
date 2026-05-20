"""
Multi-Boletín Scraper v3 — BOE + CCAA
Boletines operativos:
  BOE   — API REST oficial datosabiertos (XML)
  BOCM  — XML directo por número de boletín
  BOCyL — HTML boletin.do?fechaBoletin=DD/MM/YYYY
  DOCM  — HTML cambiarBoletin.do?fecha=YYYYMMDD

Boletines adicionales implementados:
  BOJA — Andalucía (API REST)
  DOGV — C. Valenciana (XML por fecha)
  DOGC — Cataluña (HTML)
  DOG  — Galicia (HTML)
  BOPA — Asturias (HTML)
  BOC  — Cantabria (HTML)
  BORM — Murcia (HTML)
  (las resoluciones de CCAA con DIA desfavorable se publican también en BOE)
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json, time, logging, re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# ─── KEYWORDS Y FILTROS ───────────────────────────────────────────────────────
# Keywords de GENERACIÓN Y ALMACENAMIENTO ENERGÉTICO
# Solo incluyen términos que ÚNICAMENTE aparecen en proyectos de generación/almacenamiento
# Criterio: si aparece este término en el título, ES un proyecto energético relevante
KEYWORDS_ENERGIA = [
    # ── Generación fotovoltaica ──
    "fotovoltai",                    # fotovoltaico/a — muy específico
    "planta solar","parque solar",
    "parque fotovoltaico","planta fotovoltaica",
    "instalación fotovoltaica","instalacion fotovoltaica",
    "instalación solar fotovoltaica",
    "autoconsumo",                   # excl. "sin excedentes" → ver PATRONES_EXCLUIR
    # ── Generación eólica ──
    "eólico","eólica","eolico","eolica",
    "aerogenerador",
    "parque eólico","parque eolico",
    "instalación eólica","instalacion eolica",
    "repotenciaci",                  # repotenciación parque eólico
    # ── Almacenamiento energético ──
    "BESS",
    "sistema de almacenamiento de energía",
    "sistema de almacenamiento en bater",
    "almacenamiento de energía eléctrica mediante bater",
    "batería de almacenamiento",
    "baterías de almacenamiento",
    "planta de almacenamiento de energía",
    "almacenamiento energético",     # BOPV: "instalación de almacenamiento energético stand-alone"
    "stand-alone",                   # BOPV/BOE: proyectos BESS sin generación asociada
    "hibridaci",                     # hibridación FV+eólica+BESS
    # ── Hidrógeno verde ──
    "hidrógeno verde","hidrogeno verde",
    "electrolizador",
    "planta h2","proyecto h2",
    "h2 verde",
    # ── Biomasa/biometano/biogás ──
    "biometano",
    "biogás","biogas",
    "biomasa",
    "cogeneración","cogeneracion",
    "digestión anaeróbica",
    # ── Hidráulica ──
    "hidroeléctric","minicentral",
    "central hidroeléctrica",
    # ── Termosolar ──
    "termosolar","concentración solar",
    # ── Infraestructura de evacuación de proyectos renovables ──
    # Solo las líneas de evacuación, no las de distribución general
    "línea de evacuación","linea de evacuacion",
    "infraestructura de evacuación","infraestructura de evacuacion",
    # ── Data Centers ──
    "data center","centro de datos","CPD",
    # ── Nombres de proyectos con prefijo estándar ──
    "fv ",                           # FV [nombre] = proyecto fotovoltaico (solo al inicio del título)
    "psfv ",                         # PSFV = Planta Solar Fotovoltaica
    "pv ",                           # PV [nombre] = PhotoVoltaic project
    # ── Generación en general ──
    "instalación de generación","instalacion de generacion",
    "generación renovable",
    "instalación de producción de energía eléctrica",
    "producción de energía eléctrica renovable",
    # ── Modificaciones de evacuación de proyectos existentes ──
    "instalaciones comunes de evacuación","instalaciones comunes evacuación",
    # ── Grandes LAT/SET de evacuación ──
    "LMAT",                          # Línea Muy Alta Tensión = transporte
    " LAT ","(LAT)","LAT,","LAT.","LAT ","lat ",  # LAT genérica — requiere contexto energético
    "132 kv","132 kV","220 kv","220 kV","400 kv","400 kV",  # alta tensión transporte
    "línea subterránea de alta tensión","linea subterranea de alta tension",
    "línea subterránea alta tensión","linea subterranea alta tension",
    "línea aérea-subterránea d/c","linea aerea-subterranea d/c",
    "línea aérea subterránea 66 kv","línea aérea subterránea 132 kv",
]

DEPARTAMENTOS_ENERGIA = [
    "ministerio para la transición ecológica",
    "ministerio de industria",
    "secretaría de estado de energía",
    "dirección general de política energética",
    "dgpem",
    "consejería de industria",
    "consejería de energía",
    "consejería de transición ecológica",
    "consejería de medio ambiente",
    "agencia andaluza de la energía",
    "institut català d'energia","icaen",
    "agencia de la energía","ente regional de la energía",
    # País Vasco (BOPV) — "Departamento de Industria, Transición Energética y Sostenibilidad"
    "transición energética y sostenibilidad",
    # Extremadura (DOE) — consejería y DG
    "dirección general de industria, energía",            # DG dentro de la consejería
    "industria, energía, ciencia y territorio",           # Consejería DOE (passthrough Capa 2)
]

DEPARTAMENTOS_EXCLUIR = [
    "ministerio de defensa","ministerio de asuntos exteriores",
    "ministerio del interior","ministerio de justicia",
    "ministerio de hacienda","ministerio de cultura",
    "ministerio de sanidad","ministerio de educación",
    "ministerio de derechos sociales","ministerio de igualdad",
    "tribunal","consejo de estado","jefatura del estado",
    "congreso de los diputados","senado","banco de españa",
    "agencia estatal de administración tributaria",
    "dirección general de armamento","dirección general de la guardia civil",
    "dirección general de tráfico",
    "instituto nacional de técnica aeroespacial",
    "secretaría general técnica","secretaría general de coordinación territorial",
    "secretaría de estado de industria",
    # Consejerías autonómicas claramente no energéticas
    "consejería de hacienda",
    "consejería de educación",
    "consejería de sanidad",
    "consejería de cultura",
    "consejería de derechos sociales",
    "consejería de agricultura",
    "consejería de presidencia",
    "consejería de la presidencia",
    "consejería de justicia",
    "consejería de empleo",
    "consejería de familia",
    "consejería de administraciones públicas",
    "consejería de transformación digital",
    "consejería de fomento",
    # Organismos de emergencias/seguridad
    "agencia de seguridad y emergencias",
    "cuerpo de bomberos",
    "protección civil",
    # Transporte público (contratos de mantenimiento, no permisos energéticos)
    "metro de madrid",
    "emt madrid",
    "empresa municipal de transportes",
    "renfe",
    "adif",
    # Contratación pública genérica
    "dirección general de patrimonio y contratación",
    "dirección general de contratación",
]

PATRONES_EXCLUIR_TITULO = [
    # Personal universitario / académico — nunca energético aunque venga de dept de industria
    "se nombra profesor","se nombra profesora",
    "nombra catedrático","nombra catedrática",
    "concurso de acceso a plazas",       # oposiciones universitarias
    "acceso a plazas de profesor","acceso a plazas de catedrático",
    "plaza de profesor","plazas de profesor",
    # Convenios y acuerdos no energéticos
    "convenio con el ayuntamiento","convenio entre",
    "acuerdo de la comisión bilateral","presupuestos generales de la comunidad",
    "presupuestos generales del estado","puntos de atención al emprendedor",
    "cultura industrial","sistemas de arma","artículos pirotécnicos",
    "taller de pirotecnia","fábrica de explosivos","fábrica móvil de explosivos",
    "gente de mar","plataformas aéreas",
    # Actividades ganaderas/agrícolas con "autorización ambiental" pero no energéticas
    "explotación porcina","explotación bovina","explotación avícola",
    "explotación ganadera","explotación cunícola",
    "mejores técnicas disponibles",   # MTD — industria no energética
    "fábrica de metionina","fábrica de piensos","industria cárnica",
    # Urbanismo no energético
    "plan parcial del sector","plan parcial de ordenación",
    "actuación logística","actuación industrial",
    # Condecoraciones y personal
    "medalla al mérito","condecoración",
    # Montes y medio natural (no energéticos)
    "dirección general de medio natur",
    "montes. corrección","montes. resolución","montes. orden",
    "monte de utilidad pública","repoblación forestal",
    "aprovechamiento forestal","vías pecuarias",
    # Urbanismo genérico sin relación energética
    "plan general de ordenación urbana",
    "gerencia municipal de urbanismo",
    "estudio de detalle",
    # Agua y minería (no energéticos)
    "captación de aguas subterráneas","sondeo para la captación",
    "aprovechamiento de aguas","concesión de aguas",
    # Gas doméstico y redes de distribución menores (no renovables)
    "acometida de gas licuado de petróleo","acometida de glp",
    "instalación de gas para edificio","instalación de gas para vivienda",
    "instalación receptora de gas","red de distribución de gas natural",
    # Naves agrícolas, ganaderas e invernaderos
    "nave ganadera","nave agrícola","explotación de vacuno","explotación de ovino",
    "explotación de porcino","explotación de caprino","explotación avícola",
    "invernadero multitúnel","invernadero de","almacén agrícola",
    "rehabilitación de nave agrícola","construcción de nave ganadera",
    # Autoconsumo sin excedentes — no afecta capacidad RdT/RdD
    "autoconsumo sin excedentes",
    "instalación de autoconsumo sin excedentes",
    "ampliación de instalación fotovoltaica de autoconsumo sin excedentes",
    # Licencias urbanísticas menores sin componente energético
    "licencia de obras y calificación urbanística para la rehabilitación",
    "calificación urbanística para la construcción de nave",
    "calificación y licencia urbanística para la construcción de nave",
    # Urbanismo residencial y municipal
    "ampliación del núcleo urbano","delimitación del núcleo urbano",
    "normas urbanísticas municipales","normas subsidiarias municipales",
    "normas subsidiarias y plan especial","modificación normas subsidiarias",
    "plan de ordenación municipal","plan municipal de ordenación",
    "modificación puntual de las normas","modificación de las normas urbanísticas",
    "modificación puntual número","modificación puntual nº",
    "plan de actuación urbanística","unidades de actuación",
    "reparcelación","proyecto de urbanización",
    "sistema general de zona verde","zona verde","parque urbano",
    "viviendas protegidas","vivienda de protección oficial",
    "suelo urbano","uso residencial",
    # Infraestructuras aeronáuticas
    "helipuerto","aeródromo","aeropuerto","pista de aterrizaje",
    # Agua y saneamiento
    "abastecimiento de agua","abastecimiento y renovación de conducciones",
    "conducciones de agua","red de distribución de agua",
    "emisario","edar","estación depuradora de aguas residuales",
    "planta de tratamiento de aguas","depuradora","colector de aguas",
    "saneamiento","alcantarillado",
    "agua mineral natural","aguas subterráneas para consumo",
    "sondeo aqua","sondeo para agua","captación de agua para",
    # Líneas eléctricas de distribución LOCAL (no evacuación)
    # LAMT/LMT que alimentan instalaciones puntuales no son proyectos energéticos
    "cambio de conductor en lamt","cambio de conductor lmt",
    "cambio de conductor en lmt","sustitución de conductor en lamt",
    "alimentación a ct ","alimentación al ct ",
    "ct piscina","ct polideportivo","ct colegio","ct hospital",
    "centro de transformación municipal","centro de transformación local",
    # Equipamiento municipal no energético
    "escuela de equitación","campo de golf","instalación deportiva",
    "piscina municipal","polideportivo",
    # Contratos de suministro y servicios (no permisos energéticos)
    "suministro de reactivos","material fungible de laboratorio",
    "laboratorio regional","laboratorio de sanidad",
    "servicios de mantenimiento y desarrollo","contrato por procedimiento abierto",
    "formalización del contrato de suministros","formalización de contrato",
    "convocatoria del contrato","licitación del contrato",
    # Forestal y medio natural
    "plan dasocrático","monte de utilidad pública","monte catalogado",
    "aprovechamiento maderable","tratamiento selvícola",
    "codmont","cif ","monte número",
    # Minería no energética
    "concesión minera","concesión de explotación minera",
    "permiso de investigación minera","derechos mineros",
    "fr 1","fr 2","fr 3",   # referencia concesiones mineras
    # Urbanismo específico
    "plan especial de reforma interior","plan especial de mejora urbana",
    "desclasificación del polígono","suelo urbanizable programado",
    "ordenación detallada sobre","cigarrales","ordenanza municipal",
    # Infraestructuras de agua y asfálticas
    "renovación tubería","tubería avenida","tubería calle",
    "planta de aglomerado asfáltico","planta asfáltica","aglomerado asfáltico",
    "abastecimiento y renovación","red de distribución de agua potable",
    # Centros de transformación locales (distribución urbana)
    "nuevo ct en edificio","nuevo ct edificio","ct en edificio",
    "centro de transformación en edificio","ct urbano",
    # Canal de Isabel II y similares
    "canal de isabel ii","canal de isabel",
    # Vías pecuarias no energéticas
    "ocupación temporal vía pecuaria","ocupación de vía pecuaria",
    "ocupación en vía pecuaria","paso por vía pecuaria",
    # Dominio público marítimo-terrestre (litoral, no energético)
    "dominio público marítimo-terrestre","dominio maritimo terrestre",
    "servidumbre de protección costera","deslinde del dominio",
    # Correcciones de errores y disposiciones administrativas menores
    "corrección de errores","corrección de error",
    "fe de erratas","errata",
    # Órganos administrativos sin proyecto energético
    "del concejal delegado","del concejal de",
    "del alcalde del","del secretario del",
    # Propiedad industrial / intelectual (no energético)
    "propiedad industrial","propiedad intelectual","oficina española de patentes",
    "marcas y patentes","registro de la propiedad industrial",
    # Parques nacionales / naturales (ampliaciones de espacios protegidos)
    "parque nacional sierra de guadarrama","ampliación del parque nacional",
    "ampliación parque nacional","parque nacional de",
    # Investigación académica (no proyectos de planta real)
    "centro ibérico de investigación","centro de investigación en almacenamiento",
    "proyecto de investigación","programa de investigación","beca de investigación",
    # Planes de ordenación territorial / urbanismo
    "plan especial de protección del núcleo","plan especial de ordenación del núcleo",
    "plan especial de reforma interior","plan especial del núcleo rural",
    "calificación urbanística","licencia urbanística","licencia de obras",
    "plan regional ampliación polígono industrial","plan regional zamora",
    # Residuos no energéticos
    "gestión de residuos no peligrosos","vertedero de residuos no peligrosos",
    "planta de gestión de residuos","tratamiento de residuos sólidos",
    # "valorización de residuos" eliminado: biometano de residuos orgánicos SÍ es energético
    # Dragado / obra marítima no energética
    "dragado de mantenimiento","dragado del puerto","dragado en el puerto",
    # Ganadería / agricultura
    "explotación porcina","explotación vacuna","explotación cunícola",
    "fábrica de elaboración de productos lácteos","elaboración de productos lácteos",
    "transformación en regadío","captación de agua para riego",
    # Carreteras y caminos
    "mejora de carretera","acondicionamiento de carretera","ensanche de carretera",
    # Reciclaje de baterías (no es almacenamiento energético)
    "planta reciclado baterías","reciclado de baterías","reciclaje de baterías",
    "planta de reciclado de baterías","planta de tratamiento de baterías",
    # Mantenimiento de líneas existentes (no proyectos nuevos)
    "sustitución de apoyos",         # siempre es mantenimiento, nunca proyecto nuevo
    "sustitución apoyos",
    # Montes, catálogos forestales y bienes comunales
    "rectificación catálogo","catálogo de montes","catalogación monte",
    "catálogo de utilidad pública","monte catalogado",
    # Industria alimentaria / farmacéutica
    "producción de proteínas","planta de proteínas","planta de vacunas",
    "fábrica de vacunas","producción de vacunas",
    # Nombres de sólo localidad sin proyecto (detectados en capturas)
    # El filtro del dashboard cubre más, pero excluirlos en el scraper es más limpio
    # Textos truncados o solo lugar
    "información pública. resolución de",
    # Anuncios genéricos sin contenido energético específico
    "anuncio de la agencia andaluza de la energía, por el que se hace público",
    "por el que se hace público el listado",
    # Industria no energética
    "planta de fabricación de componentes","fabricación de componentes",
    "planta de hormigón","hormigonera","planta de áridos",
    "nave industrial y planta","nave industrial para",
    "almacén logístico","centro logístico","plataforma logística",
    "planta de reciclaje","planta de tratamiento de residuos",
    "explotación de cantera","extracción de áridos",
    # ERM (estaciones de regulación y medida de gas) locales pequeñas
    "sustitución erm","modificación erm","nueva erm",
    # Concesiones no energéticas del DOG/BOJA
    "concesión de aguas","aprovechamiento de aguas",
    "captación de aguas para riego","captación de aguas subterráneas para",
    # Sondeos de agua (no energéticos)
    "sondeo aquadomus","agua mineral natural","sondeo para captación",
    "sondeo de investigación de aguas","captación de aguas minerales",
    # Industria no energética adicional
    "planta de hormigón en seco","hormigón en seco","hormigón prefabricado",
    "fábrica de muebles","fábrica de piensos","industria cárnica",
    "matadero","slaughterhouse",
    # Rutas y caminos
    "camino rural","camino de concentración parcelaria",
    "acondicionamiento de camino","mejora de camino",
    # Telecomunicaciones (no energético)
    "antena de telecomunicaciones","torre de telecomunicaciones",
    "instalación de telefonía","fibra óptica",
    # Textos truncados típicos
    "de 10/04/","de 11/04/","de 12/04/","de 13/04/","de 14/04/",
    "de 15/04/","de 16/04/","de 17/04/","de 18/04/",
    # Infraestructura de distribución local (no proyectos de generación)
    # LMT/LMTA = Línea Media Tensión local — son mantenimiento de red, no proyectos
    "reglamentación lmta","reglamentación lmt",
    "lmt, ct, rbt","lmta lug","línea de distribución lmta",
    "línea media tensión subterránea, rbts",
    "plan básico municipal","plan de ordenación municipal",
    # IPA = Informe Previo de Ayuntamiento (urbanismo)
    # Excepciones: "parque eólico" o "fotovoltaica" en el título sí pasan
    
    # Excepciones: estas sí son energéticas aunque usen vía pecuaria
    # (se manejan en la lógica de keywords duros)
    
    # Agricultura y medio ambiente no energético
    "nitratos procedentes de fuentes agrarias","zonas vulnerables a la contaminación",
    "programa de actuación sobre las zonas vulnerables",
    "programa de vigilancia y control de aguas","masas de agua subterránea",
    "plan de gestión de residuos","residuos sólidos urbanos",
    "vía verde","sendero","camino natural",
    "espacio natural protegido","parque natural","reserva natural",
    "zona de especial protección","lugar de importancia comunitaria",
    # Infraestructuras no energéticas
    "abastecimiento de agua","saneamiento de aguas","depuradora de aguas",
    "planta de tratamiento de agua","estación depuradora",
    "red de saneamiento","red de abastecimiento",
    "carretera","autovía","autopista","variante de","circunvalación",
    "línea ferroviaria","infraestructura ferroviaria",
    # Contratos de mantenimiento de infraestructura no energética
    "anuncio periódico indicativo",   # BOCM — contratos de Metro, Transportes, etc.
    "contrato de arrendamiento",
    "contrato de suministro de bobinas",
    "contrato del servicio de reparación",
    "contrato de mantenimiento de los servidores",
    "contrato de servicios profesionales",
    "contrato de revisión overhaul",
    "contrato de renovación sistemas",
    "contrato del servicio de sustitución",
    "contrato de consultoría y asistencia técnica para labores",
    # Otros claramente no energéticos
    "servicios mínimos","concurso-oposición","proceso selectivo",
    "medalla al mérito","condecoración",
    # Industria farmacéutica y biotecnología no energética
    "fábrica de productos farmacéuticos","planta farmacéutica","laboratorio farmacéutico",
    "medicamentos veterinarios","productos fitosanitarios","laboratorios calier",
    "planta de fabricación de medicamentos","fabricación de fármacos",
    # Insectos / proteínas alternativas (no energético)
    "hermetia illucens","cría de insectos","producción de insectos",
    "granja de insectos","mosca soldado negra","proteínas de insecto",
    "cría de larvas","planta de larvas",
    # Gestión de residuos no energéticos
    "gestor de residuos no peligrosos","gestor de residuos peligrosos",
    "centro de tratamiento de residuos urbanos","centro de tratamiento de residuos",
    "complejo medioambiental de residuos","planta de clasificación de residuos",
    "punto limpio",
    # Infraestructuras portuarias no energéticas
    "muelle comercial","ampliación del muelle","ampliación de muelle",
    "terminal portuaria","terminal de contenedores","instalaciones portuarias",
    "dársena comercial","atraque comercial",
    # Fabricación de vehículos y automoción
    "fabricación de vehículos automóviles","fábrica de vehículos","planta de ensamblaje",
    "fabricación de autobuses","fabricación de camiones",
    "sector del automóvil","industria de automoción",
    # Líneas de baja tensión (distribución local, no evacuación)
    "línea subterránea de baja tensión","cable subterráneo de baja tensión",
    "red de baja tensión","instalación de baja tensión","línea de baja tensión",
    "lbt subterránea","red bt subterránea","canalización de baja tensión",
    # Planeamiento urbanístico regional sin contenido energético
    "plan regional de ámbito territorial","plan regional de ámbito sectorial",
    "modificación del plan regional de",
    # Redes de distribución eléctrica local (media/baja tensión hacia instalaciones puntuales)
    "alimentación al polígono industrial","alimentación a urbanización",
    "subterranización de línea de distribución",
    # Concentración parcelaria (siempre gestión agrícola/rural, nunca proyecto energético)
    "concentración parcelaria",
    "proyecto de concentración parcelaria",
    "declaración de impacto ambiental de la concentración parcelaria",
    # Regadío e infraestructura hídrica agrícola
    "ampliación de regadío","modernización del regadío","proyecto de regadío",
    "modificación de regadío","comunidad de regantes","zona regable",
    # Bases reguladoras y convocatorias de subvenciones energéticas (no son proyectos de planta)
    "bases reguladoras para la concesión de subvenciones",
    "bases reguladoras dirigidas a las subvenciones del programa",
    "bases reguladoras de las subvenciones para",
    "convocatoria de subvenciones para proyectos de energía",
    "redistribuyen los créditos presupuestarios",
    "redistribución de créditos presupuestarios",
    "habilitan créditos",        # BOPV — Decreto habilitación créditos presupuestarios
    "habilitación de créditos",
    "suplemento de crédito",
    "transferencia de créditos",
    "modificación de créditos presupuestarios",
    "generación de créditos",
    "se convocan para el año 20","incentivos para el año 20",
    "ayudas a proyectos de inversión en el marco del",  # subvenciones IDAE / auton.
    # Normas UNE y normativa técnica europea (BOE — DG Estrategia Industrial)
    "proyectos de normas europeas e internacionales","proyectos de norma une",
    "tramitados como proyectos de norma une","asociación española de normalización",
    # Industria alimentaria láctea/quesera
    "elaboración de queso","fábrica de queso",
    # Patrimonio forestal y usos privativos de montes (DG Patrimonio Natural)
    "dirección general de patrimonio natural y política forestal",
    "uso privativo del monte","uso privativo de monte",
    "ordenación del monte","plan dasocrático del monte",
    "aprovechamiento del monte","ocupación temporal del monte",
    # Consultas y audiencias públicas de normativa (no proyectos)
    "se somete a audiencia e información pública los proyectos de normas",
    "se somete a audiencia e información pública los anteproyectos",
    "sometido a consulta pública previa",
    # Concursos de capacidad de acceso (proceso administrativo, no planta)
    "concurso de capacidad de acceso",
    # ── Patrones específicos de nuevas CCAA ─────────────────────────────────
    # Aragón (BOA) — montes, caza, pesca, agricultura
    "aprovechamiento cinegético","coto de caza","plan de ordenación cinegética",
    "aprovechamiento piscícola","masa forestal","monte de utilidad pública",
    "cuota forestal","plan rector de uso y gestión",
    # País Vasco (BOPV) — administración local, cultura
    "plan territorial sectorial","plan de ordenación del territorio",
    "plan territorial parcial",
    "plan especial de ordenación urbana",
    "eusko jaurlaritza — decreto",
    # Extremadura (DOE) — agricultura, dehesa, fincas
    "concentración parcelaria",
    "transformación en regadío","proyecto de transformación en regadío",
    "zona de regadío","comunidad de regantes",
    "aprovechamiento de pastos","dehesa",
    "finca rústica","monte público",
    # Navarra (BON) — montes, caza, urbanismo
    "ordenación del territorio","plan urbanístico","plan municipal",
    "plan general municipal","actuación urbanística",
    # La Rioja (BOLR) — viñedo, agricultura, montes
    "viñedo","denominación de origen","sector vitivinícola",
    "aprovechamiento forestal de","monte de la rioja",
]

KEYWORDS_LOWER      = [k.lower() for k in KEYWORDS_ENERGIA]
DEPARTAMENTOS_LOWER = [d.lower() for d in DEPARTAMENTOS_ENERGIA]
EXCLUIR_LOWER       = [d.lower() for d in DEPARTAMENTOS_EXCLUIR]

# "pv " y "fv " sólo son válidos como sigla de proyecto (PV Solar X, FV Ribera)
# cuando NO están precedidos de letra (e.g. "bopv ", "cpv ", "dfv " → falso positivo)
_RE_PV_AISLADO = re.compile(r'(?<![a-záéíóúüñ])pv\s', re.I)
_RE_FV_AISLADO = re.compile(r'(?<![a-záéíóúüñ])fv\s', re.I)
KEYWORDS_DUROS      = [
    # Tecnologías renovables
    "fotovoltai","eólico","eolico","aerogenerador",
    "declaración de utilidad pública",
    "batería","almacenamiento energético","bess",
    "hidrógeno","hidrogeno","h2 ","h2,","(h2)","planta h2","electrolizador","biometano","biogás",
    "biomasa","termosolar","geotérmi",
    # Infraestructura eléctrica
    "subestación eléctrica","subestación transformadora",
    "línea de alta tensión","línea de media tensión",
    "lat ","set ","punto de acceso","punto de conexión a la red",
    "evacuación de energía","infraestructura de evacuación",
    # Gas renovable/hidrógeno
    "planta de hidrógeno","planta de biometano","planta de biogás",
    "instalación de producción de gas","almacenamiento de hidrógeno",
    # Data centers (gran consumo eléctrico)
    "centro de procesamiento de datos","data center","centro de datos",
    # Términos de tramitación energética específicos
    "autorización administrativa previa","autorización de construcción",
    "declaración de utilidad pública","servidumbre de paso",
    "hibridaci","autoconsumo con excedentes",
    # Instalación solar / eólica explícita
    "parque eólico","parque fotovoltaico","parque solar",
    "planta fotovoltaica","planta solar","instalación fotovoltaica",
    "instalación eólica","instalación de generación eléctrica",
]


def es_relevante(titulo: str, texto: str = "", departamento: str = "") -> bool:
    titulo_lower = titulo.lower()
    dept_lower   = departamento.lower()

    # Capa -1: patrones de título claramente no energéticos
    if any(p in titulo_lower for p in PATRONES_EXCLUIR_TITULO):
        return False

    # Capa 0: lista negra de departamentos
    if any(exc in dept_lower for exc in EXCLUIR_LOWER):
        haystack = (titulo + " " + texto[:200]).lower()
        if not any(k in haystack for k in KEYWORDS_DUROS):
            return False

    haystack = (titulo + " " + texto[:500]).lower()

    # Capa 1: keyword directo de generación/almacenamiento
    # Con los KEYWORDS_ENERGIA reescritos precisamente, casi no hacen falta excepciones
    matched_kw = [k for k in KEYWORDS_LOWER if k in haystack]
    if matched_kw:
        # "pv " y "fv " sólo son válidos si aparecen como sigla AISLADA,
        # no embebidos dentro de otra palabra (e.g. "bopv ", "bpv ", "dfv ").
        # Comprobación: el carácter anterior al match NO debe ser letra.
        _weak_siglas = {"pv ", "fv "}
        strong = [k for k in matched_kw if k not in _weak_siglas]
        weak   = [k for k in matched_kw if k in _weak_siglas]
        if not strong:
            valid_weak = []
            if "pv " in weak and _RE_PV_AISLADO.search(haystack):
                valid_weak.append("pv ")
            if "fv " in weak and _RE_FV_AISLADO.search(haystack):
                valid_weak.append("fv ")
            matched_kw = valid_weak  # descartar los embebidos

    if matched_kw:
        # LAT suelto (sin contexto renovable) → puede ser distribución industrial
        lat_terms = ["lat ", " lat ", "(lat)", "lat,", "lat."]
        if any(k in haystack for k in lat_terms):
            if not any(k in haystack for k in KEYWORDS_DUROS):
                if not any(p in haystack for p in ["red eléctrica", " ree ", "evacuación parque",
                                                     "evacuación planta", "evacuación fotovoltai",
                                                     "evacuación eólico", "lmat",
                                                     "400 kv", "220 kv", "132 kv",
                                                     "400kv", "220kv", "132kv",
                                                     "400 kV", "220 kV", "132 kV",
                                                     "doble circuito", "nueva lat"]):
                    return False
        return True


    # Capa 2: departamento energético conocido → pasa directamente
    # (restaurar comportamiento original: MITECO + departamentos energéticos pasan)
    if any(d in dept_lower for d in DEPARTAMENTOS_LOWER):
        # Excepción: títulos que definitivamente no son proyectos energéticos
        # aunque vengan de departamentos energéticos
        NO_PASAR_DEPT = [
            "propiedad industrial", "propiedad intelectual",
            "voluntariado ambiental en ríos", "sensibilización ambiental en ríos",
            "precio medio de la energía", "retribución del servicio de gestión",
            "demanda de interrumpibilidad",
            "vía izquierda", "túnel de padornelo", "corredor norte",
            "línea de alta velocidad madrid",
            "convenio con la plataforma tecnológica",
            # DOE Extremadura — Consejería de Industria, Energía, Ciencia y Territorio
            # publica subvenciones y extractos no energéticos
            "economía social",
            "turismo",
            "comercio interior",
            "artesanía",
            "consumo",
        ]
        if any(excl in titulo_lower for excl in NO_PASAR_DEPT):
            return False
        return True

    return False


# ─── BOE SCRAPER ─────────────────────────────────────────────────────────────
class BOEScraper:
    API_SUMARIO = "https://boe.es/datosabiertos/api/boe/sumario/{fecha}"
    API_TEXTO   = "https://www.boe.es/diario_boe/xml.php?id={item_id}"
    SECCIONES   = {"1","2","3","5"}

    def __init__(self, session):
        self.s = session
        # NO modificar la sesión compartida — pasar Accept en cada petición

    def get_items(self, fecha: str) -> list:
        url = self.API_SUMARIO.format(fecha=fecha)
        try:
            # Accept: application/xml en cada petición, no en la sesión global
            r = self.s.get(url, timeout=30, headers={"Accept": "application/xml"})
            r.raise_for_status()
            return self._parse(r.content, fecha)
        except Exception as e:
            logger.error(f"BOE {fecha}: {e}")
            return []

    def _parse(self, xml_bytes, fecha):
        items = []
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            logger.error(f"Parse XML BOE {fecha}: {e}")
            return []
        for sec in root.iter("seccion"):
            if sec.get("codigo","") not in self.SECCIONES:
                continue
            for dept in sec.iter("departamento"):
                dept_nombre = dept.get("nombre","").strip()
                for item in dept.iter("item"):
                    titulo  = (item.findtext("titulo") or "").strip()
                    if not titulo:
                        continue
                    if not es_relevante(titulo, departamento=dept_nombre):
                        continue
                    item_id  = (item.findtext("identificador") or "").strip()
                    url_html = (item.findtext("url_html") or "").strip()
                    url_pdf  = (item.findtext("url_pdf")  or "").strip()
                    url_xml  = (item.findtext("url_xml")  or "").strip()
                    items.append({
                        "boletin":"BOE","ccaa":"Nacional","id":item_id,
                        "fecha":fecha,"departamento":dept_nombre,"titulo":titulo,
                        "url":url_html,"url_pdf":url_pdf,"url_xml":url_xml,"texto":""
                    })
        return items

    def get_texto(self, item: dict) -> str:
        url_xml = item.get("url_xml","")
        if url_xml:
            try:
                r = self.s.get(url_xml, timeout=30)
                r.raise_for_status()
                root = ET.fromstring(r.content)
                partes = []
                for el in root.iter():
                    if el.tag in ("titulo","id","identificador"):
                        continue
                    if el.text and el.text.strip():
                        partes.append(el.text.strip())
                    if el.tail and el.tail.strip():
                        partes.append(el.tail.strip())
                texto = " ".join(filter(None, partes))
                if len(texto) > 200:
                    return texto[:8000]
            except Exception as e:
                logger.warning(f"XML texto {item.get('id')}: {e}")
        url_html = item.get("url","")
        if url_html:
            try:
                r = self.s.get(url_html, timeout=30)
                r.raise_for_status()
                soup = BeautifulSoup(r.text,"lxml")
                for sel in ["#textoxslt",".diari-content","article","main"]:
                    el = soup.select_one(sel)
                    if el:
                        return el.get_text(" ",strip=True)[:8000]
            except Exception as e:
                logger.warning(f"HTML texto {item.get('id')}: {e}")
        return ""


# ─── BOCM SCRAPER ────────────────────────────────────────────────────────────
class BOCMScraper:
    """
    BOCM — Estructura real confirmada:
    1. Portada del día: /boletin/bocm-YYYYMMDD-NNN (NNN = número del boletín)
       El número se extrae del HTML de la portada.
    2. Cada sección tiene su URL:
       /boletin-completo/bocm-YYYYMMDD/NNN/seccion-url-encoded/consejeria-url-encoded
    3. Estrategia: solo descargar secciones de consejerías energéticas relevantes
       para minimizar peticiones y falsos positivos.
    """
    BASE = "https://www.bocm.es"

    # Secciones con actividad energética en BOCM
    # Formato: slug URL-encoded que aparece en los links de la portada
    SECCIONES_ENERGIA = [
        "consejer%C3%ADa-de-econom%C3%ADa%2C-hacienda-y-empleo",
        "consejer%C3%ADa-de-medio-ambiente%2C-agricultura--e-interior",
        "consejer%C3%ADa-de-vivienda%2C-transportes--e-infraestructuras",
    ]

    def __init__(self, session):
        self.s = session

    def get_items(self, fecha: str) -> list:
        dt  = datetime.strptime(fecha, "%Y%m%d")
        num = self._get_num_boletin(dt, fecha)
        if not num:
            logger.warning(f"BOCM {fecha}: no se encontró número de boletín")
            return []

        logger.info(f"  BOCM nº {num} — {fecha}")
        items = []

        # Descargar solo las secciones energéticas relevantes
        # Secciones: b)=autoridades, c)=otras disposiciones, d)=anuncios
        secciones_tipo = [
            "c%29-otras-disposiciones",
            "d%29-anuncios",
        ]

        for tipo in secciones_tipo:
            for consejeria in self.SECCIONES_ENERGIA:
                url = (f"{self.BASE}/boletin-completo/bocm-{fecha}/{num}/"
                       f"i.-comunidad-de-madrid/{tipo}/{consejeria}")
                try:
                    r = self.s.get(url, timeout=20)
                    if r.status_code != 200:
                        continue
                    nuevos = self._parse_seccion(r.text, fecha, url)
                    items.extend(nuevos)
                    time.sleep(0.3)
                except Exception as e:
                    logger.warning(f"BOCM sección {url[-50:]}: {e}")

        return items

    def _get_num_boletin(self, dt, fecha: str) -> int:
        """
        Obtiene el número de boletín probando URLs de sección directamente.
        El BOCM publica ~250 boletines/año. Estimamos el número como
        día_del_año * 0.83 y probamos en un rango de ±15.
        """
        dia_anyo   = dt.timetuple().tm_yday
        estimacion = int(dia_anyo * 0.83)
        # URL de sección rápida para verificar (sección siempre presente)
        url_test = (f"{self.BASE}/boletin-completo/bocm-{fecha}/{{num}}/"
                    f"i.-comunidad-de-madrid/b%29-autoridades-y-personal/"
                    f"consejer%C3%ADa-de-presidencia%2C-justicia--y-administraci%C3%B3n-local")

        # Probar desde estimacion-10 hasta estimacion+10
        for delta in [0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5,
                      -6, 6, -7, 7, -8, 8, -9, 9, -10, 10]:
            num = estimacion + delta
            if num < 1:
                continue
            try:
                r = self.s.get(url_test.format(num=num), timeout=8)
                if r.status_code == 200 and "BOCM" in r.text:
                    logger.info(f"  BOCM número encontrado: {num} (delta={delta:+d})")
                    return num
            except Exception:
                pass
            time.sleep(0.2)

        # Si no encontramos por sección, intentar URL del boletín completo
        for num in range(max(1, estimacion-15), estimacion+15):
            try:
                r = self.s.get(f"{self.BASE}/boletin/bocm-{fecha}-{num}",
                               timeout=8)
                if r.status_code == 200 and "BOCM" in r.text:
                    return num
            except Exception:
                pass

        logger.warning(f"BOCM {fecha}: número de boletín no encontrado")
        return 0

    def _parse_seccion(self, html: str, fecha: str, url_seccion: str) -> list:
        """
        Parsea una sección del BOCM usando selectores CSS precisos.
        Estructura HTML real confirmada:
          div.view-content > div.view-grouping
            h4 = Consejería
            div.views-row
              div.sub-organismo = Suborganismo (puede vacío)
              article[about="/bocm-FECHA-NUM"]
                div.field-name-field-order-number = número orden
                div.field-name-field-short-description > p
                  "TipoActo<br/>– Título completo"
                a[href*=".PDF"] = PDF
                a[href^="/bocm-"] = HTML
                a[href*=".xml"] = XML
        """
        soup  = BeautifulSoup(html, "lxml")
        items = []

        view = soup.find("div", class_="view-content")
        if not view:
            return []

        for grouping in view.find_all("div", class_="view-grouping"):
            # Consejería principal del grupo
            h4 = grouping.find("h4")
            consejeria = h4.get_text(strip=True) if h4 else ""

            for row in grouping.find_all("div", class_="views-row"):
                # Suborganismo (p.ej. "Agencia de Seguridad y Emergencias")
                sub_el = row.find("div", class_="sub-organismo")
                suborganismo = sub_el.get_text(strip=True) if sub_el else ""

                article = row.find("article")
                if not article:
                    continue

                # ID desde atributo about: "/bocm-20260428-52" -> "52"
                about = article.get("about", "")
                m_num = re.search(r"-(\d+)$", about)
                num_orden = m_num.group(1) if m_num else str(len(items))

                # Título desde field-short-description
                desc = article.find("div", class_=re.compile(
                    r"field-name-field-short-description"))
                if not desc:
                    continue
                p = desc.find("p")
                if not p:
                    continue

                # Separar tipo de acto del título real usando el <br/>
                tipo_acto = ""
                titulo = ""
                partes_br = []
                for child in p.children:
                    if hasattr(child, "name") and child.name == "br":
                        partes_br.append(None)  # marcador de salto
                    else:
                        txt = str(child).strip()
                        if txt:
                            partes_br.append(txt)

                if None in partes_br:
                    idx_br = partes_br.index(None)
                    tipo_acto = " ".join(str(x) for x in partes_br[:idx_br]).strip()
                    resto = " ".join(str(x) for x in partes_br[idx_br+1:] if x).strip()
                    # Quitar guión largo inicial
                    titulo = re.sub(r"^[–—\-]\s*", "", resto).strip()
                else:
                    titulo = p.get_text(strip=True)

                if not titulo or len(titulo) < 20:
                    continue

                # Filtro: lista negra por suborganismo primero
                dept_check = suborganismo if suborganismo else consejeria
                dept_lower = dept_check.lower()
                if any(exc in dept_lower for exc in EXCLUIR_LOWER):
                    continue

                # Filtro energético con título limpio
                if not es_relevante(titulo, departamento=consejeria):
                    continue

                # URLs de descarga
                url_pdf  = next((a["href"] for a in article.find_all("a", href=True)
                                 if ".pdf" in a["href"].lower() or ".PDF" in a["href"]), "")
                url_html = next((a["href"] for a in article.find_all("a", href=True)
                                 if a["href"].startswith("/bocm-")), "")
                url_xml  = next((a["href"] for a in article.find_all("a", href=True)
                                 if ".xml" in a["href"].lower()), "")

                if url_pdf and not url_pdf.startswith("http"):
                    url_pdf = f"https://www.bocm.es{url_pdf}"
                if url_html:
                    url_html = f"https://www.bocm.es{url_html}"
                if url_xml and not url_xml.startswith("http"):
                    url_xml = f"https://www.bocm.es{url_xml}"

                items.append({
                    "boletin": "BOCM",
                    "ccaa": "Madrid",
                    "id": f"BOCM-{fecha}-{num_orden}",
                    "fecha": fecha,
                    "departamento": consejeria,
                    "suborganismo": suborganismo,
                    "titulo": titulo,
                    "url": url_html,
                    "url_pdf": url_pdf,
                    "url_xml": url_xml,
                    "texto": ""
                })

        return items


    def get_texto(self, item: dict) -> str:
        """
        Descarga el texto del item BOCM.
        Prioriza XML (limpio) sobre HTML.
        URL XML: https://www.bocm.es/boletin/CM_Orden_BOCM/YYYY/MM/DD/BOCM-YYYYMMDD-NN.xml
        """
        # Intentar XML primero
        url_xml = item.get("url_xml", "")
        if url_xml:
            try:
                r = self.s.get(url_xml, timeout=20)
                if r.status_code == 200 and r.text.strip().startswith("<"):
                    root = ET.fromstring(r.content)
                    partes = []
                    for el in root.iter():
                        if el.text and el.text.strip():
                            partes.append(el.text.strip())
                        if el.tail and el.tail.strip():
                            partes.append(el.tail.strip())
                    texto = " ".join(filter(None, partes))
                    if len(texto) > 100:
                        return texto[:8000]
            except Exception as e:
                logger.warning(f"BOCM XML {item.get('id')}: {e}")

        # Fallback HTML
        url = item.get("url", "")
        if url:
            try:
                r = self.s.get(url, timeout=20)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "lxml")
                    for sel in [".field-name-body", ".node-content",
                                ".field-items", "article"]:
                        el = soup.select_one(sel)
                        if el:
                            return el.get_text(" ", strip=True)[:8000]
            except Exception as e:
                logger.warning(f"BOCM HTML {item.get('id')}: {e}")
        return ""


# ─── BOCyL SCRAPER ───────────────────────────────────────────────────────────
class BOCyLScraper:
    """
    BOCyL: HTML en boletin.do?fechaBoletin=DD/MM/YYYY
    Estructura real confirmada:
      <div id="resultados">
        <h3> Sección principal
        <h4> Subsección
        <h5> Consejería/Organismo
        <p>  Título de la disposición
        <ul class="descargaBoletin"> <li><a href="...pdf"> PDF
    """
    BASE = "https://bocyl.jcyl.es"

    def __init__(self, session):
        self.s = session

    def get_items(self, fecha: str) -> list:
        dt  = datetime.strptime(fecha, "%Y%m%d")
        url = f"{self.BASE}/boletin.do?fechaBoletin={dt.day:02d}/{dt.month:02d}/{dt.year}"
        try:
            r = self.s.get(url, timeout=30)
            r.raise_for_status()
            return self._parse(r.text, fecha)
        except Exception as e:
            logger.error(f"BOCyL {fecha}: {e}")
            return []

    def get_texto(self, item: dict) -> str:
        """
        Descarga el texto completo de la disposición BOCyL.
        Estrategia: HTML primero, PDF como fallback si HTML da poco texto.
        """
        texto_html = self._get_texto_html(item)
        if len(texto_html) > 500:
            return texto_html

        # Fallback: intentar PDF si el HTML no tiene suficiente contenido
        url_pdf = item.get("url_pdf", "")
        if url_pdf:
            texto_pdf = self._get_texto_pdf(url_pdf, item.get("id",""))
            if len(texto_pdf) > len(texto_html):
                return texto_pdf

        return texto_html

    def _get_texto_html(self, item: dict) -> str:
        """Descarga texto desde el HTML de la disposición."""
        url = item.get("url", "")
        if not url:
            return ""
        try:
            r = self.s.get(url, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            for sel in ["#contenido", ".disposicion", "article", "main", "#textoxslt"]:
                el = soup.select_one(sel)
                if el:
                    return el.get_text(" ", strip=True)[:8000]
            return soup.get_text(" ", strip=True)[:8000]
        except Exception as e:
            logger.warning(f"BOCyL HTML {item.get('id')}: {e}")
            return ""

    def _get_texto_pdf(self, url_pdf: str, item_id: str = "") -> str:
        """Extrae texto del PDF de la disposición usando pdfplumber."""
        try:
            import pdfplumber
            import io as _io
            r = self.s.get(url_pdf, timeout=30)
            r.raise_for_status()
            if b"%PDF" not in r.content[:10]:
                return ""
            pdf = pdfplumber.open(_io.BytesIO(r.content))
            texto = ""
            for page in pdf.pages[:6]:  # máximo 6 páginas
                t = page.extract_text()
                if t:
                    texto += t + "\n"
                if len(texto) > 8000:
                    break
            pdf.close()
            return texto[:8000]
        except ImportError:
            logger.debug("pdfplumber no instalado — instala con: pip install pdfplumber")
            return ""
        except Exception as e:
            logger.warning(f"BOCyL PDF {item_id}: {e}")
            return ""

    def _parse(self, html: str, fecha: str) -> list:
        soup  = BeautifulSoup(html, "lxml")
        div   = soup.find("div", id="resultados")
        if not div:
            return []

        items       = []
        organismo   = ""
        seccion     = ""

        for el in div.children:
            if not hasattr(el, "name") or not el.name:
                continue
            tag = el.name.lower()

            if tag in ("h3","h4"):
                seccion = el.get_text(strip=True)
            elif tag == "h5":
                organismo = el.get_text(strip=True)
            elif tag == "p":
                titulo = el.get_text(strip=True)
                if not titulo or not es_relevante(titulo, departamento=organismo):
                    continue
                # Buscar el PDF en el siguiente <ul class="descargaBoletin">
                ul = el.find_next_sibling("ul", class_="descargaBoletin")
                url_pdf = ""
                url_html_item = ""
                if ul:
                    for a in ul.find_all("a", href=True):
                        href = a["href"]
                        if href.endswith(".pdf"):
                            url_pdf = href if href.startswith("http") else f"{self.BASE}/{href}"
                        elif ".do" in href or "html" in href.lower():
                            url_html_item = href if href.startswith("http") else f"{self.BASE}/{href}"

                item_id = re.search(r"BOCYL-D-[\d-]+-\d+", url_pdf)
                item_id = item_id.group(0) if item_id else f"BOCyL-{fecha}-{len(items)}"

                items.append({
                    "boletin":"BOCyL","ccaa":"Castilla y León","id":item_id,
                    "fecha":fecha,"departamento":organismo,"titulo":titulo,
                    "url":url_html_item,"url_pdf":url_pdf,"url_xml":"","texto":""
                })
        return items


# ─── DOCM SCRAPER ────────────────────────────────────────────────────────────
class DOCMScraper:
    """
    DOCM (Castilla-La Mancha): HTML en cambiarBoletin.do?fecha=YYYYMMDD
    Los items están como <a href="./detalleDocumento.do?idDisposicion=NNN">Ver detalle</a>
    El título está en el texto anterior al link, dentro de la celda de tabla.
    """
    BASE = "https://docm.jccm.es"

    def __init__(self, session):
        self.s = session

    def get_items(self, fecha: str) -> list:
        url = f"{self.BASE}/docm/cambiarBoletin.do?fecha={fecha}"
        try:
            r = self.s.get(url, timeout=30)
            r.raise_for_status()
            return self._parse(r.text, fecha)
        except Exception as e:
            logger.error(f"DOCM {fecha}: {e}")
            return []

    def get_texto(self, item: dict) -> str:
        """
        Intenta obtener texto del DOCM.
        - descargarArchivo.do devuelve error del servidor
        - Intentamos el HTML de detalleDocumento.do con headers de navegador
        """
        url = item.get("url", "")
        if not url:
            return ""
        try:
            # Intentar con headers completos de navegador
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-ES,es;q=0.9",
                "Referer": "https://docm.jccm.es/docm/",
            }
            r = self.s.get(url, timeout=20, headers=headers)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")
            # Buscar el contenido principal evitando menús y cabeceras
            for sel in [".contenido-disposicion", "#contenido", ".texto-disposicion",
                        "article", ".field-items", "div.node-content"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 200:
                        return t[:8000]
            # Si no hay selector específico, extraer párrafos largos
            parrafos = [p.get_text(" ", strip=True) for p in soup.find_all("p")
                       if len(p.get_text(strip=True)) > 100]
            if parrafos:
                return " ".join(parrafos)[:8000]
        except Exception as e:
            logger.debug(f"DOCM texto {item.get('id')}: {e}")
        return ""

    def _parse(self, html: str, fecha: str) -> list:
        """
        Estructura real del DOCM confirmada:
        - Las consejerías aparecen como texto en celdas/divs
        - Cada disposición tiene su consejería en el texto ANTERIOR al link
        - Los links son: ./detalleDocumento.do?idDisposicion=NNN
        - El título está en el mismo bloque de texto que el link
        Estrategia: para cada link, buscar la consejería más cercana hacia arriba
        """
        soup  = BeautifulSoup(html, "lxml")
        items = []

        # Construir mapa de todas las consejerías con su posición en el árbol
        # para asignar la consejería correcta a cada disposición
        all_links = soup.find_all("a", href=re.compile(r"detalleDocumento\.do"))

        for a in all_links:
            href = a.get("href","")
            if not href:
                continue

            # Extraer título: buscar el texto del bloque contenedor
            # subiendo hasta encontrar texto sustancial distinto de "Ver detalle"
            titulo = ""
            consejeria_local = ""

            # Buscar hacia arriba en el DOM
            node = a
            for _ in range(6):  # máximo 6 niveles arriba
                node = node.parent
                if node is None:
                    break
                texto = node.get_text(" ", strip=True)
                texto_limpio = re.sub(r'Ver detalle', '', texto)
                texto_limpio = re.sub(r'\d{4,6}\s*KB', '', texto_limpio)
                texto_limpio = re.sub(r'\[\s*\]', '', texto_limpio)
                texto_limpio = re.sub(r'\s+', ' ', texto_limpio).strip()

                if len(texto_limpio) > 60 and not titulo:
                    titulo = texto_limpio[:300]

                # Buscar consejería en el mismo bloque
                m_con = re.search(
                    r'Consejería de [A-ZÁÉÍÓÚÑ][^.\n]{5,80}',
                    texto_limpio
                )
                if m_con and not consejeria_local:
                    consejeria_local = m_con.group(0).strip()

                if titulo and consejeria_local:
                    break

            # Si no encontramos consejería en el bloque, buscar hacia atrás
            # en el HTML por el texto de consejería más próximo anterior
            if not consejeria_local:
                prev = a
                for _ in range(20):
                    prev = prev.find_previous(
                        lambda t: t.name and t.get_text(strip=True).startswith("Consejería")
                                  and len(t.get_text(strip=True)) < 120
                    )
                    if prev:
                        consejeria_local = prev.get_text(strip=True)
                        break

            if not titulo:
                continue

            # Aplicar filtro energético con la consejería local correcta
            if not es_relevante(titulo, departamento=consejeria_local):
                continue

            url_detalle = f"{self.BASE}/docm/{href.lstrip('./')}"
            m = re.search(r"idDisposicion=(\d+)", href)
            item_id = f"DOCM-{m.group(1)}" if m else f"DOCM-{fecha}-{len(items)}"

            items.append({
                "boletin":"DOCM","ccaa":"Castilla-La Mancha","id":item_id,
                "fecha":fecha,"departamento":consejeria_local,"titulo":titulo,
                "url":url_detalle,"url_pdf":"","url_xml":"","texto":""
            })

        return items



# ─── BOJA SCRAPER (Andalucía) ────────────────────────────────────────────────
class BOJAScraper:
    """
    BOJA — Boletín Oficial de la Junta de Andalucía
    API: contentapi/boja/calendario → número de boletín → HTML de secciones.
    No requiere Playwright.
    """
    BASE        = "https://www.juntadeandalucia.es"
    API_CAL     = ("https://www.juntadeandalucia.es/ssdigitales/datasets/"
                   "contentapi/boja/calendario?fechaDesde={f}&fechaHasta={f}")
    # Formato fecha confirmado: DD-MM-YYYY (ej: 24-04-2026)
    API_SECS    = ("https://www.juntadeandalucia.es/ssdigitales/datasets/"
                   "contentapi/boja/secciones/{num}")
    EBOJA_INDEX = "https://www.juntadeandalucia.es{enlace}"  # /eboja/YYYY/NUM/c01/index.html

    # Secciones del BOJA relevantes para energía
    SECCIONES_OK = {"1", "2", "3", "5"}  # 1=disposiciones, 2=autoridades, 3=otras, 5=anuncios

    def __init__(self, session):
        self.s = session
        self.s.headers.update({
            "Referer": "https://www.juntadeandalucia.es/eboja.html",
            "Accept":  "application/json, text/html, */*",
        })

    def get_items(self, fecha: str) -> list:
        dt = datetime.strptime(fecha, "%Y%m%d")
        fecha_api = f"{dt.day:02d}-{dt.month:02d}-{dt.year}"  # DD-MM-YYYY confirmado

        # 1. Obtener metadatos del boletín del día
        # La API alterna entre JSON y XML según versión/caché — intentar JSON primero
        try:
            r = self.s.get(self.API_CAL.format(f=fecha_api), timeout=15)
            if r.status_code != 200:
                logger.debug(f"BOJA {fecha}: sin boletín ({r.status_code})")
                return []

            boletines = []
            # Intentar JSON primero (formato habitual)
            try:
                data = r.json()
                resultado_raw = data.get("resultado", [])
                if resultado_raw:
                    for b in resultado_raw[0].get("boja", []):
                        enlace = b.get("enlace", "")
                        bnum   = str(b.get("bojaNumber", "")) or None
                        if enlace:
                            boletines.append({"enlace": enlace, "boja_num": bnum})
            except Exception:
                # Fallback XML: <jsonObject><resultado><enlace>…</enlace><boja><bojaNumber>N</bojaNumber>…
                xml_soup = BeautifulSoup(r.text, "lxml-xml")
                for res in xml_soup.find_all("resultado"):
                    enlace_tag   = res.find("enlace")
                    boja_num_tag = res.find("bojaNumber")
                    if enlace_tag:
                        boletines.append({
                            "enlace":   enlace_tag.get_text(strip=True),
                            "boja_num": boja_num_tag.get_text(strip=True) if boja_num_tag else None,
                        })

            if not boletines:
                logger.debug(f"BOJA {fecha}: sin boletines en la respuesta")
                return []

        except Exception as e:
            logger.warning(f"BOJA calendario: {e}")
            return []

        items = []
        for boletin_meta in boletines:
            enlace_index = boletin_meta["enlace"]   # /eboja/20260518.html ó /eboja/2026/78/index.html
            boja_num_xml = boletin_meta.get("boja_num")
            if not enlace_index:
                continue

            # 2. Descargar el índice del boletín
            url_index = self.BASE + enlace_index
            try:
                r2 = self.s.get(url_index, timeout=20)
                if r2.status_code != 200:
                    continue
            except Exception as e:
                logger.warning(f"BOJA index: {e}")
                continue

            # 3. Determinar boja_num y base_sec
            # Nuevo formato: /eboja/YYYYMMDD.html  → boja_num del XML
            # Viejo formato: /eboja/2026/78/index.html → extraer del path
            m_old = re.search(r'/eboja/(\d{4})/(\d+)/index\.html', enlace_index)
            if m_old:
                boja_num = m_old.group(2)
                base_sec = f"{self.BASE}/boja/{m_old.group(1)}/{boja_num}/"
            elif boja_num_xml:
                boja_num = boja_num_xml
                base_sec = f"{self.BASE}/boja/{dt.year}/{boja_num}/"
            else:
                logger.warning(f"BOJA: no se pudo determinar boja_num para {enlace_index}")
                continue

            soup2 = BeautifulSoup(r2.text, "lxml")
            columna = soup2.find("div", id="columna") or soup2

            # Obtener links de secciones (hrefs como "s54", "s51", etc.)
            secciones_links = []
            for a in columna.find_all("a", href=True):
                href = a.get("href", "")
                if re.match(r'^s\d+$', href):
                    secciones_links.append(href)

            logger.debug(f"BOJA {boja_num}: secciones {secciones_links}")

            # 4. Descargar cada sección y extraer items
            for sec in secciones_links:
                url_sec = base_sec + sec
                try:
                    r3 = self.s.get(url_sec, timeout=20)
                    if r3.status_code == 200:
                        nuevos = self._parse_seccion(r3.text, fecha, base_sec)
                        items.extend(nuevos)
                        if nuevos:
                            logger.debug(f"BOJA sección {sec}: {len(nuevos)} items")
                    time.sleep(0.2)
                except Exception as e:
                    logger.debug(f"BOJA {url_sec}: {e}")

        return items

    def _parse_seccion(self, html: str, fecha: str, base_sec: str) -> list:
        """
        Parsea una página de sección del BOJA (ej: /boja/2026/78/s54).
        Estructura confirmada:
          - div.grid_11.boja_sumario: contenedor real
          - div.item.punteado_izquierda: disposiciones
          - Consejería: texto previo a cada grupo de items
        """
        soup  = BeautifulSoup(html, "lxml")
        items = []

        # Buscar todos los items de disposición directamente
        divs_item = soup.find_all("div", class_=lambda c: c and
                                  "item" in c and "punteado_izquierda" in c)

        for div in divs_item:
            # Título: primer <p> del div
            p = div.find("p")
            titulo = (p.get_text(" ", strip=True) if p
                     else div.get_text(" ", strip=True))
            titulo = titulo.strip()
            if not titulo or len(titulo) < 20:
                continue

            # Departamento: buscar hacia atrás el hermano previo que sea consejería
            dept = ""
            for sib in div.find_previous_siblings():
                sib_txt = sib.get_text(strip=True) if hasattr(sib, "get_text") else ""
                if not sib_txt:
                    continue
                if any(w in sib_txt for w in [
                    "Consejería","Agencia","Secretaría","Dirección General",
                    "Presidencia","Junta de Andalucía","Instituto","Servicio Andaluz"
                ]) and len(sib_txt) < 200:
                    dept = sib_txt
                    break
                # Si es otro item, parar la búsqueda
                sib_cls = " ".join(sib.get("class", []) if hasattr(sib, "get") else [])
                if "item" in sib_cls and "punteado" in sib_cls:
                    break

            # Enlace HTML: a con "Otros formatos" o class item_html
            url = ""
            for a in div.find_all("a", href=True):
                txt_a = a.get_text(strip=True).lower()
                cls_a = " ".join(a.get("class", []))
                if "otros formatos" in txt_a or "item_html" in cls_a:
                    href = a["href"]
                    url = href if href.startswith("http") else self.BASE + "/" + href.lstrip("/")
                    break

            # Enlace PDF: a con "Descargar PDF" o class item_pdf
            url_pdf = ""
            for a in div.find_all("a", href=True):
                txt_a = a.get_text(strip=True).lower()
                cls_a = " ".join(a.get("class", []))
                if "descargar pdf" in txt_a or "item_pdf" in cls_a:
                    href = a["href"]
                    url_pdf = (href if href.startswith("http")
                               else base_sec + href.lstrip("/"))
                    break

            if es_relevante(titulo, departamento=dept):
                items.append({
                    "boletin": "BOJA", "ccaa": "Andalucía",
                    "id": f"BOJA-{fecha}-{len(items)}",
                    "fecha": fecha, "departamento": dept,
                    "titulo": titulo[:300],
                    "url": url, "url_pdf": url_pdf,
                    "url_xml": "", "texto": ""
                })

        return items

    def _parse_sumario(self, html: str, fecha: str, url_base: str) -> list:
        """Alias por compatibilidad."""
        return self._parse_seccion(html, fecha, url_base)

    def _parse_secciones_meta(self, secciones, fecha, boja_num, enlace_base) -> list:
        """Parsea las secciones de la metadata del API como fallback."""
        items = []
        base_dir = enlace_base.rsplit("/", 1)[0] if enlace_base else ""
        for sec in secciones:
            titulo_sec = sec.get("titulo","")
            enlace_sec = sec.get("enlace","")
            if not enlace_sec:
                continue
            try:
                url_sec = self.BASE + enlace_sec
                r = self.s.get(url_sec, timeout=15)
                if r.status_code == 200:
                    nuevos = self._parse_sumario(r.text, fecha, boja_num)
                    items.extend(nuevos)
                    time.sleep(0.3)
            except Exception as e:
                logger.debug(f"BOJA sección {enlace_sec}: {e}")
        return items

    def get_texto(self, item: dict) -> str:
        url = item.get("url","")
        if not url:
            return ""
        try:
            r = self.s.get(url, timeout=20)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")
            for sel in [".contenido-disposicion","#contenido",".texto","article","main"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 200:
                        return t[:8000]
            return soup.get_text(" ", strip=True)[:4000]
        except Exception as e:
            logger.debug(f"BOJA texto: {e}")
            return ""

# ─── DOGV SCRAPER (C. Valenciana) ────────────────────────────────────────────
class DOGVScraper:
    """
    DOGV — Diari Oficial de la Generalitat Valenciana
    XML por fecha: https://dogv.gva.es/datos/YYYY/MM/DD/xml/YYYYMMDD.xml
    Estructura confirmada similar al BOE.
    """
    BASE    = "https://dogv.gva.es"
    XML_URL = "https://dogv.gva.es/datos/{anyo}/{mes}/{dia}/xml/{fecha}.xml"

    def __init__(self, session):
        self.s = session

    def get_items(self, fecha: str) -> list:
        dt  = datetime.strptime(fecha, "%Y%m%d")
        url = self.XML_URL.format(
            anyo=dt.year, mes=f"{dt.month:02d}",
            dia=f"{dt.day:02d}", fecha=fecha
        )
        try:
            r = self.s.get(url, timeout=30)
            if r.status_code in (404, 403):
                return []
            r.raise_for_status()
            return self._parse_xml(r.content, fecha)
        except Exception as e:
            logger.warning(f"DOGV {fecha}: {e}")
            return []

    def _parse_xml(self, xml_bytes: bytes, fecha: str) -> list:
        items = []
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return []
        for item in root.iter("item"):
            titulo = (item.findtext("titulo") or item.findtext("TITULO") or "").strip()
            dept   = (item.findtext("organismo") or item.findtext("ORGANISMO") or
                      item.findtext("departamento") or "").strip()
            if not titulo or not es_relevante(titulo, departamento=dept):
                continue
            item_id  = (item.findtext("id") or item.findtext("identificador") or
                        f"DOGV-{fecha}-{len(items)}")
            url_html = item.findtext("url_html") or item.findtext("urlHtml") or ""
            url_pdf  = item.findtext("url_pdf") or item.findtext("urlPdf") or ""
            items.append({
                "boletin": "DOGV", "ccaa": "C. Valenciana",
                "id": item_id, "fecha": fecha,
                "departamento": dept, "titulo": titulo,
                "url": url_html, "url_pdf": url_pdf,
                "url_xml": "", "texto": ""
            })
        return items

    def get_texto(self, item: dict) -> str:
        url = item.get("url", "")
        if not url:
            return ""
        try:
            r = self.s.get(url, timeout=20)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")
            for sel in [".diari-contingut", ".field-items", "article", "main", "#contingut"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 200:
                        return t[:8000]
        except Exception as e:
            logger.warning(f"DOGV texto {item.get('id')}: {e}")
        return ""


# ─── DOGC SCRAPER (Cataluña) ─────────────────────────────────────────────────
class DOGCScraper:
    """
    DOGC — Diari Oficial de la Generalitat de Catalunya
    API REST: POST portaldogc.gencat.cat/eadop-rest/api/dogc/documentDOGC
    Body: documentId=YYYYMMDD&language=ca (form-urlencoded)
    No requiere Playwright.
    """
    BASE    = "https://dogc.gencat.cat"
    API_URL = "https://portaldogc.gencat.cat/eadop-rest/api/dogc/documentDOGC"

    def __init__(self, session):
        self.s = session

    def get_items(self, fecha: str) -> list:
        import ssl, urllib3
        from requests.adapters import HTTPAdapter
        import requests as _req
        urllib3.disable_warnings()

        # Python 3.14 eliminó soporte a cipher suites legacy
        # portaldogc.gencat.cat requiere TLS legacy — usar OP_LEGACY_SERVER_CONNECT
        try:
            from urllib3.util.ssl_ import create_urllib3_context
            ctx = create_urllib3_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            # Habilitar cipher suites legacy (necesario para portaldogc en Python 3.14)
            try:
                ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
            except Exception:
                pass
            try:
                ctx.set_ciphers("ALL:@SECLEVEL=0")
            except Exception:
                try:
                    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
                except Exception:
                    pass

            class LegacySSLAdapter(HTTPAdapter):
                def init_poolmanager(self, *args, **kwargs):
                    kwargs["ssl_context"] = ctx
                    return super().init_poolmanager(*args, **kwargs)
                def proxy_manager_for(self, proxy, **kwargs):
                    kwargs["ssl_context"] = ctx
                    return super().proxy_manager_for(proxy, **kwargs)

            dogc_s = _req.Session()
            dogc_s.mount("https://portaldogc", LegacySSLAdapter())
            dogc_s.mount("https://", LegacySSLAdapter())
            dogc_s.headers.update(self.s.headers)
        except Exception as e:
            logger.debug(f"DOGC SSL setup: {e}")
            dogc_s = self.s

        try:
            r = dogc_s.post(
                self.API_URL,
                data={"documentId": fecha, "language": "ca"},
                headers={
                    "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept":           "application/json, text/javascript, */*; q=0.01",
                    "Origin":           "https://dogc.gencat.cat",
                    "Referer":          "https://dogc.gencat.cat/",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=20,
                verify=False
            )
        except Exception as e:
            logger.warning(f"DOGC {fecha}: {e}")
            return []

        if r.status_code == 500:
            logger.debug(f"DOGC {fecha}: sin boletín o acceso restringido (500)")
            return []
        if r.status_code != 200:
            logger.warning(f"DOGC {fecha}: {r.status_code}")
            return []

        try:
            data = r.json()
        except Exception:
            logger.warning(f"DOGC {fecha}: respuesta no es JSON")
            return []

        return self._parse(data, fecha)

    def _parse(self, data, fecha: str) -> list:
        items = []
        # Normalizar estructura JSON del DOGC
        disposicions = []
        if isinstance(data, list):
            disposicions = data
        elif isinstance(data, dict):
            for key in ["disposicions","documents","items","results","data","registres"]:
                if key in data and isinstance(data[key], list):
                    disposicions = data[key]
                    break
            if not disposicions:
                for v in data.values():
                    if isinstance(v, list) and len(v) > 0:
                        disposicions = v
                        break

        for d in disposicions:
            if not isinstance(d, dict):
                continue
            titulo = (d.get("titol") or d.get("titulo") or
                     d.get("title") or d.get("nom") or "").strip()
            dept   = (d.get("organisme") or d.get("organismo") or
                     d.get("departament") or "").strip()
            url    = (d.get("urlHtml") or d.get("url_html") or d.get("url") or "").strip()
            url_pdf = (d.get("urlPdf") or d.get("url_pdf") or "").strip()
            item_id = str(d.get("id") or d.get("codi") or f"DOGC-{fecha}-{len(items)}")

            if not titulo or len(titulo) < 15:
                continue
            if not es_relevante(titulo, departamento=dept):
                continue

            items.append({
                "boletin": "DOGC", "ccaa": "Cataluña",
                "id": f"DOGC-{item_id}", "fecha": fecha,
                "departamento": dept, "titulo": titulo[:300],
                "url": url, "url_pdf": url_pdf,
                "url_xml": "", "texto": ""
            })
        return items

    def get_texto(self, item: dict) -> str:
        url = item.get("url","")
        if not url:
            return ""
        try:
            r = self.s.get(url, timeout=20)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")
            for sel in [".contingut-disposicio","#contingut",".cos-disposicio","article","main"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 200:
                        return t[:8000]
            return soup.get_text(" ", strip=True)[:4000]
        except Exception as e:
            logger.debug(f"DOGC texto: {e}")
            return ""


# ─── SCRAPER GENÉRICO HTML (DOG Galicia, BOPA, BOC, BORM) ──────────────────────
class GenericHTMLScraper:
    """
    Scraper genérico para boletines con estructura HTML por secciones.
    Adaptable a DOGC, DOG Galicia, BOPA, BOC Cantabria, BORM.
    """

    CONFIGS = {
        "DOGC": {
            "ccaa": "Cataluña",
            "base": "https://dogc.gencat.cat",
            "url_sumario": "https://dogc.gencat.cat/ca/pdogc_canals_interns/pdogc_resultats_fitxes/?action=fitxa&documentId={fecha}",
            "url_alt": "https://dogc.gencat.cat/ca/document-del-dogc/?documentId={yyyymmdd}",
        },
        "DOG": {
            "ccaa": "Galicia",
            "base": "https://www.xunta.gal",
            # DOG: secciones HTML accesibles directamente
            # Secciones3 = VI. Anuncios (principal para energía)
            # Secciones1 = III. Otras disposiciones (decretos, órdenes)
            "url_sumario": "https://www.xunta.gal/diario-oficial-galicia/mostrarContenido.do?lang=es&paginaCompleta=false&fecha={fecha}&ruta=/{anyo}/{fecha}/Secciones3_es.html",
            "url_otras": "https://www.xunta.gal/diario-oficial-galicia/mostrarContenido.do?lang=es&paginaCompleta=false&fecha={fecha}&ruta=/{anyo}/{fecha}/Secciones1_es.html",
        },
        "BOPA": {
            "ccaa": "Asturias",
            "base": "https://miprincipado.asturias.es",
            # PDF de sumario confirmado: /bopa/YYYY/MM/DD/YYYYMMDD.pdf
            "url_sumario": "https://miprincipado.asturias.es/bopa/{anyo}/{mes}/{dia}/{fecha}.pdf",
        },
        "BOC": {
            "ccaa": "Cantabria",
            "base": "https://boc.cantabria.es",
            "url_sumario": "https://boc.cantabria.es/boces/verAnuncioAction.do?idAnuncioFecha={yyyymmdd}",
        },
        "BORM": {
            "ccaa": "Murcia",
            "base": "https://www.borm.es",
            "resource_id": "1aa934a4-56a4-4b19-9193-bb9005c8bbc5",
            "url_sumario": "https://datosabiertos.regiondemurcia.es/api/3/action/datastore_search?resource_id=1aa934a4-56a4-4b19-9193-bb9005c8bbc5&q={dia}/{mes}/{anyo}&limit=200",
        },
        "BON": {
            # Boletín Oficial de Navarra — búsqueda por fecha
            "ccaa": "Navarra",
            "base": "https://bon.navarra.es",
            "url_sumario": "https://bon.navarra.es/es/boletin/-/boletin/list/findByDate?date={dia}%2F{mes}%2F{anyo}",
            "url_alt":     "https://bon.navarra.es/es/anuncio/-/texto/{anyo}/{fecha}/0",
        },
        "BOLR": {
            # Boletín Oficial de La Rioja
            "ccaa": "La Rioja",
            "base": "https://www.larioja.org",
            "url_sumario": "https://www.larioja.org/bor/es?fecha={anyo}-{mes}-{dia}",
            "url_alt":     "https://ias1.larioja.org/boletin/Bor?ACCL=BLT_LST&FECHA={dia}/{mes}/{anyo}",
        },
    }

    def __init__(self, session, nombre: str):
        self.s      = session
        self.nombre = nombre
        self.cfg    = self.CONFIGS.get(nombre, {})
        self.ccaa   = self.cfg.get("ccaa", nombre)
        self.base   = self.cfg.get("base", "")

    def _build_url(self, fecha: str) -> str:
        dt   = datetime.strptime(fecha, "%Y%m%d")
        tmpl = self.cfg.get("url_sumario", "")
        return tmpl.format(
            fecha=fecha, yyyymmdd=fecha,
            anyo=dt.year, mes=f"{dt.month:02d}", dia=f"{dt.day:02d}",
        )

    def _build_urls(self, fecha: str) -> list:
        """Construye todas las URLs a consultar para este boletín."""
        dt   = datetime.strptime(fecha, "%Y%m%d")
        urls = []
        for key in ["url_sumario", "url_otras", "url_alt"]:
            tmpl = self.cfg.get(key, "")
            if tmpl:
                urls.append(tmpl.format(
                    fecha=fecha, yyyymmdd=fecha,
                    anyo=dt.year, mes=f"{dt.month:02d}", dia=f"{dt.day:02d}",
                ))
        return urls

    def get_items(self, fecha: str) -> list:
        items_total = []
        ids_vistos  = set()
        urls = self._build_urls(fecha)

        for url in urls:
            try:
                r = self.s.get(url, timeout=30, allow_redirects=True)
                if r.status_code in (404, 403) or len(r.content) < 200:
                    continue
                ct = r.headers.get("Content-Type", "")
                if "pdf" in ct or url.lower().endswith(".pdf"):
                    nuevos = self._parse_pdf(r.content, fecha, url)
                elif "json" in ct:
                    nuevos = self._parse_ckan_json(r.json(), fecha)
                elif "xml" in ct or r.text.strip().startswith("<?xml"):
                    nuevos = self._parse_xml(r.content, fecha)
                else:
                    nuevos = self._parse_html(r.text, fecha)
                for item in nuevos:
                    key = item.get("titulo","")[:80]
                    if key not in ids_vistos:
                        ids_vistos.add(key)
                        items_total.append(item)
            except Exception as e:
                logger.debug(f"{self.nombre} {url[-40:]}: {e}")

        return items_total

    def _parse_pdf(self, pdf_bytes: bytes, fecha: str, url_pdf: str) -> list:
        """Extrae disposiciones del PDF de sumario del BOPA."""
        try:
            import pdfplumber, io
            pdf  = pdfplumber.open(io.BytesIO(pdf_bytes))
            text = ""
            for page in pdf.pages[:10]:
                t = page.extract_text()
                if t:
                    text += t + "\n"
            pdf.close()
        except ImportError:
            logger.debug("pdfplumber no instalado — pip install pdfplumber")
            return []
        except Exception as e:
            logger.debug(f"{self.nombre} PDF: {e}")
            return []

        # Recomponer párrafos: las líneas del PDF se cortan con guion o siguen
        # en la siguiente. Hay que juntar fragmentos en oraciones completas.
        parrafos = []
        buf = ""
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                if buf:
                    parrafos.append(buf)
                    buf = ""
                continue
            # Detectar consejería/sección (sin unir al buffer)
            if (any(w in line for w in ["Consejería","Consejeria","Presidencia",
                                         "Dirección General","Servicio","Agencia"])
                    and len(line) < 150 and not buf):
                parrafos.append("__DEPT__" + line)
                continue
            # Si la línea anterior termina en guion, es continuación
            if buf.endswith("-"):
                buf = buf[:-1] + line   # unir sin espacio (guion de partición)
            elif buf:
                buf = buf + " " + line
            else:
                buf = line
            # Si la línea termina en punto/corchete/cierra paréntesis = fin de frase
            if line.endswith((".", "]", ")")) or re.search(r"\[\d+ págs?\.?\]$", line):
                parrafos.append(buf)
                buf = ""
        if buf:
            parrafos.append(buf)

        items = []
        dept  = ""
        for parrafo in parrafos:
            if parrafo.startswith("__DEPT__"):
                dept = parrafo[8:]
                continue
            parrafo = parrafo.strip()
            if len(parrafo) > 40 and es_relevante(parrafo, departamento=dept):
                items.append({
                    "boletin": self.nombre, "ccaa": self.ccaa,
                    "id": f"{self.nombre}-{fecha}-{len(items)}",
                    "fecha": fecha, "departamento": dept,
                    "titulo": parrafo[:500], "url": "",
                    "url_pdf": url_pdf, "url_xml": "", "texto": ""
                })
        return items

    def _parse_ckan_json(self, data: dict, fecha: str) -> list:
        """Parser para respuestas de la API CKAN (BORM datos abiertos)."""
        items = []
        result = data.get("result", {})
        records = result.get("records", []) if isinstance(result, dict) else []

        for rec in records:
            titulo = (rec.get("TITULO") or rec.get("titulo") or
                     rec.get("SUMARIO") or rec.get("sumario") or "").strip()
            dept   = (rec.get("DEPARTAMENTO") or rec.get("departamento") or
                     rec.get("ORGANISMO") or rec.get("organismo") or "").strip()
            url    = (rec.get("URL") or rec.get("url") or
                     rec.get("URL_HTML") or "").strip()
            url_pdf = (rec.get("URL_PDF") or rec.get("url_pdf") or "").strip()

            if not titulo or len(titulo) < 15:
                continue
            if not es_relevante(titulo, departamento=dept):
                continue

            items.append({
                "boletin": self.nombre, "ccaa": self.ccaa,
                "id": f"{self.nombre}-{fecha}-{len(items)}",
                "fecha": fecha, "departamento": dept,
                "titulo": titulo[:300], "url": url,
                "url_pdf": url_pdf, "url_xml": "", "texto": ""
            })
        return items

    def _parse_xml(self, xml_bytes: bytes, fecha: str) -> list:
        items = []
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return []
        for item in root.iter("item"):
            titulo = (item.findtext("titulo") or item.findtext("title") or "").strip()
            dept   = (item.findtext("organismo") or item.findtext("departamento") or "").strip()
            if not titulo or not es_relevante(titulo, departamento=dept):
                continue
            item_id  = item.findtext("id") or f"{self.nombre}-{fecha}-{len(items)}"
            url_html = item.findtext("url_html") or ""
            url_pdf  = item.findtext("url_pdf") or ""
            items.append({
                "boletin": self.nombre, "ccaa": self.ccaa,
                "id": item_id, "fecha": fecha,
                "departamento": dept, "titulo": titulo,
                "url": url_html, "url_pdf": url_pdf,
                "url_xml": "", "texto": ""
            })
        return items

    def _parse_html(self, html: str, fecha: str) -> list:
        soup  = BeautifulSoup(html, "lxml")
        items = []
        dept  = ""

        # Detectar estructura DOG Galicia
        es_dog = "Consellería" in html or "Conselleria" in html or "Xunta de Galicia" in html
        if es_dog:
            return self._parse_dog(soup, fecha)

        # Detectar BOPA (Liferay portlet SedeBopaDispositionWeb)
        es_bopa = "SedeBopaDispositionWeb" in html or "bopa-input" in html or "miprincipado.asturias.es" in html
        if es_bopa:
            return self._parse_bopa(soup, fecha)

        # Parser genérico para otros boletines
        for el in soup.find_all(["h2","h3","h4","h5","p","li","div","td"]):
            txt = el.get_text(" ", strip=True)
            if not txt or len(txt) < 10:
                continue
            # Detectar cabecera de organismo
            if (any(w in txt for w in ["Conselleria","Consejería","Departament",
                                        "Dirección General","Agencia","Servizo",
                                        "Consellaría","Consellería de"])
                    and len(txt) < 150):
                dept = txt
                continue
            # Detectar título de disposición relevante
            if len(txt) > 50 and es_relevante(txt, departamento=dept):
                a = el.find("a", href=True) or el.find_parent("a")
                url = ""
                if a and a.get("href"):
                    url = a["href"]
                    if not url.startswith("http"):
                        url = self.base + url
                items.append({
                    "boletin": self.nombre, "ccaa": self.ccaa,
                    "id": f"{self.nombre}-{fecha}-{len(items)}",
                    "fecha": fecha, "departamento": dept, "titulo": txt[:300],
                    "url": url, "url_pdf": "", "url_xml": "", "texto": ""
                })
        return items

    def _parse_dog(self, soup, fecha: str) -> list:
        """
        Parser específico para DOG Galicia.
        Estructura: organismo en h2/h3/h4/strong, luego anuncios en párrafos o links.
        Cada anuncio tiene: título largo + número de página + link PDF.
        """
        items = []
        dept  = ""

        for el in soup.find_all(["h2","h3","h4","strong","p","td","li","span"]):
            txt = el.get_text(" ", strip=True)
            if not txt:
                continue

            # Detectar consellería/organismo (texto corto sin números de página)
            if (any(w in txt for w in ["Consellería","Conselleria","Consellaría",
                                        "Presidencia","Vicepresidencia","Axencia",
                                        "Dirección Xeral","Instituto","Servizo"])
                    and len(txt) < 150 and not any(c.isdigit() and len(c)>3
                                                    for c in txt.split())):
                dept = txt.strip()
                continue

            # Anuncio energético
            if len(txt) > 60 and es_relevante(txt, departamento=dept):
                # Buscar enlace PDF asociado
                url_pdf = ""
                url_html = ""
                # El link suele estar en el mismo elemento o el siguiente
                a = el.find("a", href=True)
                if not a:
                    # Buscar en elementos hermanos
                    next_el = el.find_next_sibling()
                    if next_el:
                        a = next_el.find("a", href=True)
                if a and a.get("href"):
                    href = a["href"]
                    if ".pdf" in href.lower():
                        url_pdf = href if href.startswith("http") else self.base + href
                    else:
                        url_html = href if href.startswith("http") else self.base + href

                # Limpiar título (quitar número de página al final)
                import re
                titulo_limpio = re.sub(r'\s+\d{4,6}\s*$', '', txt).strip()

                if titulo_limpio and len(titulo_limpio) > 40:
                    items.append({
                        "boletin": self.nombre, "ccaa": self.ccaa,
                        "id": f"{self.nombre}-{fecha}-{len(items)}",
                        "fecha": fecha, "departamento": dept,
                        "titulo": titulo_limpio[:300],
                        "url": url_html, "url_pdf": url_pdf,
                        "url_xml": "", "texto": ""
                    })
        return items

    def _parse_bopa(self, soup, fecha: str) -> list:
        """
        Parser para el BOPA Asturias (Liferay).
        URL: disposiciones?p_r_p_dispositionDate=DD%2FMM%2FYYYY
        Estructura: los items están dentro del portlet SedeBopaDispositionWeb
        como links (<a>) con texto de disposición.
        """
        items = []
        dept  = ""

        # Buscar el portlet principal del BOPA
        portlet = (
            soup.find("div", class_=lambda c: c and "sede-bopa-search" in c) or
            soup.find(id=lambda x: x and "SedeBopaDispositionWeb" in (x or "")) or
            soup.find("section", id=lambda x: x and "SedeBopaDispositionWeb" in (x or "")) or
            soup
        )

        # Iterar por todos los elementos buscando links energéticos
        for el in portlet.find_all(True, recursive=True):
            txt = el.get_text(" ", strip=True)
            if not txt:
                continue

            # Detectar consejería (texto corto que precede a los items)
            if el.name in ("h2","h3","h4","h5","strong","b","span") and len(txt) < 150:
                if any(w in txt for w in ["Consejería","Consejería","Servicio","Dirección",
                                           "Presidencia","Agencia","Viceconsejería"]):
                    dept = txt
                    continue

            # Detectar disposición como link
            if el.name == "a" and el.get("href") and len(txt) > 30:
                href = el["href"]
                url  = href if href.startswith("http") else "https://miprincipado.asturias.es" + href
                if es_relevante(txt, departamento=dept):
                    items.append({
                        "boletin": self.nombre, "ccaa": self.ccaa,
                        "id": f"{self.nombre}-{fecha}-{len(items)}",
                        "fecha": fecha, "departamento": dept,
                        "titulo": txt[:300], "url": url,
                        "url_pdf": "", "url_xml": "", "texto": ""
                    })

        return items

    def get_texto(self, item: dict) -> str:
        url = item.get("url", "")
        if not url:
            return ""
        try:
            r = self.s.get(url, timeout=20)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")
            for sel in [".field-items", ".contingut", ".node-content",
                        "article", "main", "#contingut", ".body"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 200:
                        return t[:8000]
        except Exception as e:
            logger.warning(f"{self.nombre} texto {item.get('id')}: {e}")
        return ""



# ─── BOA ARAGÓN ─────────────────────────────────────────────────────────────
class BOAScraper:
    """
    BOA — Boletín Oficial de Aragón
    Estrategia: VERLST → MLKOB del PDF completo → pdfplumber → parsear texto
    El primer MLKOB &type=pdf es siempre el BOA completo (title="Ver pdf del boletín completo").
    Estructura del PDF: secciones → departamentos → títulos → csv: BOA{fecha}{NNN}
    Requiere: pip install pdfplumber
    """
    BASE_CGI = "https://www.boa.aragon.es/cgi-bin/EBOA"
    URL_VERLST = (BASE_CGI
                  + "/BRSCGI?CMD=VERLST&DOCS=1-200&BASE=BOLE"
                  + "&SEC=BUSQUEDA_FECHA&SEPARADOR=&PUBL={fecha}")

    def __init__(self, session):
        self.s = session

    def get_items(self, fecha: str) -> list:
        try:
            import pdfplumber, io as _io
        except ImportError:
            logger.warning("BOA: pdfplumber no instalado → pip install pdfplumber")
            return []

        # 1. Obtener VERLST para encontrar el MLKOB del PDF completo
        url_verlst = self.URL_VERLST.format(fecha=fecha)
        try:
            r = self.s.get(url_verlst, timeout=25)
            if r.status_code != 200:
                logger.debug(f"BOA VERLST {fecha}: {r.status_code}")
                return []
            enc  = r.encoding or "iso-8859-1"
            html = r.content.decode(enc, errors="replace").replace("&amp;", "&")
        except Exception as e:
            logger.warning(f"BOA VERLST: {e}")
            return []

        # 2. Extraer MLKOB del PDF completo (primer PDF con &type=pdf)
        mlkobs_pdf = re.findall(r'CMD=VEROBJ&MLKOB=(\d{13})&type=pdf', html)
        if not mlkobs_pdf:
            logger.debug(f"BOA {fecha}: sin PDF en VERLST")
            return []
        mlkob = mlkobs_pdf[0]  # El primero es siempre el BOA completo
        url_pdf = f"{self.BASE_CGI}/BRSCGI?CMD=VEROBJ&MLKOB={mlkob}&type=pdf"

        # 3. Descargar PDF completo
        try:
            rp = self.s.get(url_pdf, timeout=60)
            if rp.status_code != 200:
                logger.debug(f"BOA PDF {mlkob}: {rp.status_code}")
                return []
            logger.debug(f"BOA PDF {mlkob}: {rp.status_code} {len(rp.content)}B")
        except Exception as e:
            logger.warning(f"BOA PDF: {e}")
            return []

        # 4. Extraer texto con pdfplumber
        try:
            with pdfplumber.open(_io.BytesIO(rp.content)) as pdf:
                pages_text = [p.extract_text() or "" for p in pdf.pages]
            full_text = "\n".join(pages_text)
        except Exception as e:
            logger.warning(f"BOA pdfplumber: {e}")
            return []

        # 5. Parsear entradas del texto del sumario
        return self._parse_pdf_text(full_text, fecha, url_pdf)

    def _parse_pdf_text(self, text: str, fecha: str, url_pdf_completo: str) -> list:
        """
        Parsea el texto extraído del PDF del BOA.
        Estructura: Sección → Departamento (MAYÚSCULAS) → Título → csv: BOA{YYYYMMDD}{NNN}
        """
        items  = []
        dept   = ""
        seccion = ""
        buf    = []   # líneas del título actual
        csv_id = None

        SECCIONES_PATTERN = re.compile(
            r'^(I{1,3}V?|IV|V?I{0,3})\.\s+.{5,}$'
        )
        DEPT_PATTERN = re.compile(
            r'^(DEPARTAMENTO|CONSEJERÍA|DIRECCIÓN GENERAL|INSTITUTO|SERVICIO|'
            r'PRESIDENCIA|VICEPRESIDENCIA|GOBIERNO DE ARAGÓN|TRIBUNAL|JEFATURA).{0,150}$'
        )
        # csv: BOA20260518NNN (>=11 dígitos) = entrada real
        # csv: BOA20260518   (8 dígitos)     = separador de página
        CSV_ENTRY_PAT = re.compile(r'^csv:\s+(BOA\d{8}\d{3,})\s*$')
        CSV_SEP_PAT   = re.compile(r'^csv:\s+BOA\d{8}\s*$')

        def flush(csv_code):
            nonlocal buf
            titulo = " ".join(buf).strip()
            buf = []
            if not titulo or len(titulo) < 40:
                return
            if not es_relevante(titulo, departamento=dept):
                return
            items.append({
                "boletin": "BOA", "ccaa": "Aragón",
                "id": csv_code,
                "fecha": fecha, "departamento": dept,
                "seccion": seccion,
                "titulo": titulo[:400],
                "url": "", "url_pdf": url_pdf_completo,
                "url_xml": "", "texto": ""
            })

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # Separadores de página → limpiar buffer, no crear item
            if CSV_SEP_PAT.match(line):
                buf = []
                continue

            m_csv = CSV_ENTRY_PAT.match(line)
            if m_csv:
                flush(m_csv.group(1))
                continue

            if SECCIONES_PATTERN.match(line):
                buf = []
                seccion = line
                continue

            if DEPT_PATTERN.match(line):
                buf = []
                dept = line
                continue

            # Ignorar cabeceras del PDF, notas legales, subsecciones
            if re.match(r'^(BOLETÍN OFICIAL|AÑO |Sumario|Núm\.|Depósito legal)', line, re.IGNORECASE):
                buf = []
                continue
            if re.match(r'^\d{1,4}$', line):   # números de página solos
                continue
            if re.match(r'^[a-z]\)', line):     # "a)" "b)" subsecciones
                buf = []
                continue
            buf.append(line)

        logger.debug(f"BOA {fecha}: {len(items)} items energéticos del PDF")
        return items

    def get_texto(self, item: dict) -> str:
        return ""  # El texto completo está en el PDF — no se extrae por defecto

# ─── BOPV PAÍS VASCO ─────────────────────────────────────────────────────────
class BOPVScraper:
    """
    BOPV — Boletín Oficial del País Vasco / Euskal Herriko Agintaritzaren Aldizkaria (EHAA)

    La URL /bopv2/ está protegida por WAF (403). El acceso correcto es vía:
      Portal:  https://www.euskadi.eus/y22-bopv/es/
      Datos:   https://www.euskadi.eus/web01-bopv/es/bopv2/datos/YYYY/MM/
      Último:  https://www.euskadi.eus/web01-bopv/es/bopv2/datos/Ultimo.shtml

    Ficheros shtml del sumario: YYMMNNNa.shtml (castellano) / YYMMNNNe.shtml (euskera)
    donde NNN = número de boletín del año (3 o 4 dígitos).

    Estrategias:
      1. Último boletín → verifica si es la fecha pedida (uso en ejecución diaria)
      2. Directorio mensual → busca shtml del día
      3. Sondeo por número estimado ±5 (con early-exit si WAF)
      4. Búsqueda por keyword + fecha
    """
    BASE        = "https://www.euskadi.eus"
    # Rutas accesibles (sin WAF)
    URL_PORTAL  = "https://www.euskadi.eus/y22-bopv/es/"
    URL_ULTIMO  = "https://www.euskadi.eus/web01-bopv/es/bopv2/datos/Ultimo.shtml"
    URL_DIR     = "https://www.euskadi.eus/web01-bopv/es/bopv2/datos/{yyyy}/{mm}/"
    URL_SEARCH  = "https://www.euskadi.eus/web01-bopv/es/bopv2/busqueda/"

    # Palabras clave de búsqueda energética
    KEYWORDS_BOPV = [
        "energia solar", "fotovoltaico", "eoliko", "hidrogeno",
        "energia berriztagarria", "energia renovable",
    ]

    # Headers que imitan Chrome — necesarios para evitar WAF de euskadi.eus
    CHROME_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;"
            "q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language":           "es-ES,es;q=0.9,eu;q=0.8",
        "Accept-Encoding":           "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none",
        "Sec-Fetch-User":            "?1",
        "Sec-Ch-Ua":                 '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile":          "?0",
        "Sec-Ch-Ua-Platform":        '"Windows"',
        "Cache-Control":             "max-age=0",
    }

    def __init__(self, session):
        self.s = session
        self.s.headers.update(self.CHROME_HEADERS)

    # ------------------------------------------------------------------ #
    def get_items(self, fecha: str) -> list:
        dt   = datetime.strptime(fecha, "%Y%m%d")
        yyyy = dt.year
        mm   = f"{dt.month:02d}"
        yy   = str(yyyy)[2:]
        dd   = f"{dt.day:02d}"

        items_dict: dict = {}

        # ── 0. Ultimo.shtml — solo si fecha == hoy (siempre apunta al boletín actual) ─
        today = datetime.now().strftime("%Y%m%d")
        if fecha == today:
            try:
                r = self.s.get(self.URL_ULTIMO, timeout=15)
                logger.debug(f"BOPV Ultimo.shtml: {r.status_code} {len(r.content)}B")
                if r.status_code == 200 and len(r.content) > 3000:
                    for item in self._parse(r.text, fecha, self.URL_ULTIMO):
                        items_dict[item["url"]] = item
            except Exception as e:
                logger.debug(f"BOPV Ultimo.shtml: {e}")

            if items_dict:
                items = list(items_dict.values())
                logger.debug(f"BOPV {fecha}: {len(items)} items (vía Ultimo.shtml)")
                return items
            # Si Ultimo.shtml no dio resultados energéticos hoy, devolver lista vacía
            # (no tiene sentido buscar el mismo boletín por otra vía)
            logger.debug(f"BOPV {fecha}: 0 items energéticos en Ultimo.shtml")
            return []

        # ── 1. Directorio mensual → detectar shtml del día ─────────────
        url_dir = self.URL_DIR.format(yyyy=yyyy, mm=mm)
        try:
            r = self.s.get(url_dir, timeout=20)
            logger.debug(f"BOPV dir: status={r.status_code} size={len(r.content)}")
            if r.status_code == 200 and len(r.content) > 1000:
                soup_dir = BeautifulSoup(r.text, "lxml")
                shtml_links = soup_dir.find_all(
                    "a", href=re.compile(rf"/{yyyy}/{mm}/\d+a\.shtml", re.I)
                )
                logger.debug(f"BOPV dir: {len(shtml_links)} ficheros shtml")
                for a in shtml_links:
                    href  = a["href"]
                    url_s = href if href.startswith("http") else self.BASE + href
                    try:
                        rs = self.s.get(url_s, timeout=20)
                        if rs.status_code == 200 and dd in rs.text:
                            for item in self._parse(rs.text, fecha, url_s):
                                items_dict[item["url"]] = item
                    except Exception as e2:
                        logger.debug(f"BOPV shtml {url_s}: {e2}")
        except Exception as e:
            logger.debug(f"BOPV dir: {e}")

        # ── 2. Sondeo por número estimado (formatos A y B) ──────────────
        # www.euskadi.eus aplica WAF — si da 403 constante, saltamos.
        if not items_dict:
            jan1      = datetime(yyyy, 1, 1)
            n_est     = max(1, int((dt - jan1).days * 248 / 365))
            got_403   = 0
            for delta in range(-4, 5):
                n = n_est + delta
                if n < 1 or n > 300:
                    continue
                for fmt in [f"{yy}{mm}{n:03d}a.shtml",   # Formato A (3-dig)
                            f"{yy}{mm}{n:04d}a.shtml"]:  # Formato B (4-dig)
                    url_s = self.URL_DIR.format(yyyy=yyyy, mm=mm) + fmt
                    try:
                        rs = self.s.get(url_s, timeout=12)
                        if rs.status_code == 403:
                            got_403 += 1
                            if got_403 >= 3:
                                logger.debug("BOPV: WAF activo (403 constante) — abortando sondeo")
                                break
                            continue
                        if rs.status_code == 200 and len(rs.content) > 5000:
                            logger.debug(f"BOPV shtml {fmt}: encontrado ({len(rs.content)}B)")
                            if dd in rs.text or mm in rs.text:
                                for item in self._parse(rs.text, fecha, url_s):
                                    items_dict[item["url"]] = item
                                if items_dict:
                                    break
                    except Exception as e:
                        logger.debug(f"BOPV shtml {fmt}: {e}")
                if got_403 >= 3 or items_dict:
                    break

        # ── 3. Búsqueda por keyword + fecha ────────────────────────────
        if not items_dict:
            fi = f"{dd}/{mm}/{yyyy}"
            for kw in self.KEYWORDS_BOPV[:4]:
                for lang in ("es", "eu"):
                    params = {"lang": lang, "text": kw,
                              "fechaInicio": fi, "fechaFin": fi}
                    try:
                        r = self.s.get(self.URL_SEARCH, params=params, timeout=20)
                        if r.status_code == 200 and len(r.content) > 3000:
                            for item in self._parse(r.text, fecha, self.URL_SEARCH):
                                if item["url"] not in items_dict:
                                    items_dict[item["url"]] = item
                    except Exception as e:
                        logger.debug(f"BOPV search kw={kw!r}: {e}")

        items = list(items_dict.values())
        logger.debug(f"BOPV {fecha}: {len(items)} items energéticos")
        return items

    # Base para resolver URLs relativas de Ultimo.shtml
    URL_DATOS = "https://www.euskadi.eus/web01-bopv/es/bopv2/datos/"

    def _parse(self, html: str, fecha: str, base_url: str) -> list:
        """
        Parsea el HTML del BOPV (Ultimo.shtml o disposición individual).

        Estructura de Ultimo.shtml:
          - Links relativos a disposiciones: "2026/05/2602047a.shtml"
          - Texto del link = título de la disposición
          - Departamento en encabezados h2/h3 entre grupos de links

        Los links se resuelven contra URL_DATOS (base del directorio de datos).
        """
        soup  = BeautifulSoup(html, "lxml")
        items = []
        seen  = set()
        dept  = ""

        # Patrón de links a disposiciones BOPV:
        # Relativo: "2026/05/2602047a.shtml"
        # Absoluto: "/web01-bopv/es/bopv2/datos/2026/05/2602047a.shtml"
        DISP_PAT = re.compile(r"\d{4}/\d{2}/\d+[ae]\.shtml$", re.I)
        DEPT_WORDS = [
            "Departamento", "Eusko Jaurlaritza", "Gobierno Vasco",
            "Agencia", "Instituto", "Dirección", "Viceconsejería",
            "Kontseilua", "Sailburua", "Ministerio",
        ]

        for el in soup.find_all(["h2", "h3", "h4", "h5", "li", "p", "div", "a"]):
            txt = el.get_text(" ", strip=True)
            if not txt:
                continue

            # Detectar departamento/organismo emisor
            # Nota: headings en BOPV están en MAYÚSCULAS → comparación case-insensitive
            if el.name in ("h2", "h3", "h4", "h5"):
                txt_lower_h = txt.lower()
                if any(w.lower() in txt_lower_h for w in DEPT_WORDS) and len(txt) < 250:
                    dept = txt
                    continue

            # Link a una disposición individual
            if el.name == "a" and el.get("href"):
                href = el["href"]
                # Solo procesar links que parecen disposiciones BOPV
                if not (DISP_PAT.search(href) or "web01-bopv" in href):
                    continue
                titulo = txt
                if len(titulo) < 20:
                    continue
                # Resolver URL relativa contra la base de datos
                if href.startswith("http"):
                    url_item = href
                elif href.startswith("/"):
                    url_item = self.BASE + href
                else:
                    url_item = self.URL_DATOS + href
                if url_item in seen:
                    continue
                seen.add(url_item)
                if not es_relevante(titulo, departamento=dept):
                    continue
                items.append({
                    "boletin": "BOPV", "ccaa": "País Vasco",
                    "id":     f"BOPV-{url_item.split('/')[-1].replace('.shtml','')}",
                    "fecha":  fecha,
                    "departamento": dept,
                    "titulo": titulo[:300],
                    "url":    url_item, "url_pdf": url_item, "url_xml": "", "texto": "",
                })

        logger.debug(f"BOPV _parse: {len(items)} items energéticos desde {base_url[-50:]}")
        return items

    def get_texto(self, item: dict) -> str:
        url = item.get("url", "")
        if not url:
            return ""
        try:
            r = self.s.get(url, timeout=20)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")
            for sel in [".contenido", "#contenido", ".bopv-texto",
                        "article", "main", "#texto"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 200:
                        return t[:8000]
            return soup.get_text(" ", strip=True)[:4000]
        except Exception as e:
            logger.debug(f"BOPV texto: {e}")
            return ""



# ─── DOE EXTREMADURA ─────────────────────────────────────────────────────────
class DOEScraper:
    """
    DOE — Diario Oficial de Extremadura
    Acceso directo al sumario por fecha vía:
      https://doe.juntaex.es/ultimosdoe/mostrardoe.php?fecha=YYYYMMDD&t=o

    NOTA: El form POST de disposiciones.php no funciona sin sesión JS —
    siempre devuelve la homepage (9849 B). Usamos el sumario directo en su lugar.

    Estructura HTML de mostrardoe.php:
      <div class="Contenido_DOE">
        <p><span class="DOE2">CONSEJERÍA DE ...</span></p>   ← dept header (sin enlace)
        <div class="justificado">
          <p>
            <span class="DOE2">Energía solar.-</span>
            <span class="DOE4">Resolución de... texto completo.</span>
            <a class="enlace_dis" href="/pdfs/doe/2026/940o/26050052.pdf">...</a>
          </p>
        </div>
        ...
      </div>
    """
    BASE    = "https://doe.juntaex.es"
    URL_DIA = "https://doe.juntaex.es/ultimosdoe/mostrardoe.php?fecha={fecha}&t={tipo}"
    TIPOS   = ["o", "e", "s"]   # ordinario, extraordinario, suplemento

    # PDF individual de cada disposición (6-10 dígitos numéricos)
    IND_PDF = re.compile(r"/pdfs/doe/\d{4}/\w+/\d{6,10}\.pdf$", re.I)

    def __init__(self, session):
        self.s = session
        self.s.headers.update({
            "Referer": self.BASE + "/index.php",
            "Accept":  "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
        })
        self._sesion_lista = False

    def _init_sesion(self):
        """Obtener cookie BIGip y Referer correctos."""
        if not self._sesion_lista:
            try:
                self.s.get(self.BASE + "/index.php", timeout=10)
                self._sesion_lista = True
            except Exception:
                pass

    def get_items(self, fecha: str) -> list:
        self._init_sesion()
        items: list = []
        seen:  set  = set()

        for tipo in self.TIPOS:
            url = self.URL_DIA.format(fecha=fecha, tipo=tipo)
            try:
                r = self.s.get(url, timeout=20)
                logger.debug(f"DOE {url[-55:]}: HTTP {r.status_code} {len(r.content)}B")
                if r.status_code != 200:
                    continue
                enc  = r.encoding or "iso-8859-1"
                html = r.content.decode(enc, errors="replace")
                if "D.O.E. No encontrado" in html:
                    logger.debug(f"DOE {fecha} tipo={tipo!r}: sin publicación")
                    continue
                for item in self._parse(html, fecha):
                    if item["url_pdf"] not in seen:
                        seen.add(item["url_pdf"])
                        items.append(item)
            except Exception as e:
                logger.debug(f"DOE {url[-45:]}: {e}")

        logger.debug(f"DOE {fecha}: {len(items)} items energéticos")
        return items

    def _parse(self, html: str, fecha: str) -> list:
        soup  = BeautifulSoup(html, "lxml")
        items = []
        seen  = set()

        contenido = soup.find("div", class_="Contenido_DOE") or soup
        dept_actual = ""

        for el in contenido.children:
            if not hasattr(el, "name") or not el.name:
                continue

            # ── Cabecera de departamento/sección ─────────────────────────
            if el.name == "p":
                span2 = el.find("span", class_="DOE2")
                # Dept header: tiene DOE2 pero NO enlace_dis
                if span2 and not el.find("a", class_="enlace_dis"):
                    dept_actual = span2.get_text(" ", strip=True)
                continue

            # ── Disposición: <div class="justificado"> ───────────────────
            if el.name != "div" or "justificado" not in (el.get("class") or []):
                continue

            p = el.find("p")
            if not p:
                continue
            a_pdf = p.find("a", href=self.IND_PDF)
            if not a_pdf:
                continue
            href = a_pdf.get("href", "")
            if href in seen:
                continue

            # Título: descriptor (DOE2) + texto completo (DOE4)
            span2  = p.find("span", class_="DOE2")
            span4  = p.find("span", class_="DOE4")
            desc   = span2.get_text(" ", strip=True) if span2 else ""
            cuerpo = span4.get_text(" ", strip=True) if span4 else p.get_text(" ", strip=True)
            titulo = f"{desc} {cuerpo}".strip() if desc else cuerpo
            if len(titulo) < 15:
                continue

            seen.add(href)
            url_pdf = href if href.startswith("http") else self.BASE + href

            if not es_relevante(titulo, departamento=dept_actual):
                continue

            item_id = "DOE-" + href.rsplit("/", 1)[-1].replace(".pdf", "")
            items.append({
                "boletin": "DOE", "ccaa": "Extremadura",
                "id":           item_id,
                "fecha":        fecha,
                "departamento": dept_actual,
                "titulo":       titulo[:300],
                "url":          url_pdf,
                "url_pdf":      url_pdf,
                "url_xml":      "",
                "texto":        "",
            })

        logger.debug(f"DOE _parse {fecha}: {len(items)} items")
        return items

    def get_texto(self, item: dict) -> str:
        return ""   # PDFs demasiado pesados; texto vacío por ahora




# ─── BON NAVARRA ─────────────────────────────────────────────────────────────
class BONScraper:
    """
    BON — Boletín Oficial de Navarra

    Estrategia dual:
      - Día actual  → /es/ultimo (SSR, rápido)
      - Histórico   → /es/indice-boletines → buscar enlace de la edición por fecha
                      → fetch de esa edición → parsear anuncios
    """
    BASE        = "https://bon.navarra.es"
    URL_ULTIMO  = "https://bon.navarra.es/es/ultimo"
    URL_INDICE  = "https://bon.navarra.es/es/indice-boletines"

    ANUNCIO_PAT = re.compile(r"/es/anuncio/-/texto/\d{4}/\d+/\d+")
    EDICION_PAT = re.compile(r"/es/boletin/-/boletin/\d{4}/\d+")
    FECHA_PAT   = re.compile(
        r"(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto"
        r"|septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})", re.I
    )
    MESES = {
        "enero":"01","febrero":"02","marzo":"03","abril":"04",
        "mayo":"05","junio":"06","julio":"07","agosto":"08",
        "septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12",
    }

    def __init__(self, session):
        self.s = session
        self.s.headers.update({
            "Referer": self.BASE + "/es/",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
        })

    def get_items(self, fecha: str) -> list:
        # ── 1. Ruta rápida: /es/ultimo (solo si es el boletín del día pedido) ──
        try:
            r = self.s.get(self.URL_ULTIMO, timeout=25)
            if r.status_code == 200:
                enc  = r.encoding or "utf-8"
                html = r.content.decode(enc, errors="replace")
                if self._extraer_fecha(html) == fecha:
                    items = self._parse(html, fecha)
                    logger.debug(f"BON {fecha} (ultimo): {len(items)} items")
                    return items
        except Exception as e:
            logger.debug(f"BON /es/ultimo: {e}")

        # ── 2. Ruta histórica: índice → buscar anuncios directos o nº edición ──
        items, num_edicion = self._buscar_en_indice(fecha)
        if items:
            logger.debug(f"BON {fecha} (índice directo): {len(items)} items")
            return items

        # ── 3. Si tenemos nº de edición, enumerar anuncios individualmente ──────
        #     Las páginas de edición son JS-rendered; las de anuncio son SSR.
        #     Enumeramos /es/anuncio/-/texto/{yyyy}/{num}/{i} i=1…N
        #     y nos detenemos tras MAX_FALLOS errores consecutivos.
        if num_edicion:
            items = self._enumerar_anuncios(fecha, num_edicion)
            logger.debug(f"BON {fecha} (enumeración edición {num_edicion}): {len(items)} items")
            return items

        logger.debug(f"BON {fecha}: edición no encontrada en índice")
        return []

    def _buscar_en_indice(self, fecha: str):
        """
        Busca en el indice de BON la edicion y los anuncios para 'fecha'.
        Estrategia: parsear el script tag JSON/toString incrustado en el HTML
        (el indice es JS-rendered pero los datos estan en un <script> de 400K).

        Devuelve:
          (items_relevantes, None)  si pudo extraer datos del script
          ([], None)                si no hay datos (dia sin publicacion)
        La enumeracion individual queda como fallback externo.
        """
        dt        = datetime.strptime(fecha, "%Y%m%d")
        fecha_iso = "{}-{:02d}-{:02d}".format(dt.year, dt.month, dt.day)

        urls_indice = [
            self.URL_INDICE + "?mes={}&anio={}".format(dt.month, dt.year),
            self.URL_INDICE,
            self.URL_INDICE + "?anio={}&mes={:02d}".format(dt.year, dt.month),
        ]

        for url_idx in urls_indice:
            try:
                r = self.s.get(url_idx, timeout=25)
                if r.status_code != 200:
                    continue
                enc  = r.encoding or "utf-8"
                html = r.content.decode(enc, errors="replace")

                if fecha_iso not in html:
                    logger.debug("BON indice %s: %s no aparece", url_idx, fecha_iso)
                    continue

                soup = BeautifulSoup(html, "lxml")

                for script in soup.find_all("script"):
                    content = script.string or ""
                    if fecha_iso not in content:
                        continue

                    # ── A. Extraer numero de edicion del JSON de calendario ──────
                    # Formato: "2026-05-07":[{"boletinId":"2026.88","extraordinario":null,"numero":88}]
                    m_ed = re.search(
                        r'"' + re.escape(fecha_iso) + r'":\[{"boletinId":"[^"]+","extraordinario":[^,]+,"numero":(\d+)}',
                        content
                    )
                    if not m_ed:
                        continue
                    num_edicion = m_ed.group(1)
                    logger.debug("BON indice: edicion %s -> nº %s", fecha, num_edicion)

                    # ── B. Extraer titulos de anuncios del toString Java ──────────
                    # Formato: anuncioId=2026.88.N, titulo=TITULO, organoSolicitante=
                    pat = re.compile(
                        r"anuncioId=" + str(dt.year) + r"\." + num_edicion +
                        r"\.(\d+),\s*titulo=(.*?),\s*organoSolicitante="
                    )
                    items = []
                    seen  = set()
                    for am in pat.finditer(content):
                        item_num = am.group(1)
                        titulo   = am.group(2).strip()
                        if not titulo or item_num in seen:
                            continue
                        seen.add(item_num)
                        url_item = "{}/es/anuncio/-/texto/{}/{}/{}".format(
                            self.BASE, dt.year, num_edicion, item_num)
                        if es_relevante(titulo):
                            items.append({
                                "boletin": "BON", "ccaa": "Navarra",
                                "id":           "BON-{}-{}-{}".format(dt.year, num_edicion, item_num),
                                "fecha":        fecha,
                                "departamento": "",
                                "titulo":       titulo[:300],
                                "url":          url_item,
                                "url_pdf": "", "url_xml": "", "texto": "",
                            })

                    logger.debug("BON script: %d anuncios parseados, %d relevantes (edicion %s)",
                                 len(seen), len(items), num_edicion)
                    return (items, None)

            except Exception as e:
                logger.debug("BON indice %s: %s", url_idx, e)

        return ([], None)

    def _enumerar_anuncios(self, fecha: str, num_edicion: str) -> list:
        """
        Fallback: enumera /es/anuncio/-/texto/{yyyy}/{num}/{i} desde i=0.
        Solo se usa si _buscar_en_indice no pudo extraer datos del script
        (p.ej. ediciones muy antiguas fuera del rango del indice).
        Para el texto usa 'main' o '#content' que son SSR en BON.
        """
        dt   = datetime.strptime(fecha, "%Y%m%d")
        yyyy = str(dt.year)
        items      = []
        seen       = set()
        fallos     = 0
        MAX_I      = 300
        MAX_FALLOS = 4

        for i in range(0, MAX_I):
            url = "{}/es/anuncio/-/texto/{}/{}/{}".format(self.BASE, yyyy, num_edicion, i)
            try:
                r = self.s.get(url, timeout=15)
                if r.status_code in (404, 410):
                    fallos += 1
                    if fallos >= MAX_FALLOS:
                        break
                    continue
                if r.status_code != 200:
                    fallos += 1
                    if fallos >= MAX_FALLOS:
                        break
                    continue

                enc  = r.encoding or "utf-8"
                html = r.content.decode(enc, errors="replace")
                soup = BeautifulSoup(html, "lxml")

                # main / #content son SSR en BON; el contenido real empieza
                # despues del encabezado "BOLETIN Nº X - fecha".
                txt = ""
                for sel in ["main", "#content", "article"]:
                    el = soup.select_one(sel)
                    if el:
                        txt = el.get_text(" ", strip=True)
                        break
                if len(txt) < 50:
                    txt = soup.get_text(" ", strip=True)

                if len(txt) < 50:
                    fallos += 1
                    if fallos >= MAX_FALLOS:
                        break
                    continue

                fallos = 0

                # Extraer titulo: texto despues de la cabecera de edicion
                titulo = txt
                m_hdr = self.FECHA_PAT.search(txt)
                if m_hdr:
                    titulo = txt[m_hdr.end():].strip()[:400]

                dept = ""
                if url not in seen and es_relevante(titulo[:600]):
                    seen.add(url)
                    items.append({
                        "boletin": "BON", "ccaa": "Navarra",
                        "id":           "BON-{}-{}-{}".format(yyyy, num_edicion, i),
                        "fecha":        fecha,
                        "departamento": dept,
                        "titulo":       titulo[:300],
                        "url":          url,
                        "url_pdf": "", "url_xml": "",
                        "texto": titulo[:4000],
                    })

            except Exception as e:
                logger.debug("BON anuncio %s: %s", url, e)
                fallos += 1
                if fallos >= MAX_FALLOS:
                    break

        return items

    def _extraer_fecha(self, html: str) -> str:
        """Extrae YYYYMMDD del texto 'BOLETÍN Nº N - DD de MES de YYYY'."""
        m = self.FECHA_PAT.search(html)
        if not m:
            return ""
        dia  = m.group(1).zfill(2)
        mes  = self.MESES.get(m.group(2).lower(), "")
        anyo = m.group(3)
        return f"{anyo}{mes}{dia}" if mes else ""

    def _parse(self, html: str, fecha: str) -> list:
        soup  = BeautifulSoup(html, "lxml")
        items = []
        seen  = set()

        for a in soup.find_all("a", href=self.ANUNCIO_PAT):
            href     = a.get("href", "")
            url_item = href if href.startswith("http") else self.BASE + href
            if url_item in seen:
                continue

            # Texto del item: preferir el contenedor inmediato con suficiente contenido
            txt  = ""
            parent = a.find_parent(["li", "p", "div", "td", "article"])
            if parent:
                txt = parent.get_text(" ", strip=True)
            if len(txt) < 25:
                txt = a.get_text(" ", strip=True)
            if len(txt) < 25:
                continue

            # Departamento: heading de sección más cercano
            dept = ""
            for anc in (parent.parents if parent else []):
                h = anc.find(["h2","h3","h4","h5"], recursive=False)
                if h:
                    dept = h.get_text(" ", strip=True)
                    break

            seen.add(url_item)
            if not es_relevante(txt, departamento=dept):
                continue

            item_id = "BON-" + href.replace("/es/anuncio/-/texto/","").replace("/","-")
            items.append({
                "boletin": "BON", "ccaa": "Navarra",
                "id":           item_id,
                "fecha":        fecha,
                "departamento": dept,
                "titulo":       txt[:300],
                "url":          url_item,
                "url_pdf":      "",
                "url_xml":      "",
                "texto":        "",
            })

        logger.debug(f"BON _parse {fecha}: {len(items)} items")
        return items

    def get_texto(self, item: dict) -> str:
        url = item.get("url", "")
        if not url:
            return ""
        try:
            r = self.s.get(url, timeout=20)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.content.decode(r.encoding or "utf-8", errors="replace"), "lxml")
            for sel in [".anuncio-contenido", "#contenido", "article", "main"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 100:
                        return t[:8000]
        except Exception as e:
            logger.debug(f"BON texto: {e}")
        return ""


class BOLRScraper:
    """
    BOLR — Boletín Oficial de La Rioja

    URL directa por fecha (confirmada):
      https://web.larioja.org/bor-portada?fecha=YYYY-MM-DD

    Fallback para compatibilidad: Liferay JSON API (ignora filtro de fecha,
    devuelve boletín más reciente; se verifica fecha en _parse).
    """
    BASE_WEB  = "https://web.larioja.org"
    BASE_IAS1 = "https://ias1.larioja.org"

    # URL directa por fecha — primer intento (SSR, sin JS)
    URL_FECHA = "https://web.larioja.org/bor-portada?fecha={yyyy}-{mm}-{dd}"

    # Portales HTML JS-only (último recurso)
    URLS_DIA = [
        "https://web.larioja.org/bor-portada?anio={yyyy}&mes={mm}&dia={dd}",
        "https://ias1.larioja.org/bor/web/bor/buscador-boletines?anio={yyyy}&mes={mm}&dia={dd}",
    ]
    # Fallbacks Liferay (si URL_FECHA falla o devuelve vacío)
    URLS_JSON = [
        ("https://web.larioja.org/bor-portada/bor"
         "?filtros=%7B%22fecha_publicacion%22%3A%22{yyyy}-{mm}-{dd}%22%7D&page=1"),
        "https://web.larioja.org/bor-portada/bor?anio={yyyy}&mes={mm}&dia={dd}&page=1",
        "https://web.larioja.org/bor-portada/bor?page=1",
    ]
    URLS_RSS = [
        "https://web.larioja.org/bor-portada/bor-rss",
        "https://ias1.larioja.org/bor/web/bor/rss",
    ]

    def __init__(self, session):
        self.s = session
        self.s.headers.update({
            "Referer": "https://web.larioja.org/bor-portada",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def get_items(self, fecha: str) -> list:
        dt   = datetime.strptime(fecha, "%Y%m%d")
        yyyy = str(dt.year)
        mm   = f"{dt.month:02d}"
        dd   = f"{dt.day:02d}"

        fecha_iso   = f"{fecha[0:4]}-{fecha[4:6]}-{fecha[6:8]}"
        fecha_slash = f"{fecha[6:8]}/{fecha[4:6]}/{fecha[0:4]}"

        # ── 1. JSON API con cabecera AJAX + filtro de fecha ───────────────────
        # Liferay responde con JSON de items; si el filtro de fecha funciona,
        # el contenido incluirá la fecha solicitada. Si devuelve el BOR actual
        # (filtro ignorado), _parse() lo descartará por fecha.
        ajax_headers = {**self.s.headers,
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/javascript, */*; q=0.01"}
        for url_json_tmpl in self.URLS_JSON:
            url_json = url_json_tmpl.format(yyyy=yyyy, mm=mm, dd=dd)
            try:
                r = self.s.get(url_json, timeout=20, headers=ajax_headers)
                logger.debug(f"BOLR JSON: {r.status_code} {len(r.content)}B ({url_json[-50:]})")
                if r.status_code == 200 and len(r.content) > 5000:
                    resp_tiene_fecha = (fecha_iso in r.text or fecha_slash in r.text)
                    try:
                        data = r.json()
                        if resp_tiene_fecha:
                            items = self._parse_json(data, fecha)
                            if items:
                                return items
                        else:
                            logger.debug(f"BOLR JSON: respuesta no contiene {fecha} "
                                         f"→ BOR actual ≠ BOR solicitado; ignorando")
                    except Exception:
                        pass  # No es JSON puro
                    if resp_tiene_fecha:
                        items = self._parse(r.text, fecha)
                        logger.debug(f"BOLR JSON URL{self.URLS_JSON.index(url_json_tmpl)+1}: "
                                     f"{len(items)} items energéticos para {fecha}")
                        if items:
                            return items
            except Exception as e:
                logger.debug(f"BOLR JSON: {e}")

        # ── 2. RSS (filtra por fecha en el XML) ────────────────────────
        for url_rss in self.URLS_RSS:
            try:
                r = self.s.get(url_rss, timeout=20,
                               headers={"Accept": "application/rss+xml,application/xml,*/*"})
                logger.debug(f"BOLR RSS {url_rss[-40:]}: {r.status_code} {len(r.content)}B")
                if r.status_code == 200 and len(r.content) > 1000:
                    items = self._parse_rss(r.text, fecha)
                    if items:
                        return items
            except Exception as e:
                logger.debug(f"BOLR RSS {url_rss[-30:]}: {e}")

        # ── 3. Portales HTML (JS-only — último recurso) ────────────────
        for url_tmpl in self.URLS_DIA:
            url = url_tmpl.format(yyyy=yyyy, mm=mm, dd=dd)
            try:
                r = self.s.get(url, timeout=25)
                logger.debug(f"BOLR HTML {url[-55:]}: {r.status_code} {len(r.content)}B")
                if r.status_code == 200 and len(r.content) > 5000:
                    items = self._parse(r.text, fecha)
                    if items:
                        logger.debug(f"BOLR: {len(items)} items vía {url[-40:]}")
                        return items
            except Exception as e:
                logger.debug(f"BOLR {url[-40:]}: {e}")

        logger.debug(f"BOLR {fecha}: 0 items energéticos")
        return []

    def _parse_json(self, data, fecha: str) -> list:
        """Intenta extraer items de una respuesta JSON de la API Liferay."""
        items = []
        rows = data if isinstance(data, list) else data.get("items", data.get("data", []))
        for row in rows:
            if not isinstance(row, dict):
                continue
            txt = row.get("titulo", row.get("title", row.get("descripcion", "")))
            url = row.get("url", row.get("link", row.get("enlace", "")))
            if not txt or not url:
                continue
            if not es_relevante(txt):
                continue
            if not url.startswith("http"):
                url = self.BASE_WEB + "/" + url.lstrip("/")
            items.append({
                "boletin": "BOLR", "ccaa": "La Rioja",
                "id":    f"BOLR-{fecha}-{len(items)}",
                "fecha": fecha, "departamento": "",
                "titulo": txt[:300],
                "url":    url, "url_pdf": "", "url_xml": "", "texto": "",
            })
        return items

    def _parse_rss(self, xml_text: str, fecha: str) -> list:
        """Extrae items del RSS del BOR filtrando por fecha y es_relevante."""
        items = []
        try:
            soup = BeautifulSoup(xml_text, "xml")
            for item in soup.find_all("item"):
                pub = item.find("pubDate")
                if pub:
                    # Verificar que el item corresponde a la fecha pedida
                    pub_txt = pub.get_text()
                    # pubDate en RSS suele ser "Wed, 14 May 2026 00:00:00 +0200"
                    try:
                        pub_dt = datetime.strptime(pub_txt[:16].strip(), "%a, %d %b %Y")
                        if pub_dt.strftime("%Y%m%d") != fecha:
                            continue
                    except Exception:
                        pass  # No se puede verificar fecha → incluir igualmente
                title = item.find("title")
                link  = item.find("link")
                if not title or not link:
                    continue
                txt = title.get_text(strip=True)
                url = link.get_text(strip=True)
                if es_relevante(txt):
                    items.append({
                        "boletin": "BOLR", "ccaa": "La Rioja",
                        "id":    f"BOLR-{fecha}-{len(items)}",
                        "fecha": fecha, "departamento": "",
                        "titulo": txt[:300],
                        "url":    url, "url_pdf": "", "url_xml": "", "texto": "",
                    })
        except Exception as e:
            logger.debug(f"BOLR _parse_rss: {e}")
        return items

    def _parse(self, html: str, fecha: str) -> list:
        """
        Parsea el HTML del BOR (JSON API o portal).

        Estructura real de cada item en la JSON API:
          <li>
            <h6>CONSEJERÍA DE ...</h6>
            <p><a href="https://ias1.larioja.org/boletin/Bor_Boletin_visor_Servlet?referencia=...">
               TÍTULO DE LA DISPOSICIÓN</a></p>
            <p>BOR nº 92 - Fecha: 18/05/2026 -
               <a class="btn" href="/bor-portada/boranuncio?n=anu-NNNNN">html</a></p>
          </li>

        IMPORTANTE: la JSON API puede devolver el boletín más reciente aunque se
        solicite una fecha histórica. Se descarta cualquier item cuya fecha no coincida.
        """
        soup  = BeautifulSoup(html, "lxml")
        items = []
        seen  = set()

        VISOR_PAT = re.compile(r"Bor_Boletin_visor_Servlet|boletin.*referencia", re.I)
        FECHA_PAT = re.compile(r"Fecha:\s*(\d{2})/(\d{2})/(\d{4})", re.I)

        # ── Estructura principal: <li> con visor_Servlet + boranuncio ──
        for li in soup.find_all("li"):
            a_visor = li.find("a", href=VISOR_PAT)
            if not a_visor:
                continue

            # Verificar fecha del item antes de procesar
            li_text  = li.get_text(" ", strip=True)
            m_fecha  = FECHA_PAT.search(li_text)
            if m_fecha:
                item_fecha = f"{m_fecha.group(3)}{m_fecha.group(2)}{m_fecha.group(1)}"
                if item_fecha != fecha:
                    continue  # Descartar items de otra fecha
            else:
                continue  # Sin "Fecha: DD/MM/YYYY" verificable → descartar

            titulo  = a_visor.get_text(" ", strip=True)
            url_pdf = a_visor["href"]
            if not url_pdf.startswith("http"):
                url_pdf = self.BASE_IAS1 + "/" + url_pdf.lstrip("/")
            if url_pdf in seen or len(titulo) < 15:
                continue

            # Departamento desde <h6>
            h6   = li.find("h6")
            dept = h6.get_text(" ", strip=True) if h6 else ""

            # Link al visor HTML
            a_html   = li.find("a", href=lambda h: h and "boranuncio" in h)
            url_html = ""
            item_id  = f"BOLR-{fecha}-{len(items)}"
            if a_html:
                href = a_html["href"]
                url_html = href if href.startswith("http") else self.BASE_WEB + href
                item_id  = "BOLR-" + a_html["href"].split("n=")[-1].split("&")[0]

            seen.add(url_pdf)
            if not es_relevante(titulo, departamento=dept):
                continue

            items.append({
                "boletin": "BOLR", "ccaa": "La Rioja",
                "id":           item_id,
                "fecha":        fecha,
                "departamento": dept,
                "titulo":       titulo[:300],
                "url":          url_html or url_pdf,
                "url_pdf":      url_pdf,
                "url_xml":      "",
                "texto":        "",
            })

        # ── Fallback: visor_Servlet en cualquier contexto ──────────────
        if not items:
            for a in soup.find_all("a", href=VISOR_PAT):
                url_pdf = a["href"]
                if not url_pdf.startswith("http"):
                    url_pdf = self.BASE_IAS1 + "/" + url_pdf.lstrip("/")
                if url_pdf in seen:
                    continue
                titulo = a.get_text(" ", strip=True)
                parent = a.find_parent(["li", "p", "div", "td"])
                if len(titulo) < 15 and parent:
                    titulo = parent.get_text(" ", strip=True)[:300]
                if len(titulo) < 15:
                    continue
                # Verificar fecha en el contexto
                if parent:
                    m = FECHA_PAT.search(parent.get_text())
                    if m:
                        if f"{m.group(3)}{m.group(2)}{m.group(1)}" != fecha:
                            continue
                seen.add(url_pdf)
                dept = ""
                if parent:
                    h6 = parent.find("h6")
                    dept = h6.get_text(" ", strip=True) if h6 else ""
                if not es_relevante(titulo, departamento=dept):
                    continue
                items.append({
                    "boletin": "BOLR", "ccaa": "La Rioja",
                    "id":    f"BOLR-{fecha}-{len(items)}",
                    "fecha": fecha, "departamento": dept,
                    "titulo": titulo[:300],
                    "url":    url_pdf, "url_pdf": url_pdf, "url_xml": "", "texto": "",
                })

        logger.debug(f"BOLR {fecha}: {len(items)} items energéticos")
        return items

    def get_texto(self, item: dict) -> str:
        url = item.get("url","")
        if not url:
            return ""
        try:
            r = self.s.get(url, timeout=20)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text,"lxml")
            for sel in ["#content-inner",".item-page","article","main"]:
                el = soup.select_one(sel)
                if el:
                    t = el.get_text(" ", strip=True)
                    if len(t) > 200:
                        return t[:8000]
        except Exception as e:
            logger.debug(f"BOLR texto: {e}")
        return ""

# ─── ORQUESTADOR PRINCIPAL ───────────────────────────────────────────────────
class MultiBoletinScraper:
    SCRAPERS = {
        "BOE":   BOEScraper,
        "BOCM":  BOCMScraper,
        "BOCyL": BOCyLScraper,
        "DOCM":  DOCMScraper,
        "BOJA":  BOJAScraper,
        "DOGV":  DOGVScraper,
        "DOGC":  DOGCScraper,
        "DOG":   lambda s: GenericHTMLScraper(s, "DOG"),
        "BOPA":  lambda s: GenericHTMLScraper(s, "BOPA"),
        "BOC":   lambda s: GenericHTMLScraper(s, "BOC"),
        "BORM":  lambda s: GenericHTMLScraper(s, "BORM"),  # Anti-bot Radware — 0 items esperado
        # ── Nuevas CCAA ──────────────────────────────────────────────────────
        "BOA":   BOAScraper,       # Aragón
        "BOPV":  BOPVScraper,      # País Vasco
        "DOE":   DOEScraper,       # Extremadura
        "BON":   BONScraper,      # Navarra
        "BOLR":  BOLRScraper,     # La Rioja
    }

    def __init__(self, output_dir: str = "data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "es-ES,es;q=0.9",
        })

    def scrape_dia(self, fecha: str = None, boletines: list = None) -> list:
        if not fecha:
            fecha = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        # Scrapers estándar (requests)
        scrapers_activos = {
            k: v(self.session)
            for k, v in self.SCRAPERS.items()
            if not boletines or k in boletines
        }

        # Scrapers Playwright (JS dinámico) — si están disponibles y solicitados
        playwright_scrapers = {}
        BOLETINES_PW = set()  # BOJA y BOPA usan requests directos
        boletines_pw_solicitados = (
            set(boletines or []) & BOLETINES_PW
            if boletines else set()
        )
        if boletines_pw_solicitados:
            try:
                from scrapers.playwright_scraper import get_playwright_scraper, PLAYWRIGHT_DISPONIBLE
                if PLAYWRIGHT_DISPONIBLE:
                    for nombre in boletines_pw_solicitados:
                        scraper_pw = get_playwright_scraper(nombre)
                        scraper_pw = get_playwright_scraper(nombre)
                        if scraper_pw:
                            playwright_scrapers[nombre] = scraper_pw
                            logger.info(f"  {nombre}: usando Playwright (JS completo)")
                else:
                    logger.warning("Playwright no instalado. Para BOJA/DOGC/DOGV: "
                                  "pip install playwright && playwright install chromium")
            except ImportError:
                logger.debug("playwright_scraper.py no encontrado")

        todos = []

        # Ejecutar scrapers estándar
        for nombre, scraper in scrapers_activos.items():
            # Si hay versión Playwright para este boletín, usarla en su lugar
            if nombre in playwright_scrapers:
                continue
            logger.info(f"Scraping {nombre} — {fecha}")
            try:
                items = scraper.get_items(fecha)
                if hasattr(scraper, "get_texto"):
                    for item in items:
                        item["texto"] = scraper.get_texto(item)
                        time.sleep(0.5)
                logger.info(f"  {nombre}: {len(items)} items relevantes")
                logger.info(f"  {nombre}: {len(items)} items relevantes")
                todos.extend(items)
            except Exception as e:
                logger.error(f"  {nombre} falló: {e}")
            time.sleep(1)

        # Ejecutar scrapers Playwright (si están disponibles)
        for nombre in [n for n in (boletines or list(scrapers_activos.keys()))
                       if n in playwright_scrapers]:
            logger.info(f"Scraping {nombre} (Playwright) — {fecha}")
            try:
                scraper_pw = playwright_scrapers[nombre]
                items = scraper_pw.get_items(fecha)
                logger.info(f"  {nombre} (Playwright): {len(items)} items relevantes")
                todos.extend(items)
            except Exception as e:
                logger.error(f"  {nombre} (Playwright) falló: {e}")
            time.sleep(1)

        # Deduplicar por ID/URL
        seen_ids: set = set()
        unique: list = []
        for item in todos:
            key = item.get("id") or item.get("url", "")
            if key not in seen_ids:
                seen_ids.add(key)
                unique.append(item)
        todos = unique

        # Guardar raw (sobreescribe si ya existe — permite re-runs parciales)
        out_path = self.output_dir / f"energy_raw_{fecha}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"fecha": fecha, "total": len(todos), "items": todos},
                      f, ensure_ascii=False, indent=2)
        logger.info(f"Guardado: {out_path}  ({len(todos)} items)")
        return todos
