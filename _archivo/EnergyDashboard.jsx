import { useState, useMemo } from "react";

// ─── TAXONOMÍAS (espejo exacto del extractor Python) ──────────────────────────
const TIPOS_PERMISO = {
  EsIA:"Estudio de Impacto Ambiental", DIA:"Declaración de Impacto Ambiental",
  AAI:"Autorización Ambiental Integrada", AAU:"Autorización Ambiental Unificada",
  IPA:"Información Pública Ambiental", IP:"Información Pública (energética)",
  AAP:"Autorización Administrativa Previa", AAC:"Autorización Administrativa de Construcción",
  AAE:"Autorización Administrativa de Explotación", AAP_AAC:"AAP + AAC (conjunta)",
  ModAAP:"Modificación de AAP", ModAAC:"Modificación de AAC", ModAAE:"Modificación de AAE",
  DUP:"Declaración de Utilidad Pública", LAP:"Levantamiento de Actas Previas",
  Servidumbre:"Servidumbre de Paso", OcupacionUP:"Ocupación definitiva / Acta Replanteo",
  PtoConexion:"Punto de Conexión / Acceso y Conexión", ModConexion:"Modificación Pto. Conexión",
  InscReg:"Inscripción en Registro", BajReg:"Baja en Registro",
  PlanEsp:"Plan Especial Urbanístico", LicObras:"Licencia de Obras",
  Concesion:"Concesión Dominio Público", Otro:"Otro",
};

const TIPO_GRUPO = {
  Ambiental:   ["EsIA","DIA","AAI","AAU","IPA"],
  Energético:  ["IP","AAP","AAC","AAE","AAP_AAC","ModAAP","ModAAC","ModAAE"],
  "UP/Serv.":  ["DUP","LAP","Servidumbre","OcupacionUP"],
  Conexión:    ["PtoConexion","ModConexion"],
  Registro:    ["InscReg","BajReg"],
  Urbanismo:   ["PlanEsp","LicObras"],
  Otros:       ["Concesion","Otro"],
};

const ESTADOS = {
  favorable:           { label:"Favorable",            color:"#22c55e", bg:"#0d2010", grupo:"positivo",  libera:false, fallido:false },
  otorgado:            { label:"Otorgado",              color:"#4ade80", bg:"#0a1a0d", grupo:"positivo",  libera:false, fallido:false },
  no_necesario:        { label:"No Necesario",          color:"#86efac", bg:"#091508", grupo:"positivo",  libera:false, fallido:false },
  informacion_publica: { label:"Inf. Pública",          color:"#38bdf8", bg:"#0c1a2a", grupo:"proceso",   libera:false, fallido:false },
  en_tramitacion:      { label:"En Tramitación",        color:"#7dd3fc", bg:"#0a1520", grupo:"proceso",   libera:false, fallido:false },
  suspendido:          { label:"Suspendido",            color:"#fcd34d", bg:"#1f1a00", grupo:"proceso",   libera:false, fallido:false },
  desfavorable:        { label:"Desfavorable",          color:"#f87171", bg:"#2d0a0a", grupo:"fallido",   libera:true,  fallido:true  },
  denegado:            { label:"Denegado",              color:"#ef4444", bg:"#2d0808", grupo:"fallido",   libera:true,  fallido:true  },
  desistido:           { label:"Desistido",             color:"#fb923c", bg:"#2d1000", grupo:"fallido",   libera:true,  fallido:true  },
  caducado:            { label:"Caducado",              color:"#fbbf24", bg:"#261800", grupo:"fallido",   libera:true,  fallido:true  },
  archivado:           { label:"Archivado",             color:"#f59e0b", bg:"#221500", grupo:"fallido",   libera:true,  fallido:true  },
  revocado:            { label:"Revocado / Anulado",    color:"#e879f9", bg:"#200d26", grupo:"fallido",   libera:true,  fallido:true  },
  inadmitido:          { label:"Inadmitido a trámite",  color:"#c084fc", bg:"#180d26", grupo:"fallido",   libera:true,  fallido:true  },
  otro:                { label:"Otro",                  color:"#6b7280", bg:"#111",    grupo:"otro",      libera:false, fallido:false },
};

const TECH_ICONS = {
  eólica:"🌀", fotovoltaica:"☀️", BESS:"🔋", H2:"⚗️", "Data Center":"🖥️",
  LAT:"⚡", SET:"🔌", "FV+BESS":"☀️🔋", "eólica+BESS":"🌀🔋",
  termosolar:"🌡️", hidráulica:"💧", biomasa:"🌿", cogeneración:"♻️", otro:"📄",
};

const BOLETIN_COLOR = { BOE:"#3b82f6", DOGC:"#f59e0b", BOCM:"#a855f7", BOJA:"#22c55e", BOCyL:"#f97316" };

