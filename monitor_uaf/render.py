from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .analysis import sanitize_project_record


HARD_EXCLUDED_BULLETINS = {"2975-07"}


def _reference_date(item: dict[str, Any]) -> str:
    return str(
        item.get("latest_movement_date")
        or item.get("reference_date")
        or item.get("entry_date")
        or "0000-00-00"
    )


def prepare_dashboard_projects(payload: Any, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Prepara solamente la cartera vigente y la ordena por última modificación."""
    if isinstance(payload, dict) and "projects" in payload:
        payload = payload.get("projects")
    if isinstance(payload, dict):
        items = list(payload.values())
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    deduped: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = sanitize_project_record(raw)
        bulletin = str(item.get("bulletin", "") or "").strip()
        if not bulletin or bulletin in HARD_EXCLUDED_BULLETINS:
            continue
        if item.get("is_current") is False:
            continue
        lifecycle = str(item.get("lifecycle_code", "") or "").lower()
        if lifecycle in {"terminal", "historical", "stale", "excluded", "unverified"}:
            continue
        current = deduped.get(bulletin)
        if current is None or (
            _reference_date(item),
            int(item.get("pertinence_score", 0) or 0),
        ) >= (
            _reference_date(current),
            int(current.get("pertinence_score", 0) or 0),
        ):
            deduped[bulletin] = item

    return sorted(
        deduped.values(),
        key=lambda item: (
            _reference_date(item),
            2 if int(item.get("relevance_level", 9) or 9) == 1 else 1,
            int(item.get("pertinence_score", 0) or 0),
            int(item.get("priority_score", 0) or 0),
        ),
        reverse=True,
    )


def prepare_dashboard_alerts(payload: Any, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and "alerts" in payload:
        payload = payload.get("alerts")
    items = payload if isinstance(payload, list) else []
    deduped: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = deepcopy(raw)
        if str(item.get("bulletin", "") or "") in HARD_EXCLUDED_BULLETINS:
            continue
        marker = str(item.get("id") or f"{item.get('bulletin')}|{item.get('detected_at')}|{item.get('kind')}")
        deduped.setdefault(marker, item)
    return sorted(deduped.values(), key=lambda item: str(item.get("detected_at", "")), reverse=True)[:250]


def render_dashboard(
    projects: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    status: dict[str, Any],
    output: Path,
) -> Path:
    projects = prepare_dashboard_projects(projects)
    alerts = prepare_dashboard_alerts(alerts)
    output.parent.mkdir(parents=True, exist_ok=True)
    data_projects = json.dumps(projects, ensure_ascii=False).replace("</", "<\\/")
    data_alerts = json.dumps(alerts, ensure_ascii=False).replace("</", "<\\/")
    data_status = json.dumps(status or {}, ensure_ascii=False).replace("</", "<\\/")
    html = (
        TEMPLATE.replace("__PROJECTS__", data_projects)
        .replace("__ALERTS__", data_alerts)
        .replace("__STATUS__", data_status)
    )
    output.write_text(html, encoding="utf-8")
    return output


TEMPLATE = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor Legislativo UAF</title>
<style>
:root{--navy:#0b2034;--navy2:#123954;--blue:#1875a9;--blue2:#42a4c8;--violet:#6655aa;--bg:#f3f6f9;--card:#fff;--text:#142638;--muted:#617386;--line:#dbe4eb;--direct:#b42318;--secondary:#6655aa;--green:#21835b;--amber:#a96600}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif}.app{display:grid;grid-template-columns:230px 1fr;min-height:100vh}.side{background:linear-gradient(180deg,var(--navy),#071522);color:#dbe9f1;padding:20px 14px;position:sticky;top:0;height:100vh;overflow:auto}.brand{display:flex;gap:10px;align-items:center;padding:3px 6px 21px}.logo{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;background:#fff;color:var(--navy);font-weight:900}.brand b{display:block;font-size:13px}.brand small{color:#91b4ca}.navtitle{font-size:9px;text-transform:uppercase;letter-spacing:1.2px;color:#7097b0;margin:18px 8px 7px}.nav{width:100%;border:0;background:transparent;color:#cfe0e9;text-align:left;padding:10px;border-radius:8px;cursor:pointer;font-size:12px;display:flex;justify-content:space-between;gap:8px}.nav:hover,.nav.active{background:#173b57;color:#fff}.navcount{background:#2a526e;border-radius:99px;padding:2px 7px;font-size:9px}.side-status{margin-top:24px;padding:12px;background:#0e2a41;border:1px solid #244963;border-radius:10px;font-size:10px;line-height:1.55;color:#a9c4d4}.main{min-width:0}.top{height:66px;background:#fff;border-bottom:1px solid var(--line);padding:0 25px;display:flex;align-items:center;gap:15px;position:sticky;top:0;z-index:6}.top h1{font-size:16px;margin:0;white-space:nowrap}.search{flex:1;max-width:650px}.search input{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:9px;background:#f8fafb}.run{margin-left:auto;font-size:10px;color:var(--muted);display:flex;align-items:center;gap:6px}.dot{width:8px;height:8px;border-radius:50%;background:#25a26b}.dot.bad{background:#c8483d}.content{padding:22px 26px 55px;max-width:1600px;margin:auto}.hero{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:12px}.hero h2{font-size:23px;margin:0 0 6px}.hero p{font-size:12px;color:var(--muted);line-height:1.5;margin:0;max-width:900px}.pill{font-size:10px;font-weight:700;padding:6px 9px;border-radius:99px;background:#e5f2f8;color:#226589;white-space:nowrap}.segments{display:flex;gap:7px;flex-wrap:wrap;margin:13px 0}.segment{border:1px solid var(--line);background:#fff;border-radius:99px;padding:7px 11px;font-size:10px;font-weight:700;cursor:pointer}.segment.active{background:var(--navy2);color:#fff;border-color:var(--navy2)}.segment.direct.active{background:var(--direct);border-color:var(--direct)}.segment.secondary.active{background:var(--secondary);border-color:var(--secondary)}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin:11px 0 13px}.kpi{background:#fff;border:1px solid var(--line);border-radius:10px;padding:11px}.kpi span{font-size:8.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.45px}.kpi b{display:block;font-size:21px;margin:4px 0 2px}.kpi small{font-size:8.5px;color:var(--muted)}.section{margin-top:15px}.sectionhead{display:flex;justify-content:space-between;align-items:end;gap:15px;margin-bottom:8px}.sectionhead h3{margin:0;font-size:15px}.sectionhead p{margin:3px 0 0;color:var(--muted);font-size:10.5px}.watch-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.watch-card{background:#fff;border:1px solid var(--line);border-top:4px solid var(--direct);border-radius:10px;padding:11px;cursor:pointer;min-height:145px;display:flex;flex-direction:column}.watch-card:hover{box-shadow:0 7px 18px #17364b1b;transform:translateY(-1px)}.watch-date{font-size:8.5px;color:var(--muted);font-weight:700}.watch-card h4{font-size:11px;line-height:1.35;margin:7px 0 6px}.watch-card .bulletin{margin-top:auto}.watch-stage{font-size:9px;line-height:1.4;color:#455d70;margin-bottom:8px}.watch-empty{grid-column:1/-1;background:#fff;border:1px dashed var(--line);padding:18px;border-radius:10px;text-align:center;font-size:10px;color:var(--muted)}.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:#fff;border:1px solid var(--line);border-radius:10px 10px 0 0;padding:9px}.toolbar select{border:1px solid var(--line);border-radius:7px;padding:7px 9px;background:#fff;font-size:10px}.toolbar .spacer{flex:1}.count{font-size:10px;color:var(--muted)}.tablewrap{background:#fff;border:1px solid var(--line);border-top:0;border-radius:0 0 11px 11px;overflow:auto}table{width:100%;border-collapse:collapse;min-width:1070px}th{background:#f7f9fb;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.45px;padding:10px;text-align:left;border-bottom:1px solid var(--line)}td{padding:11px 10px;border-bottom:1px solid #edf1f4;vertical-align:top;font-size:10.5px}tr:hover{background:#f9fbfd}.title{font-size:11.5px;font-weight:800;line-height:1.35}.bulletin{font-size:9.5px;color:var(--blue);font-weight:800;margin-top:4px}.state{line-height:1.45}.subtle{font-size:9px;color:var(--muted);margin-top:4px}.date-cell b{font-size:11px;display:block}.badge{display:inline-block;border-radius:99px;padding:4px 7px;background:#edf2f6;color:#415a6d;font-size:8.5px;font-weight:700;margin:0 3px 3px 0}.badge.direct{background:#fdebea;color:var(--direct)}.badge.secondary{background:#eeeafa;color:var(--secondary)}.badge.high{background:#fff0e0;color:#9a4c00}.badge.critical{background:#fde8e6;color:#a72018}.tags{display:flex;gap:4px;flex-wrap:wrap;max-width:310px}.tag{font-size:8.5px;background:#eaf3f8;color:#225b7e;padding:3px 6px;border-radius:4px}.details{border:0;background:#e8f2f8;color:#155f8d;border-radius:7px;padding:6px 8px;cursor:pointer;font-size:9px;font-weight:800}.analytics{display:grid;grid-template-columns:1.15fr .85fr .85fr;gap:9px;margin-top:10px}.panel{background:#fff;border:1px solid var(--line);border-radius:10px;padding:11px;min-width:0}.panel h4{font-size:11px;margin:0}.panel .sub{font-size:8.5px;color:var(--muted);margin:3px 0 7px}.matter-list{display:flex;flex-direction:column;gap:5px;max-height:125px;overflow:auto}.matter{display:grid;grid-template-columns:minmax(125px,1fr) 1.8fr 66px;align-items:center;gap:7px;font-size:8.5px;cursor:pointer}.matter:hover b{color:var(--blue)}.track{height:7px;background:#edf1f4;border-radius:99px;overflow:hidden}.track i{display:block;height:100%;background:linear-gradient(90deg,var(--blue2),var(--navy2));border-radius:99px}.matter em{font-style:normal;color:var(--muted);text-align:right}.chart{height:92px;display:flex;align-items:flex-end;gap:3px;border-bottom:1px solid var(--line);padding:8px 2px 0}.month{flex:1;min-width:7px;height:100%;display:flex;align-items:flex-end;justify-content:center;gap:1px;position:relative}.col{width:42%;min-width:3px;border-radius:3px 3px 0 0}.col.direct{background:var(--blue)}.col.secondary{background:var(--violet)}.month-label{position:absolute;bottom:-20px;font-size:6.5px;color:var(--muted);transform:rotate(-42deg);white-space:nowrap}.legend{font-size:7.5px;color:var(--muted);margin-top:23px;display:flex;gap:8px}.legend i{display:inline-block;width:7px;height:7px;margin-right:3px;border-radius:2px}.alerts{max-height:123px;overflow:auto;display:flex;flex-direction:column;gap:5px}.alert{border-left:3px solid var(--blue);padding:6px 7px;background:#f7fafc;border-radius:5px}.alert b{font-size:9px;display:block}.alert span{font-size:8px;color:var(--muted);line-height:1.35}.audit{display:grid;grid-template-columns:1.3fr .7fr;gap:9px;margin-top:10px}.source-row{display:grid;grid-template-columns:1.3fr .55fr .45fr 2fr;gap:8px;padding:7px 0;border-bottom:1px solid #edf1f4;font-size:9px}.ok{color:var(--green);font-weight:700}.bad{color:#b42318;font-weight:700}.health-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.health-card{background:#f6f9fb;border-radius:7px;padding:9px}.health-card b{font-size:9px;display:block}.health-card div{font-size:17px;font-weight:800;margin-top:4px}.health-card small{font-size:8px;color:var(--muted)}.foot{font-size:8.5px;color:var(--muted);line-height:1.45;margin-top:9px}.modal{position:fixed;inset:0;background:#071624aa;display:none;justify-content:flex-end;z-index:20}.modal.open{display:flex}.drawer{width:min(820px,95vw);height:100vh;background:#fff;overflow:auto}.drawerhead{background:linear-gradient(135deg,var(--navy),var(--navy2));color:#fff;padding:20px 23px;position:sticky;top:0;z-index:2}.drawerhead small{color:#95cae3;font-weight:800}.drawerhead h3{font-size:19px;margin:6px 45px 6px 0}.drawerhead p{font-size:11px;margin:0;color:#c0d4e2;line-height:1.45}.close{position:absolute;right:15px;top:14px;border:0;background:#ffffff20;color:#fff;border-radius:7px;width:31px;height:31px;cursor:pointer}.drawermeta{display:flex;gap:5px;flex-wrap:wrap;margin-top:10px}.drawermeta span{font-size:8.5px;background:#ffffff1c;padding:4px 7px;border-radius:99px}.drawerbody{padding:18px 22px 32px}.detail-section{margin-bottom:18px}.detail-section h4{font-size:10.5px;text-transform:uppercase;letter-spacing:.55px;color:#3e586d;margin:0 0 8px}.callout{background:#f1f7fa;border-left:4px solid var(--blue);border-radius:6px;padding:11px;font-size:11.5px;line-height:1.58;color:#31495b}.facts{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.fact{border:1px solid var(--line);border-radius:7px;padding:8px}.fact b{font-size:8px;color:var(--muted);text-transform:uppercase;display:block;margin-bottom:4px}.fact span{font-size:10.5px;line-height:1.35}.people{display:flex;flex-wrap:wrap;gap:5px}.person{background:#eef3f7;border-radius:6px;padding:5px 7px;font-size:9.5px}.legal-tags{max-width:none;gap:6px}.legal-tags .tag{font-size:10.5px;padding:5px 8px;line-height:1.3}.detail-table-wrap{overflow:auto;border:1px solid var(--line);border-radius:8px}.detail-table{min-width:780px}.detail-table th{font-size:8px}.detail-table td{font-size:9.5px;padding:8px}.doclink,.press-link{color:var(--blue);text-decoration:none;font-weight:750;font-size:11.5px;line-height:1.55;overflow-wrap:anywhere}.doclink:hover,.press-link:hover{text-decoration:underline}.document-briefs{display:flex;flex-direction:column;gap:7px;margin-top:9px}.document-brief{border:1px solid var(--line);border-radius:8px;padding:9px;background:#fff}.document-brief header{display:flex;justify-content:space-between;gap:10px;align-items:start}.document-brief b{font-size:10.5px}.document-brief time{font-size:8.5px;color:var(--muted);white-space:nowrap}.document-brief p{font-size:10.5px;line-height:1.5;color:#405568;margin:6px 0}.press-list{display:flex;flex-direction:column;gap:7px}.press-item{border:1px solid var(--line);border-radius:7px;padding:9px}.press-item b{font-size:10.5px;line-height:1.4;display:block}.press-item span{font-size:8.5px;color:var(--muted);display:block;margin:3px 0}.empty{padding:15px;text-align:center;color:var(--muted);font-size:9.5px}
@media(max-width:1250px){.watch-grid{grid-template-columns:repeat(3,1fr)}.kpis{grid-template-columns:repeat(3,1fr)}.analytics{grid-template-columns:1fr 1fr}.analytics .panel:first-child{grid-column:1/-1}.audit{grid-template-columns:1fr}}
@media(max-width:800px){.app{grid-template-columns:1fr}.side{display:none}.content{padding:16px}.top{padding:0 14px}.top h1{display:none}.kpis{grid-template-columns:repeat(2,1fr)}.watch-grid{grid-template-columns:1fr}.analytics{grid-template-columns:1fr}.analytics .panel:first-child{grid-column:auto}.facts{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
<aside class="side">
  <div class="brand"><div class="logo">UAF</div><div><b>Monitor Legislativo</b><small>Ley N.º 19.913</small></div></div>
  <div class="navtitle">Cartera vigente</div>
  <button class="nav active" data-nav="all" onclick="navAction('all',this)"><span>Panel general</span><span class="navcount" id="navAll">0</span></button>
  <button class="nav" data-nav="direct" onclick="navAction('direct',this)"><span>Cambios directos / UAF</span><span class="navcount" id="navDirect">0</span></button>
  <button class="nav" data-nav="secondary" onclick="navAction('secondary',this)"><span>Otras materias LA/FT</span><span class="navcount" id="navSecondary">0</span></button>
  <button class="nav" data-nav="documents" onclick="navAction('documents',this)"><span>Con documentos reseñados</span><span class="navcount" id="navDocuments">0</span></button>
  <div class="navtitle">Consulta</div>
  <button class="nav" onclick="go('watch')"><span>Iniciativas a la vista</span></button>
  <button class="nav" onclick="go('projects')"><span>Boletines por fecha</span></button>
  <button class="nav" onclick="go('analytics')"><span>Análisis compacto</span></button>
  <div class="navtitle">Control</div>
  <button class="nav" onclick="go('audit')"><span>Auditoría de fuentes</span></button>
  <button class="nav" onclick="go('health')"><span>Salud del monitor</span></button>
  <div class="side-status" id="sideStatus">Cargando estado…</div>
</aside>
<main class="main">
<header class="top"><h1>Observatorio legislativo estratégico</h1><div class="search"><input id="q" placeholder="Buscar boletín, título, autor, etapa o materia…"></div><div class="run"><i class="dot" id="runDot"></i><span id="lastRun">Sin ejecución</span></div></header>
<div class="content" id="top">
  <section class="hero"><div><h2>Proyectos de ley vigentes con impacto UAF</h2><p>Solo se publican iniciativas nuevas o en tramitación activa. La etapa, el informe y la última modificación se validan en la ficha individual del boletín; los antecedentes históricos y proyectos terminados quedan fuera.</p></div><span class="pill">Fuentes oficiales + documentos + prensa</span></section>
  <div class="segments">
    <button class="segment active" data-scope="all" onclick="setScope('all')">Todos los vigentes</button>
    <button class="segment direct" data-scope="direct" onclick="setLevel('1')">Modifican Ley 19.913 / impacto explícito UAF</button>
    <button class="segment secondary" data-scope="secondary" onclick="setLevel('2')">Otras materias LA/FT</button>
    <button class="segment" data-scope="documents" onclick="setScope('documents')">Con reseña documental</button>
  </div>
  <section class="kpis" id="kpis"></section>

  <section class="section" id="watch">
    <div class="sectionhead"><div><h3>Cambios a la Ley N.º 19.913 que hay que tener en vista</h3><p>Hasta cinco iniciativas directas, ordenadas por su última modificación legislativa verificada.</p></div></div>
    <div class="watch-grid" id="watchGrid"></div>
  </section>

  <section class="section" id="projects">
    <div class="sectionhead"><div><h3>Boletines e iniciativas vigentes</h3><p>Orden inicial: última modificación oficial, desde la más reciente.</p></div></div>
    <div class="toolbar">
      <select id="life"><option value="">Toda situación</option><option value="new">Ingreso reciente</option><option value="upcoming">Próximo hito</option><option value="active">Tramitación activa</option></select>
      <select id="matter"><option value="">Todas las materias</option></select>
      <select id="sort"><option value="movement">Ordenar: última modificación</option><option value="relevance">Ordenar: pertinencia UAF</option><option value="entry">Ordenar: fecha de ingreso</option><option value="bulletin">Ordenar: boletín</option></select>
      <span class="spacer"></span><span class="count" id="resultCount"></span>
    </div>
    <div class="tablewrap"><table><thead><tr><th>Última modificación</th><th>Proyecto</th><th>Etapa e informe actual</th><th>Vinculación</th><th>Ámbitos legales afectados</th><th></th></tr></thead><tbody id="rows"></tbody></table></div>
  </section>

  <section class="section" id="analytics">
    <div class="sectionhead"><div><h3>Análisis compacto</h3><p>Los gráficos ocupan un espacio secundario y sirven como filtros del listado.</p></div></div>
    <div class="analytics">
      <article class="panel"><h4>Materias con mayor actividad y avance</h4><div class="sub">Cantidad, proximidad legislativa y movimiento reciente. Pulse una materia para filtrar.</div><div class="matter-list" id="matterMap"></div></article>
      <article class="panel"><h4>Movimientos por mes</h4><div class="sub">Hitos extraídos de las cronologías oficiales.</div><div class="chart" id="historyChart"></div><div class="legend"><span><i style="background:var(--blue)"></i>Directos</span><span><i style="background:var(--violet)"></i>Otros LA/FT</span></div></article>
      <article class="panel"><h4>Novedades detectadas</h4><div class="sub">Alertas acumuladas por cambios reales.</div><div class="alerts" id="alertList"></div></article>
    </div>
  </section>

  <section class="section audit" id="audit"><article class="panel"><h4>Auditoría de fuentes</h4><div class="sub">Disponibilidad y resultado del último barrido.</div><div id="sourceRows"></div></article><article class="panel" id="health"><h4>Salud del monitor</h4><div class="sub">Controles de vigencia y enriquecimiento.</div><div class="health-grid" id="healthGrid"></div><div class="foot" id="healthNote"></div></article></section>
</div>
</main>
</div>
<div class="modal" id="modal" onclick="if(event.target===this)closeModal()"><aside class="drawer"><header class="drawerhead"><button class="close" onclick="closeModal()">✕</button><small id="dBulletin"></small><h3 id="dTitle"></h3><p id="dState"></p><div class="drawermeta" id="dMeta"></div></header><div class="drawerbody" id="dBody"></div></aside></div>
<script>
const projects=__PROJECTS__,alerts=__ALERTS__,status=__STATUS__;
let scope='all',matterFilter='';
const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
const dval=v=>{const t=Date.parse(v||'');return Number.isNaN(t)?0:t};
const displayDate=v=>{if(!v)return 'Sin fecha verificada';const d=new Date(String(v).slice(0,10)+'T12:00:00');return Number.isNaN(d.getTime())?v:d.toLocaleDateString('es-CL',{day:'2-digit',month:'2-digit',year:'numeric'})};
const referenceDate=p=>p.latest_movement_date||p.reference_date||p.entry_date||'';
const projectMatterNames=p=>[...(p.affected_legal_areas||[]),...(p.top_impacts||[]).map(x=>x.name)].filter((x,i,a)=>x&&a.indexOf(x)===i);
const reviews=p=>p.metadata?.official_document_reviews||p.metadata?.official_documents_matched||[];
function stageWeight(p){const s=((p.stage||p.state||'')+'').toLowerCase();if(s.includes('mixta')||s.includes('promulg'))return 4;if(s.includes('tercer'))return 3;if(s.includes('segundo'))return 2;if(s.includes('primer'))return 1;return .5}
function recencyWeight(p){const days=(Date.now()-dval(referenceDate(p)))/86400000;if(!Number.isFinite(days))return 0;return days<=30?4:days<=90?3:days<=180?2:days<=365?1:.4}
function relevanceRank(p){return p.relevance_level===1?2:p.relevance_level===2?1:0}
function setScope(value){scope=value;document.querySelectorAll('.segment').forEach(b=>b.classList.toggle('active',b.dataset.scope===value));document.querySelectorAll('.nav[data-nav]').forEach(b=>b.classList.toggle('active',b.dataset.nav===value));renderAll()}
function setLevel(value){setScope(String(value)==='1'?'direct':String(value)==='2'?'secondary':'all')}
function navAction(value,button){setScope(value);go(value==='all'?'top':'projects');document.querySelectorAll('.nav').forEach(b=>b.classList.remove('active'));button.classList.add('active')}
function go(id){document.getElementById(id)?.scrollIntoView({behavior:'smooth',block:'start'})}
function filtered(){const q=document.getElementById('q').value.trim().toLowerCase(),life=document.getElementById('life').value,matter=document.getElementById('matter').value,sort=document.getElementById('sort').value;let list=projects.filter(p=>{const hay=[p.bulletin,p.title,p.stage,p.commission,p.latest_movement,p.analysis_summary,...(p.promoters||[]),...projectMatterNames(p)].join(' ').toLowerCase();const scopeOk=scope==='all'||(scope==='direct'&&p.relevance_level===1)||(scope==='secondary'&&p.relevance_level===2)||(scope==='documents'&&reviews(p).length);const lifeOk=!life||(p.lifecycle_flags||[]).includes(life)||p.lifecycle_code===life;const matterOk=!matter||projectMatterNames(p).includes(matter);return scopeOk&&lifeOk&&matterOk&&(!q||hay.includes(q))});list.sort((a,b)=>{if(sort==='relevance')return relevanceRank(b)-relevanceRank(a)||(b.pertinence_score||0)-(a.pertinence_score||0)||dval(referenceDate(b))-dval(referenceDate(a));if(sort==='entry')return dval(b.entry_date)-dval(a.entry_date);if(sort==='bulletin')return b.bulletin.localeCompare(a.bulletin);return dval(referenceDate(b))-dval(referenceDate(a))||relevanceRank(b)-relevanceRank(a)||(b.pertinence_score||0)-(a.pertinence_score||0)});return list}
function renderKpis(){const direct=projects.filter(p=>p.relevance_level===1).length,secondary=projects.filter(p=>p.relevance_level===2).length,docs=projects.filter(p=>reviews(p).length).length,moves=projects.filter(p=>p.latest_movement_date).length;document.getElementById('kpis').innerHTML=`<div class="kpi"><span>Iniciativas vigentes</span><b>${projects.length}</b><small>Solo tramitación actual</small></div><div class="kpi"><span>Ley 19.913 / UAF</span><b>${direct}</b><small>Impacto explícito</small></div><div class="kpi"><span>Otras materias LA/FT</span><b>${secondary}</b><small>Impacto potencial</small></div><div class="kpi"><span>Movimiento fechado</span><b>${moves}</b><small>Fila oficial del boletín</small></div><div class="kpi"><span>Documentos reseñados</span><b>${docs}</b><small>PDF, informes u oficios</small></div>`;document.getElementById('navAll').textContent=projects.length;document.getElementById('navDirect').textContent=direct;document.getElementById('navSecondary').textContent=secondary;document.getElementById('navDocuments').textContent=docs}
function renderWatch(){const items=projects.filter(p=>p.relevance_level===1).sort((a,b)=>dval(referenceDate(b))-dval(referenceDate(a))||(b.pertinence_score||0)-(a.pertinence_score||0)).slice(0,5);document.getElementById('watchGrid').innerHTML=items.length?items.map(p=>`<article class="watch-card" onclick="openProject('${esc(p.bulletin)}')"><div class="watch-date">${esc(displayDate(referenceDate(p)))}</div><h4>${esc(p.title||'Título pendiente')}</h4><div class="watch-stage">${esc(p.stage||p.state||'Etapa por verificar')}<br>${esc(p.metadata?.committee_report||p.commission||'')}</div><div class="bulletin">Boletín ${esc(p.bulletin)} →</div></article>`).join(''):'<div class="watch-empty">No hay iniciativas directas vigentes con fecha validada.</div>'}
function movementText(p){return p.latest_movement||'No se detectó una fila de tramitación fechada para este boletín.'}
function renderRows(){const list=filtered();document.getElementById('resultCount').textContent=`${list.length} iniciativa(s)`;document.getElementById('rows').innerHTML=list.length?list.map(p=>`<tr><td class="date-cell"><b>${esc(displayDate(referenceDate(p)))}</b><div class="subtle">${p.latest_movement_date?'Último movimiento':'Fecha de ingreso'}</div></td><td><div class="title">${esc(p.title||'Título pendiente')}</div><div class="bulletin">Boletín ${esc(p.bulletin)}</div></td><td><div class="state"><b>${esc(p.stage||p.state||'Etapa por verificar')}</b><br>${esc(p.metadata?.committee_report||p.commission||'')}</div><div class="subtle">${esc(movementText(p))}</div></td><td><span class="badge ${p.relevance_level===1?'direct':'secondary'}">${esc(p.relevance_level===1?'Ley 19.913 / UAF':'Otra materia LA/FT')}</span><br><span class="badge">${esc(p.lifecycle_status||'Vigente')}</span></td><td><div class="tags">${projectMatterNames(p).slice(0,5).map(x=>`<span class="tag">${esc(x)}</span>`).join('')||'<span class="tag">Pendiente</span>'}</div></td><td><button class="details" onclick="openProject('${esc(p.bulletin)}')">Ver ficha →</button></td></tr>`).join(''):'<tr><td colspan="6"><div class="empty">No hay iniciativas para los filtros seleccionados.</div></td></tr>'}
function renderMatterMap(){const map=new Map();filtered().forEach(p=>projectMatterNames(p).forEach(name=>{const row=map.get(name)||{count:0,score:0,last:0};row.count++;row.score+=stageWeight(p)*2+recencyWeight(p);row.last=Math.max(row.last,dval(referenceDate(p)));map.set(name,row)}));const rows=[...map.entries()].sort((a,b)=>b[1].score-a[1].score||b[1].last-a[1].last).slice(0,8),max=Math.max(1,...rows.map(([,v])=>v.score));document.getElementById('matterMap').innerHTML=rows.map(([name,v])=>`<div class="matter" onclick="applyMatter('${esc(name)}')" title="${v.count} iniciativa(s); última actividad ${displayDate(new Date(v.last).toISOString().slice(0,10))}"><b>${esc(name)}</b><div class="track"><i style="width:${Math.max(5,v.score/max*100)}%"></i></div><em>${v.count} · ${esc(displayDate(new Date(v.last).toISOString().slice(0,10)))}</em></div>`).join('')||'<div class="empty">Sin materias clasificadas.</div>'}
function applyMatter(name){matterFilter=name;document.getElementById('matter').value=name;renderAll();go('projects')}
function historyItems(p){const meta=p.metadata||{},rows=[...(meta.senado_proceedings||[]),...(meta.camara_proceedings||[])];if(!rows.length&&p.latest_movement_date)rows.push({date:p.latest_movement_date});return rows}
function renderHistory(){const months=new Map();filtered().forEach(p=>historyItems(p).forEach(h=>{const m=String(h.date||'').match(/^(\d{4})-(\d{2})/);if(!m)return;const key=`${m[1]}-${m[2]}`,row=months.get(key)||{direct:0,secondary:0};p.relevance_level===1?row.direct++:row.secondary++;months.set(key,row)}));const data=[...months.entries()].sort().slice(-14),max=Math.max(1,...data.map(([,v])=>Math.max(v.direct,v.secondary)));document.getElementById('historyChart').innerHTML=data.map(([m,v])=>`<div class="month" title="${m}: ${v.direct} directos, ${v.secondary} relacionados"><i class="col direct" style="height:${Math.max(3,v.direct/max*86)}px"></i><i class="col secondary" style="height:${Math.max(3,v.secondary/max*86)}px"></i><span class="month-label">${m}</span></div>`).join('')||'<div class="empty">El gráfico se completará con hitos fechados.</div>'}
function renderAlerts(){document.getElementById('alertList').innerHTML=alerts.slice(0,15).map(a=>`<div class="alert"><b>${esc(a.bulletin||'')} · ${esc(a.title||'Novedad legislativa')}</b><span>${esc(displayDate((a.detected_at||'').slice(0,10)))} · ${esc((a.changes||[]).map(c=>c.after).filter(Boolean).join(' · ')||a.kind||'Cambio detectado')}</span></div>`).join('')||'<div class="empty">No hay novedades acumuladas.</div>'}
function initMatterFilter(){const names=[...new Set(projects.flatMap(projectMatterNames))].sort();document.getElementById('matter').innerHTML='<option value="">Todas las materias</option>'+names.map(x=>`<option>${esc(x)}</option>`).join('')}
function renderAudit(){const sources=Object.entries(status.sources||{});document.getElementById('sourceRows').innerHTML=sources.map(([name,v])=>`<div class="source-row"><b>${esc(name)}</b><span class="${v.ok?'ok':'bad'}">${v.ok?'Disponible':'Error'}</span><span>${esc(v.items??v.projects_searched??'—')}</span><span>${esc(v.note||v.error||'Consulta completada')}</span></div>`).join('')||'<div class="empty">Sin datos de fuentes.</div>';const ok=sources.filter(([,v])=>v.ok).length;document.getElementById('healthGrid').innerHTML=`<div class="health-card"><b>Fuentes disponibles</b><div>${ok}/${sources.length}</div><small>Última ejecución</small></div><div class="health-card"><b>Etapas verificadas</b><div>${status.stages_verified??0}</div><small>Ficha individual</small></div><div class="health-card"><b>Movimientos verificados</b><div>${status.movements_verified??0}</div><small>Fecha del mismo boletín</small></div><div class="health-card"><b>Excluidos</b><div>${status.excluded_count??0}</div><small>Terminados o históricos</small></div>`;document.getElementById('healthNote').textContent=`${status.eligibility_rule||''} Correo: ${status.email_message||'sin información'}.`}
function updateHeader(){const finished=status.finished_at||'Sin primera ejecución',sources=Object.values(status.sources||{}),ok=sources.filter(x=>x.ok).length;document.getElementById('lastRun').textContent=`Último barrido: ${finished}`;document.getElementById('runDot').classList.toggle('bad',sources.length>0&&ok<sources.length);document.getElementById('sideStatus').innerHTML=`<b style="color:#fff">Estado del monitor</b><br>Fuentes disponibles: ${ok}/${sources.length}<br>Vigentes: ${status.projects_monitored??projects.length}<br>Descartadas: ${status.excluded_count??0}<br>Documentos reseñados: ${projects.reduce((n,p)=>n+reviews(p).length,0)}<br>Prensa: ${status.sources?.['Prensa de proyectos']?.items??0} enlace(s)`}
function docLinks(docs){return (docs||[]).map(d=>`<a class="doclink" href="${esc(d.url||'#')}" target="_blank" rel="noopener">${esc(d.label||'Documento')} ↗</a>`).join('<br>')||'—'}
function proceedings(p){const meta=p.metadata||{};return meta.senado_proceedings?.length?meta.senado_proceedings:(meta.camara_proceedings||[])}
function proceedingsTable(p){const rows=proceedings(p).slice().sort((a,b)=>dval(b.date)-dval(a.date));if(!rows.length)return '<div class="empty">No se encontraron filas de tramitación individualizadas.</div>';return `<div class="detail-table-wrap"><table class="detail-table"><thead><tr><th>Sesión</th><th>Fecha</th><th>Subetapa / movimiento</th><th>Etapa</th><th>Documentos</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.session||'—')}</td><td>${esc(displayDate(r.date))}</td><td>${esc(r.substage||'—')}</td><td>${esc(r.stage||'—')}</td><td>${docLinks(r.documents)}</td></tr>`).join('')}</tbody></table></div>`}
function presentationsTable(p){const rows=(p.metadata?.commission_presentations||[]).slice().sort((a,b)=>dval(b.date)-dval(a.date));if(!rows.length)return '<div class="empty">No se detectaron presentaciones ante comisión publicadas.</div>';return `<div class="detail-table-wrap"><table class="detail-table"><thead><tr><th>Fecha</th><th>Presentación</th><th>Organización</th><th>Comisión</th><th>Documento</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(displayDate(r.date))}</td><td>${esc(r.title||'—')}</td><td>${esc(r.organization||'—')}</td><td>${esc(r.commission||'—')}</td><td>${docLinks(r.documents)}</td></tr>`).join('')}</tbody></table></div>`}
function documentBriefs(p){const rows=reviews(p).slice(0,6);return rows.length?`<div class="document-briefs">${rows.map(r=>`<article class="document-brief"><header><b>${esc(r.kind||r.label||'Documento oficial')}</b><time>${esc(displayDate(r.date))}</time></header><p>${esc(r.summary||'Documento detectado; reseña pendiente de extracción de texto.')}</p><a class="doclink" href="${esc(r.url||'#')}" target="_blank" rel="noopener">${esc(r.label||'Abrir documento oficial')} ↗</a></article>`).join('')}</div>`:'<div class="empty">No se pudo construir una reseña documental. Los enlaces de la cronología siguen disponibles.</div>'}
function pressSection(p){const rows=p.metadata?.press_mentions||[];return rows.length?`<div class="press-list">${rows.map(r=>`<div class="press-item"><b><a class="press-link" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)} ↗</a></b><span>${esc(r.outlet||'Medio')} · ${esc(displayDate(r.date))}</span></div>`).join('')}</div>`:'<div class="empty">No se encontraron publicaciones periodísticas recientes asociadas al boletín o su título.</div>'}
function openProject(bulletin){const p=projects.find(x=>x.bulletin===bulletin);if(!p)return;const people=p.promoters||p.metadata?.promoters||[],areas=projectMatterNames(p),facts=[['Fecha de ingreso',displayDate(p.entry_date)],['Cámara de origen',p.origin_chamber],['Tipo de iniciativa',p.initiative_type],['Etapa vigente',p.stage||p.state],['Comisión / informe',p.metadata?.committee_report||p.commission],['Urgencia',p.urgency||'Sin urgencia informada'],['Última modificación',displayDate(p.latest_movement_date)],['Fuente de etapa',p.metadata?.official_stage_source||'Fuente oficial consolidada']];document.getElementById('dBulletin').textContent=`Boletín ${p.bulletin}`;document.getElementById('dTitle').textContent=p.title||'Título pendiente';document.getElementById('dState').textContent=[p.stage,p.metadata?.committee_report||p.commission].filter(Boolean).join(' · ')||'Estado por verificar';document.getElementById('dMeta').innerHTML=`<span>${esc(p.relevance_label||'')}</span><span>${esc(p.lifecycle_status||'')}</span><span>${reviews(p).length} documento(s) reseñado(s)</span>`;document.getElementById('dBody').innerHTML=`<div class="detail-section"><h4>Antecedentes generales</h4><div class="facts">${facts.filter(([,v])=>v&&v!=='—').map(([k,v])=>`<div class="fact"><b>${esc(k)}</b><span>${esc(v)}</span></div>`).join('')}</div></div><div class="detail-section"><h4>Materia y lectura estratégica</h4><div class="callout">${esc(p.analysis_summary||p.matter_summary||p.title)}</div>${documentBriefs(p)}</div><div class="detail-section"><h4>Promotores de la iniciativa</h4><div class="people">${people.map(x=>`<span class="person">${esc(x)}</span>`).join('')||'<span class="subtle">La fuente oficial aún no entregó autores estructurados.</span>'}</div></div><div class="detail-section"><h4>Ámbitos legales afectados</h4><div class="tags legal-tags">${areas.map(x=>`<span class="tag">${esc(x)}</span>`).join('')||'<span class="tag">Pendiente</span>'}</div></div><div class="detail-section"><h4>Último antecedente legislativo</h4><div class="callout"><b>${esc(displayDate(p.latest_movement_date))}</b><br>${esc(movementText(p))}<br><span class="subtle">${esc(p.metadata?.movement_source||'Validación pendiente de una fila fechada del mismo boletín')}</span></div></div><div class="detail-section"><h4>Cronología de tramitación — más reciente primero</h4>${proceedingsTable(p)}</div><div class="detail-section"><h4>Presentaciones ante comisión</h4>${presentationsTable(p)}</div><div class="detail-section"><h4>Cobertura de prensa vinculada</h4>${pressSection(p)}</div><div class="detail-section"><h4>Fuentes oficiales</h4><div>${(p.source_urls||[]).map(u=>`<p><a class="doclink" href="${esc(u)}" target="_blank" rel="noopener">${esc(u)} ↗</a></p>`).join('')||'<div class="empty">Sin enlace oficial guardado.</div>'}</div></div>`;document.getElementById('modal').classList.add('open');document.body.style.overflow='hidden'}
function closeModal(){document.getElementById('modal').classList.remove('open');document.body.style.overflow=''}
function renderAll(){renderWatch();renderRows();renderMatterMap();renderHistory()}
function init(){initMatterFilter();renderKpis();renderAlerts();renderAudit();updateHeader();renderAll()}
document.getElementById('q').addEventListener('input',renderAll);document.getElementById('life').addEventListener('change',renderAll);document.getElementById('sort').addEventListener('change',renderAll);document.getElementById('matter').addEventListener('change',e=>{matterFilter=e.target.value;renderAll()});document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});init();
</script>
</body></html>'''