// ─── DATOS DEMO ───────────────────────────────────────────────────────────────
const DEMO = [
  { id:"BOE-A-2024-8821", boletin:"BOE", fecha_publicacion:"20240415", url:"https://www.boe.es",
    titulo_original:"Resolución DGPEM — caducidad AAP parque eólico 'Serra del Vent' IN/2021/00234",
    datos:{ nombre_proyecto:"Parque Eólico Serra del Vent", numero_expediente_industria:"IN/2021/00234", numero_expediente_medioambiente:null, promotor:"Renovables del Mediterráneo S.L.", tecnologia:"eólica", potencia_mw:48, tipo_permiso:"AAP", permisos_adicionales:[], estado_permiso:"caducado", es_proyecto_fallido:true, motivo_fallo:"Incumplimiento de plazo de inicio de construcción", subestacion_conexion:"SET Amposta", tension_conexion_kv:220, gestor_red:"REE", municipio:"Amposta", provincia:"Tarragona", comunidad_autonoma:"Catalunya", fecha_resolucion:"2024-04-10", capacidad_mw_liberada:48, observaciones:null, confianza:0.94 }},
  { id:"BOJA-2024-1123", boletin:"BOJA", fecha_publicacion:"20240414", url:"https://www.juntadeandalucia.es",
    titulo_original:"Resolución Consejería Industria — deniega AAP planta fotovoltaica 'Las Marismas FV-1'",
    datos:{ nombre_proyecto:"Las Marismas FV-1", numero_expediente_industria:"AT-SE-2022/00891", numero_expediente_medioambiente:"2022/EAE/0234", promotor:"Solar Invest Iberia S.A.", tecnologia:"fotovoltaica", potencia_mw:150, tipo_permiso:"AAP", permisos_adicionales:["DIA"], estado_permiso:"desfavorable", es_proyecto_fallido:true, motivo_fallo:"DIA desfavorable por afección a ZEPA — avifauna esteparia", subestacion_conexion:"SET Las Cabezas", tension_conexion_kv:132, gestor_red:"Endesa Red", municipio:"Las Cabezas de San Juan", provincia:"Sevilla", comunidad_autonoma:"Andalucía", fecha_resolucion:"2024-04-08", capacidad_mw_liberada:150, observaciones:null, confianza:0.97 }},
  { id:"BOCyL-2024-445", boletin:"BOCyL", fecha_publicacion:"20240415", url:"https://bocyl.jcyl.es",
    titulo_original:"Resolución — otorga AAC parque eólico 'Vientos de la Meseta', Soria",
    datos:{ nombre_proyecto:"Vientos de la Meseta", numero_expediente_industria:"BU-AT-2022/00156", numero_expediente_medioambiente:null, promotor:"Eólica Castellana S.A.U.", tecnologia:"eólica", potencia_mw:72, tipo_permiso:"AAC", permisos_adicionales:[], estado_permiso:"otorgado", es_proyecto_fallido:false, motivo_fallo:null, subestacion_conexion:"SET Soria Norte", tension_conexion_kv:220, gestor_red:"REE", municipio:"Golmayo", provincia:"Soria", comunidad_autonoma:"Castilla y León", fecha_resolucion:"2024-04-05", capacidad_mw_liberada:null, observaciones:null, confianza:0.92 }},
  { id:"BOE-A-2024-9102", boletin:"BOE", fecha_publicacion:"20240415", url:"https://www.boe.es",
    titulo_original:"Resolución — formula DIA de 'Extremadura Solar Hub' FV+BESS",
    datos:{ nombre_proyecto:"Extremadura Solar Hub", numero_expediente_industria:"CC-AT-2021/00089", numero_expediente_medioambiente:"2021/EIA/0567", promotor:"GreenPower Extremadura S.L.", tecnologia:"FV+BESS", potencia_mw:300, tipo_permiso:"DIA", permisos_adicionales:["AAP"], estado_permiso:"favorable", es_proyecto_fallido:false, motivo_fallo:null, subestacion_conexion:"SET Trujillo", tension_conexion_kv:400, gestor_red:"REE", municipio:"Trujillo", provincia:"Cáceres", comunidad_autonoma:"Extremadura", fecha_resolucion:"2024-04-12", capacidad_mw_liberada:null, observaciones:"BESS 150 MWh. DIA con condicionado.", confianza:0.96 }},
  { id:"BOE-A-2024-9250", boletin:"BOE", fecha_publicacion:"20240415", url:"https://www.boe.es",
    titulo_original:"Resolución — acepta desistimiento AAP 'H2 Castellón Hub'",
    datos:{ nombre_proyecto:"H2 Castellón Hub", numero_expediente_industria:"CS-AT-2022/00312", numero_expediente_medioambiente:"2022/EAE/0441", promotor:"Hydrogen Levante S.L.", tecnologia:"H2", potencia_mw:80, tipo_permiso:"AAP", permisos_adicionales:[], estado_permiso:"desistido", es_proyecto_fallido:true, motivo_fallo:"Inviabilidad económica — coste de electrolizadores fuera de rango de mercado", subestacion_conexion:"SET Castellón Norte", tension_conexion_kv:132, gestor_red:"Iberdrola Distribución", municipio:"Castellón de la Plana", provincia:"Castellón", comunidad_autonoma:"C. Valenciana", fecha_resolucion:"2024-04-11", capacidad_mw_liberada:80, observaciones:null, confianza:0.91 }},
  { id:"DOGC-2024-887", boletin:"DOGC", fecha_publicacion:"20240413", url:"https://dogc.gencat.cat",
    titulo_original:"Resolució — atorga AAP i AAC planta fotovoltaica 'Solell de Lleida'",
    datos:{ nombre_proyecto:"Solell de Lleida", numero_expediente_industria:"IN/2022/00567", numero_expediente_medioambiente:null, promotor:"Energia Solar Catalana S.L.", tecnologia:"fotovoltaica", potencia_mw:55, tipo_permiso:"AAP_AAC", permisos_adicionales:[], estado_permiso:"otorgado", es_proyecto_fallido:false, motivo_fallo:null, subestacion_conexion:"SET Lleida Oest", tension_conexion_kv:132, gestor_red:"Endesa Red", municipio:"Lleida", provincia:"Lleida", comunidad_autonoma:"Catalunya", fecha_resolucion:"2024-04-08", capacidad_mw_liberada:null, observaciones:null, confianza:0.89 }},
  { id:"BOCM-2024-334", boletin:"BOCM", fecha_publicacion:"20240415", url:"https://www.bocm.es",
    titulo_original:"Resolución — otorga AAE centro de datos 'MadridDC-4', Alcobendas",
    datos:{ nombre_proyecto:"MadridDC-4", numero_expediente_industria:"M-AT-2023/00089", numero_expediente_medioambiente:null, promotor:"DataCenter Iberia S.A.", tecnologia:"Data Center", potencia_mw:120, tipo_permiso:"AAE", permisos_adicionales:["PtoConexion"], estado_permiso:"otorgado", es_proyecto_fallido:false, motivo_fallo:null, subestacion_conexion:"SET Alcobendas", tension_conexion_kv:220, gestor_red:"UFD", municipio:"Alcobendas", provincia:"Madrid", comunidad_autonoma:"Madrid", fecha_resolucion:"2024-04-09", capacidad_mw_liberada:null, observaciones:"120 MW en 2 etapas.", confianza:0.93 }},
  { id:"BOE-A-2024-9400", boletin:"BOE", fecha_publicacion:"20240416", url:"https://www.boe.es",
    titulo_original:"Anuncio — Información Pública AAP y EsIA parque eólico 'Sierra Morena III', Córdoba",
    datos:{ nombre_proyecto:"Sierra Morena III", numero_expediente_industria:"CO-AT-2024/00045", numero_expediente_medioambiente:"2024/EsIA/0089", promotor:"Renovalia Energy S.L.", tecnologia:"eólica", potencia_mw:90, tipo_permiso:"IP", permisos_adicionales:["EsIA"], estado_permiso:"informacion_publica", es_proyecto_fallido:false, motivo_fallo:null, subestacion_conexion:"SET Pozoblanco", tension_conexion_kv:220, gestor_red:"REE", municipio:"Villanueva de Córdoba", provincia:"Córdoba", comunidad_autonoma:"Andalucía", fecha_resolucion:"2024-04-16", capacidad_mw_liberada:null, observaciones:"Plazo IP: 30 días hábiles.", confianza:0.88 }},
  { id:"BOCyL-2024-501", boletin:"BOCyL", fecha_publicacion:"20240414", url:"https://bocyl.jcyl.es",
    titulo_original:"Resolución — DUP y LAP línea evacuación 400kV 'LAT Soria–Tudela'",
    datos:{ nombre_proyecto:"LAT Soria–Tudela 400kV", numero_expediente_industria:"SO-AT-2021/00078", numero_expediente_medioambiente:null, promotor:"Red Eléctrica de España S.A.", tecnologia:"LAT", potencia_mw:null, tipo_permiso:"DUP", permisos_adicionales:["LAP"], estado_permiso:"otorgado", es_proyecto_fallido:false, motivo_fallo:null, subestacion_conexion:"SET Soria Norte / SET Tudela", tension_conexion_kv:400, gestor_red:"REE", municipio:"Varios", provincia:"Soria / Navarra", comunidad_autonoma:"Castilla y León / Navarra", fecha_resolucion:"2024-04-10", capacidad_mw_liberada:null, observaciones:"LAP programadas semana 20.", confianza:0.95 }},
  { id:"BOE-A-2024-9501", boletin:"BOE", fecha_publicacion:"20240416", url:"https://www.boe.es",
    titulo_original:"Resolución — inadmite a trámite AAP planta BESS 'Almacén Aragón I' por documentación incompleta",
    datos:{ nombre_proyecto:"Almacén Aragón I", numero_expediente_industria:"Z-AT-2023/00234", numero_expediente_medioambiente:null, promotor:"Storage Solutions Iberia S.L.", tecnologia:"BESS", potencia_mw:50, tipo_permiso:"AAP", permisos_adicionales:[], estado_permiso:"inadmitido", es_proyecto_fallido:true, motivo_fallo:"Documentación técnica incompleta — falta estudio de impacto sobre la red", subestacion_conexion:"SET Zaragoza Sur", tension_conexion_kv:132, gestor_red:"Iberdrola Distribución", municipio:"Cuarte de Huerva", provincia:"Zaragoza", comunidad_autonoma:"Aragón", fecha_resolucion:"2024-04-14", capacidad_mw_liberada:50, observaciones:"Promotor puede subsanar y reiniciar expediente.", confianza:0.90 }},
  { id:"BOJA-2024-1200", boletin:"BOJA", fecha_publicacion:"20240416", url:"https://www.juntadeandalucia.es",
    titulo_original:"Resolución — archiva expediente FV 'Doñana Solar' por silencio del promotor",
    datos:{ nombre_proyecto:"Doñana Solar", numero_expediente_industria:"HU-AT-2020/00456", numero_expediente_medioambiente:"2020/EAE/0122", promotor:"Huelva Fotovoltaica S.L.", tecnologia:"fotovoltaica", potencia_mw:200, tipo_permiso:"AAP", permisos_adicionales:["DIA"], estado_permiso:"archivado", es_proyecto_fallido:true, motivo_fallo:"Silencio administrativo del promotor. No subsanó deficiencias en plazo de 3 meses.", subestacion_conexion:"SET Huelva Norte", tension_conexion_kv:220, gestor_red:"REE", municipio:"Almonte", provincia:"Huelva", comunidad_autonoma:"Andalucía", fecha_resolucion:"2024-04-13", capacidad_mw_liberada:200, observaciones:null, confianza:0.93 }},
  { id:"BOE-A-2024-9600", boletin:"BOE", fecha_publicacion:"20240416", url:"https://www.boe.es",
    titulo_original:"Resolución — DIA no necesaria parque eólico 'Tramontana Wind I' por potencia < umbral",
    datos:{ nombre_proyecto:"Tramontana Wind I", numero_expediente_industria:"GI-AT-2023/00189", numero_expediente_medioambiente:"2023/EsIA/0234", promotor:"Eólica Mediterránea S.A.", tecnologia:"eólica", potencia_mw:38, tipo_permiso:"DIA", permisos_adicionales:[], estado_permiso:"no_necesario", es_proyecto_fallido:false, motivo_fallo:null, subestacion_conexion:"SET Roses", tension_conexion_kv:132, gestor_red:"Endesa Red", municipio:"Roses", provincia:"Girona", comunidad_autonoma:"Catalunya", fecha_resolucion:"2024-04-15", capacidad_mw_liberada:null, observaciones:"Potencia < 50 MW en zona no sensible. Resolución: DIA no exigible.", confianza:0.92 }},
  { id:"BOCyL-2024-600", boletin:"BOCyL", fecha_publicacion:"20240416", url:"https://bocyl.jcyl.es",
    titulo_original:"Resolución — revoca AAE eólico 'Picos del Duero' por irregularidades en la puesta en marcha",
    datos:{ nombre_proyecto:"Picos del Duero", numero_expediente_industria:"ZA-AT-2019/00067", numero_expediente_medioambiente:null, promotor:"Energías Duero S.L.", tecnologia:"eólica", potencia_mw:64, tipo_permiso:"AAE", permisos_adicionales:[], estado_permiso:"revocado", es_proyecto_fallido:true, motivo_fallo:"Irregularidades detectadas en las pruebas de puesta en marcha. Incumplimiento condicionado AAE.", subestacion_conexion:"SET Zamora Este", tension_conexion_kv:132, gestor_red:"Iberdrola Distribución", municipio:"Fermoselle", provincia:"Zamora", comunidad_autonoma:"Castilla y León", fecha_resolucion:"2024-04-12", capacidad_mw_liberada:64, observaciones:"Proyecto paralizado. Promotor ha interpuesto recurso de alzada.", confianza:0.94 }},
];

// ─── UTILS ────────────────────────────────────────────────────────────────────
const fmt = f => f ? `${f.slice(6,8)}/${f.slice(4,6)}/${f.slice(0,4)}` : "—";
const fmw = mw => mw!=null ? `${mw} MW` : "—";
const E   = k  => ESTADOS[k]||ESTADOS.otro;

function Badge({ text, color, bg, sz=10 }) {
  return <span style={{ padding:"2px 7px", borderRadius:3, fontSize:sz, fontWeight:700, color, background:bg, letterSpacing:"0.06em", fontFamily:"monospace", textTransform:"uppercase", whiteSpace:"nowrap" }}>{text}</span>;
}

function Sel({ label, opts, val, set }) {
  return (
    <div style={{ display:"flex", gap:5, alignItems:"center" }}>
      <span style={{ fontSize:9, color:"#374151", letterSpacing:"0.1em" }}>{label}:</span>
      <select value={val} onChange={e=>set(e.target.value)} style={{ background:"#0d0d0d", border:"1px solid #1f1f1f", borderRadius:3, color:"#94a3b8", padding:"3px 8px", fontSize:11, outline:"none", fontFamily:"monospace", cursor:"pointer" }}>
        {opts.map(o=><option key={o} value={o}>{o==="todos"?"Todos":o}</option>)}
      </select>
    </div>
  );
}

function exportCSV(rows) {
  const cols = ["boletin","fecha_publicacion","nombre_proyecto","promotor","tecnologia","potencia_mw","tipo_permiso","permisos_adicionales","estado_permiso","es_proyecto_fallido","motivo_fallo","subestacion_conexion","tension_conexion_kv","gestor_red","provincia","comunidad_autonoma","numero_expediente_industria","numero_expediente_medioambiente","capacidad_mw_liberada","confianza","url"];
  const hdr = cols.join(";");
  const body = rows.map(r=>{
    const d=r.datos||{};
    return cols.map(c=>{
      let v=["boletin","fecha_publicacion","url"].includes(c)?r[c]:d[c];
      if(Array.isArray(v))v=v.join("|");
      return `"${String(v??'').replace(/"/g,'""')}"`;
    }).join(";");
  }).join("\n");
  const blob=new Blob(["\uFEFF"+hdr+"\n"+body],{type:"text/csv;charset=utf-8;"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`permisos_${Date.now()}.csv`;a.click();
}

// ─── PANEL SUBESTACIONES ──────────────────────────────────────────────────────
function SetPanel({ items }) {
  const sets={};
  items.forEach(r=>{
    if(!r.datos?.capacidad_mw_liberada)return;
    const s=r.datos.subestacion_conexion||"SET desconocida";
    if(!sets[s])sets[s]={mw:0,proyectos:[],gestor:r.datos.gestor_red||"?"};
    sets[s].mw+=r.datos.capacidad_mw_liberada;
    sets[s].proyectos.push(r.datos.nombre_proyecto||"?");
  });
  const entries=Object.entries(sets).sort((a,b)=>b[1].mw-a[1].mw);
  if(!entries.length)return null;
  const max=entries[0][1].mw;
  return (
    <div style={{ background:"#0a0a0a", border:"1px solid #1f1f1f", borderRadius:6, padding:14, marginBottom:12 }}>
      <div style={{ fontSize:9, color:"#6b7280", letterSpacing:"0.12em", marginBottom:10, textTransform:"uppercase" }}>⚡ Capacidad potencialmente liberada por subestación</div>
      {entries.map(([s,d])=>(
        <div key={s} style={{ display:"flex", alignItems:"center", gap:10, marginBottom:7 }}>
          <div style={{ minWidth:220 }}>
            <div style={{ fontSize:12, color:"#e2e8f0", fontFamily:"monospace" }}>{s}</div>
            <div style={{ fontSize:9, color:"#374151" }}>{d.gestor} · {d.proyectos.length} proyecto{d.proyectos.length>1?"s":""}</div>
          </div>
          <div style={{ flex:1, height:5, background:"#1a1a1a", borderRadius:3, overflow:"hidden" }}>
            <div style={{ height:"100%", borderRadius:3, width:`${(d.mw/max)*100}%`, background:"linear-gradient(90deg,#c2410c,#f97316)" }} />
          </div>
          <span style={{ fontSize:13, fontWeight:900, color:"#f97316", fontFamily:"monospace", minWidth:72, textAlign:"right" }}>{d.mw} MW</span>
        </div>
      ))}
    </div>
  );
}

// ─── TABLA MAESTRA ────────────────────────────────────────────────────────────
function Tabla({ rows, onSelect }) {
  return (
    <div style={{ overflowX:"auto", border:"1px solid #111", borderRadius:6 }}>
      <table style={{ width:"100%", borderCollapse:"collapse", minWidth:1060 }}>
        <thead>
          <tr style={{ borderBottom:"1px solid #1a1a1a" }}>
            {["Boletín","Fecha","Proyecto / Promotor","Tech","MW","Tipo permiso","Adicionales","Estado","Subestación","Provincia","Lib.MW"].map(h=>(
              <th key={h} style={{ padding:"7px 9px", textAlign:"left", fontSize:9, color:"#374151", letterSpacing:"0.1em", textTransform:"uppercase", whiteSpace:"nowrap", background:"#080808", fontWeight:600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length===0
            ? <tr><td colSpan={11} style={{ padding:40, textAlign:"center", color:"#1f2937", fontSize:12 }}>Sin resultados</td></tr>
            : rows.map(r=>{
                const d=r.datos||{};
                const est=E(d.estado_permiso);
                const bc=BOLETIN_COLOR[r.boletin]||"#6b7280";
                const esF=d.es_proyecto_fallido;
                return (
                  <tr key={r.id} onClick={()=>onSelect(r)}
                    style={{ cursor:"pointer", background:esF?"rgba(239,68,68,0.03)":"transparent", borderBottom:"1px solid #0d0d0d", transition:"background 0.12s" }}
                    onMouseEnter={e=>e.currentTarget.style.background=esF?"rgba(239,68,68,0.07)":"#0f0f0f"}
                    onMouseLeave={e=>e.currentTarget.style.background=esF?"rgba(239,68,68,0.03)":"transparent"}
                  >
                    <td style={{ padding:"7px 9px" }}><Badge text={r.boletin} color={bc} bg={bc+"22"} /></td>
                    <td style={{ padding:"7px 9px", fontSize:11, color:"#4b5563", fontFamily:"monospace", whiteSpace:"nowrap" }}>{fmt(r.fecha_publicacion)}</td>
                    <td style={{ padding:"7px 9px" }}>
                      <div style={{ fontSize:12, color:"#f1f5f9", fontWeight:500, maxWidth:220 }}>{d.nombre_proyecto||<em style={{color:"#333"}}>—</em>}</div>
                      <div style={{ fontSize:10, color:"#4b5563" }}>{d.promotor||""}</div>
                    </td>
                    <td style={{ padding:"7px 9px", whiteSpace:"nowrap" }}>
                      <span style={{ fontSize:14 }}>{TECH_ICONS[d.tecnologia]||"📄"}</span>
                      <span style={{ fontSize:10, color:"#94a3b8", marginLeft:4 }}>{d.tecnologia||"—"}</span>
                    </td>
                    <td style={{ padding:"7px 9px", fontSize:12, color:"#94a3b8", fontFamily:"monospace", textAlign:"right", whiteSpace:"nowrap" }}>{fmw(d.potencia_mw)}</td>
                    <td style={{ padding:"7px 9px" }}><Badge text={d.tipo_permiso||"?"} color="#94a3b8" bg="#111" sz={9} /></td>
                    <td style={{ padding:"7px 9px" }}>
                      <div style={{ display:"flex", gap:3, flexWrap:"wrap" }}>
                        {(d.permisos_adicionales||[]).map(p=><Badge key={p} text={p} color="#6b7280" bg="#0d0d0d" sz={9} />)}
                      </div>
                    </td>
                    <td style={{ padding:"7px 9px", whiteSpace:"nowrap" }}><Badge text={est.label} color={est.color} bg={est.bg} /></td>
                    <td style={{ padding:"7px 9px" }}>
                      <div style={{ fontSize:11, color:esF?"#f97316":"#475569", fontFamily:"monospace", fontWeight:esF?700:400 }}>{d.subestacion_conexion||"—"}</div>
                      <div style={{ fontSize:9, color:"#2d2d2d" }}>{d.gestor_red||""}{d.tension_conexion_kv?` · ${d.tension_conexion_kv}kV`:""}</div>
                    </td>
                    <td style={{ padding:"7px 9px", fontSize:11, color:"#475569" }}>{d.provincia||"—"}</td>
                    <td style={{ padding:"7px 9px", textAlign:"right" }}>
                      {d.capacidad_mw_liberada!=null
                        ? <span style={{ fontSize:12, fontWeight:900, color:"#f97316", fontFamily:"monospace", background:"#1a0800", padding:"2px 7px", borderRadius:4, border:"1px solid #7c2d12" }}>⚡{d.capacidad_mw_liberada}</span>
                        : <span style={{ color:"#151515", fontSize:11 }}>—</span>}
                    </td>
                  </tr>
                );
              })
          }
        </tbody>
      </table>
    </div>
  );
}

// ─── TARJETA PROYECTO FALLIDO ─────────────────────────────────────────────────
function CardFallido({ r, onSelect }) {
  const d=r.datos||{};
  const est=E(d.estado_permiso);
  const bc=BOLETIN_COLOR[r.boletin]||"#6b7280";
  return (
    <div onClick={()=>onSelect(r)} style={{ background:"#0b0707", border:`1px solid ${est.color}33`, borderRadius:6, padding:"12px 14px", cursor:"pointer", transition:"border-color 0.15s" }}
      onMouseEnter={e=>e.currentTarget.style.borderColor=est.color+"88"}
      onMouseLeave={e=>e.currentTarget.style.borderColor=est.color+"33"}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:8 }}>
        <div style={{ display:"flex", gap:5, flexWrap:"wrap" }}>
          <Badge text={r.boletin} color={bc} bg={bc+"22"} />
          <Badge text={d.tipo_permiso||"?"} color="#6b7280" bg="#111" />
          <Badge text={est.label} color={est.color} bg={est.bg} />
          {(d.permisos_adicionales||[]).map(p=><Badge key={p} text={p} color="#4b5563" bg="#0d0d0d" />)}
        </div>
        {d.capacidad_mw_liberada!=null && (
          <span style={{ fontSize:14, fontWeight:900, color:"#f97316", fontFamily:"monospace", background:"#1a0800", padding:"3px 10px", borderRadius:4, border:"1px solid #7c2d12", flexShrink:0 }}>⚡{d.capacidad_mw_liberada} MW</span>
        )}
      </div>
      <div style={{ fontSize:13, color:"#e2e8f0", fontWeight:600, marginBottom:3 }}>
        <span style={{ marginRight:6 }}>{TECH_ICONS[d.tecnologia]||""}</span>{d.nombre_proyecto||"Sin nombre"}
      </div>
      <div style={{ fontSize:11, color:"#6b7280", marginBottom:7 }}>
        {d.promotor||"Promotor desconocido"} · {d.provincia||"—"}
      </div>
      {d.motivo_fallo && (
        <div style={{ fontSize:11, color:"#9ca3af", background:"#111", borderRadius:4, padding:"5px 9px", borderLeft:`2px solid ${est.color}` }}>{d.motivo_fallo}</div>
      )}
      <div style={{ marginTop:7, fontSize:10, color:"#374151", fontFamily:"monospace" }}>
        {d.subestacion_conexion||"SET desconocida"}{d.tension_conexion_kv?` · ${d.tension_conexion_kv}kV`:""}{d.gestor_red?` · ${d.gestor_red}`:""}
      </div>
    </div>
  );
}

// ─── MODAL DETALLE ────────────────────────────────────────────────────────────
function Modal({ item, onClose }) {
  if(!item)return null;
  const d=item.datos||{};
  const est=E(d.estado_permiso);
  return (
    <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.9)", zIndex:100, display:"flex", alignItems:"center", justifyContent:"center", padding:16 }} onClick={onClose}>
      <div style={{ background:"#0d0d0d", border:"1px solid #1f1f1f", borderRadius:8, width:"100%", maxWidth:700, maxHeight:"88vh", overflow:"auto", boxShadow:"0 30px 80px rgba(0,0,0,0.8)" }} onClick={e=>e.stopPropagation()}>
        <div style={{ padding:"14px 18px", borderBottom:"1px solid #141414", display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
          <div>
            <div style={{ display:"flex", gap:6, flexWrap:"wrap", marginBottom:7 }}>
              <Badge text={item.boletin} color={BOLETIN_COLOR[item.boletin]||"#6b7280"} bg={(BOLETIN_COLOR[item.boletin]||"#6b7280")+"22"} />
              <Badge text={d.tipo_permiso||"?"} color="#94a3b8" bg="#1a1a1a" />
              {(d.permisos_adicionales||[]).map(p=><Badge key={p} text={p} color="#6b7280" bg="#111" />)}
              <Badge text={est.label} color={est.color} bg={est.bg} />
              {d.es_proyecto_fallido && <Badge text="PROYECTO FALLIDO" color="#f97316" bg="#1a0800" />}
            </div>
            <h2 style={{ margin:0, fontSize:15, color:"#f1f5f9", fontWeight:600, lineHeight:1.4 }}>
              <span style={{ marginRight:8 }}>{TECH_ICONS[d.tecnologia]||""}</span>
              {d.nombre_proyecto||item.titulo_original}
            </h2>
          </div>
          <button onClick={onClose} style={{ background:"none", border:"none", color:"#374151", cursor:"pointer", fontSize:20, flexShrink:0 }}>✕</button>
        </div>
        <div style={{ padding:18 }}>
          {d.motivo_fallo && (
            <div style={{ background:"#110800", border:`1px solid ${est.color}44`, borderRadius:5, padding:"10px 12px", marginBottom:14 }}>
              <div style={{ fontSize:9, color:"#6b7280", textTransform:"uppercase", letterSpacing:"0.1em", marginBottom:4 }}>Motivo del fallo / estado</div>
              <div style={{ fontSize:13, color:est.color }}>{d.motivo_fallo}</div>
            </div>
          )}
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:14 }}>
            {[
              ["Promotor", d.promotor],
              ["Tecnología", `${TECH_ICONS[d.tecnologia]||""} ${d.tecnologia||"—"}`],
              ["Potencia", fmw(d.potencia_mw)],
              ["Capacidad liberada", d.capacidad_mw_liberada!=null ? `⚡ ${d.capacidad_mw_liberada} MW` : null],
              ["Tipo de permiso", d.tipo_permiso ? `${d.tipo_permiso} — ${TIPOS_PERMISO[d.tipo_permiso]||""}` : null],
              ["Permisos adicionales", (d.permisos_adicionales||[]).map(p=>`${p} (${TIPOS_PERMISO[p]||""})`).join(", ")||null],
              ["Exp. Industria", d.numero_expediente_industria],
              ["Exp. M. Ambiente", d.numero_expediente_medioambiente],
              ["Subestación", d.subestacion_conexion],
              ["Tensión", d.tension_conexion_kv ? `${d.tension_conexion_kv} kV` : null],
              ["Gestor de red", d.gestor_red],
              ["Municipio", d.municipio],
              ["Provincia", d.provincia],
              ["CCAA", d.comunidad_autonoma],
              ["Fecha resolución", d.fecha_resolucion],
              ["Confianza IA", d.confianza ? `${Math.round(d.confianza*100)}%` : null],
            ].map(([l,v])=>(
              <div key={l}>
                <div style={{ fontSize:9, color:"#374151", textTransform:"uppercase", letterSpacing:"0.1em", marginBottom:3 }}>{l}</div>
                <div style={{ fontSize:13, color:v?(l==="Capacidad liberada"?"#f97316":"#e2e8f0"):"#1f2937", fontStyle:v?"normal":"italic" }}>{v||"—"}</div>
              </div>
            ))}
          </div>
          {d.observaciones && (
            <div style={{ marginTop:14, padding:10, background:"#0d0d0d", borderRadius:4, border:"1px solid #1a1a1a" }}>
              <div style={{ fontSize:9, color:"#374151", textTransform:"uppercase", letterSpacing:"0.1em", marginBottom:4 }}>Observaciones</div>
              <div style={{ fontSize:12, color:"#64748b", lineHeight:1.6 }}>{d.observaciones}</div>
            </div>
          )}
          <div style={{ marginTop:14, display:"flex", gap:8 }}>
            <a href={item.url} target="_blank" rel="noreferrer" style={{ background:"#1e3a8a", border:"1px solid #3b82f6", borderRadius:4, color:"#93c5fd", padding:"6px 14px", fontSize:11, textDecoration:"none", fontFamily:"monospace" }}>→ Ver en boletín oficial</a>
            <span style={{ fontSize:10, color:"#1f2937", alignSelf:"center", fontFamily:"monospace" }}>{item.id}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── APP ──────────────────────────────────────────────────────────────────────
const VISTAS = ["Todos los permisos","Proyectos fallidos","Capacidad liberada"];

export default function App() {
  const [vista, setVista]   = useState("Todos los permisos");
  const [fEst, setFEst]     = useState("todos");
  const [fTipo, setFTipo]   = useState("todos");
  const [fGrupo, setFGrupo] = useState("todos");
  const [fTech, setFTech]   = useState("todos");
  const [fBol, setFBol]     = useState("todos");
  const [q, setQ]           = useState("");
  const [modal, setModal]   = useState(null);

  const fallidos     = useMemo(()=>DEMO.filter(r=>r.datos?.es_proyecto_fallido),[]);
  const conCapacidad = useMemo(()=>DEMO.filter(r=>r.datos?.capacidad_mw_liberada!=null),[]);
  const techs     = useMemo(()=>["todos",...new Set(DEMO.map(r=>r.datos?.tecnologia).filter(Boolean))],[]);
  const boletines = useMemo(()=>["todos",...new Set(DEMO.map(r=>r.boletin))],[]);
  const tipos     = useMemo(()=>["todos",...new Set(DEMO.map(r=>r.datos?.tipo_permiso).filter(Boolean))],[]);
  const grupos    = ["todos",...Object.keys(TIPO_GRUPO)];
  const estadoOpts= ["todos",...Object.keys(ESTADOS)];

  const base = vista==="Proyectos fallidos" ? fallidos : vista==="Capacidad liberada" ? conCapacidad : DEMO;

  const filtrados = useMemo(()=>base.filter(r=>{
    const d=r.datos||{};
    if(fEst!=="todos"&&d.estado_permiso!==fEst)return false;
    if(fTipo!=="todos"&&d.tipo_permiso!==fTipo)return false;
    if(fGrupo!=="todos"&&!(TIPO_GRUPO[fGrupo]||[]).includes(d.tipo_permiso))return false;
    if(fTech!=="todos"&&d.tecnologia!==fTech)return false;
    if(fBol!=="todos"&&r.boletin!==fBol)return false;
    if(q){const hay=[d.nombre_proyecto,d.promotor,d.subestacion_conexion,d.provincia,d.numero_expediente_industria,r.titulo_original].join(" ").toLowerCase();if(!hay.includes(q.toLowerCase()))return false;}
    return true;
  }),[base,fEst,fTipo,fGrupo,fTech,fBol,q]);

  const mwLib = useMemo(()=>filtrados.reduce((a,r)=>a+(r.datos?.capacidad_mw_liberada||0),0),[filtrados]);
  const mwTot = useMemo(()=>filtrados.reduce((a,r)=>a+(r.datos?.potencia_mw||0),0),[filtrados]);
  const byGrupo = useMemo(()=>{
    const g={positivo:0,proceso:0,fallido:0};
    DEMO.forEach(r=>{const gr=ESTADOS[r.datos?.estado_permiso]?.grupo;if(gr&&g[gr]!==undefined)g[gr]++;});
    return g;
  },[]);

  return (
    <div style={{ minHeight:"100vh", background:"#070707", color:"#e2e8f0", fontFamily:"'IBM Plex Mono','Courier New',monospace" }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;700&display=swap');*{box-sizing:border-box}::-webkit-scrollbar{width:4px;height:4px}::-webkit-scrollbar-thumb{background:#1f1f1f;border-radius:2px}`}</style>

      {/* Header */}
      <div style={{ borderBottom:"1px solid #111", padding:"11px 20px", display:"flex", alignItems:"center", justifyContent:"space-between", gap:12 }}>
        <div>
          <div style={{ fontSize:14, fontWeight:700, letterSpacing:"0.15em", color:"#f8fafc" }}>ENERGY <span style={{ color:"#f97316" }}>BOE</span> TRACKER</div>
          <div style={{ fontSize:9, color:"#374151", letterSpacing:"0.08em", marginTop:1 }}>PERMISOS ENERGÉTICOS · BOE + DOGC + BOCM + BOJA + BOCyL</div>
        </div>
        <div style={{ display:"flex", gap:8, alignItems:"center" }}>
          <input placeholder="Proyecto, SET, exp., promotor..." value={q} onChange={e=>setQ(e.target.value)}
            style={{ background:"#0d0d0d", border:"1px solid #1f1f1f", borderRadius:4, color:"#e2e8f0", padding:"5px 12px", fontSize:11, outline:"none", width:280, fontFamily:"monospace" }} />
          <button onClick={()=>exportCSV(filtrados)} style={{ background:"#14532d", border:"1px solid #22c55e", borderRadius:4, color:"#4ade80", padding:"5px 14px", cursor:"pointer", fontSize:11, fontFamily:"monospace" }}>↓ CSV</button>
        </div>
      </div>

      {/* Tabs vistas */}
      <div style={{ borderBottom:"1px solid #0d0d0d", padding:"0 20px", display:"flex" }}>
        {VISTAS.map(v=>(
          <button key={v} onClick={()=>setVista(v)} style={{ background:"none", border:"none", borderBottom:`2px solid ${vista===v?"#f97316":"transparent"}`, color:vista===v?"#f97316":"#4b5563", padding:"9px 16px", cursor:"pointer", fontSize:11, letterSpacing:"0.08em", fontFamily:"monospace", transition:"color 0.15s" }}>
            {v}{v==="Proyectos fallidos"?` (${fallidos.length})`:""}{v==="Capacidad liberada"?` (${conCapacidad.length})":""}
          </button>
        ))}
      </div>

      <div style={{ padding:"12px 20px" }}>
        {/* Stats */}
        <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill,minmax(120px,1fr))", gap:8, marginBottom:12 }}>
          {[
            {l:"PUBLICACIONES",  v:filtrados.length,         c:"#64748b"},
            {l:"MW SOLICITADOS", v:mwTot.toLocaleString(),   c:"#38bdf8", u:"MW"},
            {l:"MW LIBERADOS",   v:mwLib,                    c:"#f97316", u:"MW", hi:mwLib>0},
            {l:"FAVORABLES",     v:byGrupo.positivo,         c:"#22c55e"},
            {l:"EN PROCESO",     v:byGrupo.proceso,          c:"#7dd3fc"},
            {l:"FALLIDOS",       v:byGrupo.fallido,          c:"#ef4444", hi:byGrupo.fallido>0},
          ].map(({l,v,c,u,hi})=>(
            <div key={l} style={{ background:hi?"rgba(249,115,22,0.05)":"#0a0a0a", border:`1px solid ${hi?"#7c2d12":"#111"}`, borderRadius:5, padding:"9px 12px" }}>
              <div style={{ fontSize:8, color:"#374151", letterSpacing:"0.12em", marginBottom:3 }}>{l}</div>
              <div style={{ fontSize:19, fontWeight:900, color:c, fontFamily:"monospace" }}>{v}{u&&<span style={{ fontSize:10, marginLeft:2, color:c+"99" }}>{u}</span>}</div>
            </div>
          ))}
        </div>

        {/* Panel SET */}
        {vista!=="Proyectos fallidos" && <SetPanel items={vista==="Capacidad liberada"?filtrados:DEMO} />}

        {/* Filtros */}
        <div style={{ display:"flex", gap:10, marginBottom:10, flexWrap:"wrap", alignItems:"center" }}>
          <Sel label="GRUPO"   opts={grupos}     val={fGrupo} set={setFGrupo} />
          <Sel label="TIPO"    opts={tipos}      val={fTipo}  set={setFTipo}  />
          <Sel label="ESTADO"  opts={estadoOpts} val={fEst}   set={setFEst}   />
          <Sel label="TECH"    opts={techs}      val={fTech}  set={setFTech}  />
          <Sel label="BOLETÍN" opts={boletines}  val={fBol}   set={setFBol}   />
          <span style={{ fontSize:10, color:"#1f2937", marginLeft:"auto" }}>{filtrados.length} resultados</span>
        </div>

        {/* Contenido según vista */}
        {vista==="Proyectos fallidos"
          ? <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill,minmax(340px,1fr))", gap:10 }}>
              {filtrados.length===0
                ? <div style={{ color:"#1f2937", padding:40, textAlign:"center", gridColumn:"1/-1" }}>Sin resultados</div>
                : filtrados.map(r=><CardFallido key={r.id} r={r} onSelect={setModal} />)}
            </div>
          : <Tabla rows={filtrados} onSelect={setModal} />
        }

        <div style={{ marginTop:8, fontSize:9, color:"#141414", textAlign:"right" }}>
          ENERGY BOE TRACKER v2.0 · {DEMO.length} REGISTROS DEMO · HAIKU-4-5
        </div>
      </div>
      <Modal item={modal} onClose={()=>setModal(null)} />
    </div>
  );
}
