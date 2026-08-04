from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .analysis import sanitize_project_record
from .config import DOCS_DIR


def compact_dashboard_project(project: dict[str, Any]) -> dict[str, Any]:
    clean = sanitize_project_record(project)
    for key in ("raw_hash", "fingerprint"):
        clean.pop(key, None)
    clean.pop("direct_hits", None)
    impacts: dict[str, dict[str, Any]] = {}
    for name, payload in (clean.get("impacts") or {}).items():
        impacts[name] = {
            "score": payload.get("score", 0),
            "level": payload.get("level", 0),
            "recommendation": payload.get("recommendation", ""),
            "hits": [str(value)[:160] for value in (payload.get("hits") or [])[:8]],
        }
    clean["impacts"] = impacts
    clean["top_impacts"] = [
        {
            "name": item.get("name", ""),
            "score": item.get("score", 0),
            "level": item.get("level", 0),
            "recommendation": item.get("recommendation", ""),
            "hits": [str(value)[:160] for value in (item.get("hits") or [])[:8]],
        }
        for item in (clean.get("top_impacts") or [])[:9]
    ]
    return clean


def compact_alert(alert: dict[str, Any]) -> dict[str, Any]:
    clean = dict(alert)
    clean["changes"] = [
        {
            "field": str(item.get("field", ""))[:80],
            "before": str(item.get("before", ""))[:600],
            "after": str(item.get("after", ""))[:600],
        }
        for item in (clean.get("changes") or [])[:12]
    ]
    clean["source_urls"] = list(dict.fromkeys(clean.get("source_urls") or []))[:20]
    clean["decisions"] = [str(value)[:800] for value in (clean.get("decisions") or [])[:5]]
    clean["top_impacts"] = [
        {
            "name": item.get("name", ""),
            "score": item.get("score", 0),
            "level": item.get("level", 0),
            "recommendation": item.get("recommendation", ""),
        }
        for item in (clean.get("top_impacts") or [])[:5]
    ]
    return clean


def prepare_dashboard_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_dashboard_project(project) for project in projects]


def prepare_dashboard_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_alert(alert) for alert in alerts[:250]]


def render_dashboard(
    projects: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    status: dict[str, Any],
    output: Path | None = None,
) -> Path:
    output_path = output or DOCS_DIR / "index.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    public_projects = prepare_dashboard_projects(projects)
    public_alerts = prepare_dashboard_alerts(alerts)
    replacements = {
        "__PROJECTS_JSON__": json.dumps(public_projects, ensure_ascii=False).replace("</", "<\\/"),
        "__ALERTS_JSON__": json.dumps(public_alerts, ensure_ascii=False).replace("</", "<\\/"),
        "__STATUS_JSON__": json.dumps(status, ensure_ascii=False).replace("</", "<\\/"),
    }
    document = _template()
    for marker, value in replacements.items():
        document = document.replace(marker, value)
    output_path.write_text(document, encoding="utf-8")
    return output_path


def _template() -> str:
    return r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Observatorio Legislativo Estratégico UAF</title>
<style>
:root{--navy:#0b2033;--navy2:#123653;--blue:#1a6f9e;--cyan:#3a9fc2;--bg:#f2f5f8;--card:#fff;--text:#13283b;--muted:#66798b;--line:#dbe4eb;--critical:#b42318;--high:#c85f00;--medium:#886800;--violet:#654ca3;--green:#20845a}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--text)}
.shell{display:grid;grid-template-columns:245px 1fr;min-height:100vh}.sidebar{background:linear-gradient(180deg,var(--navy),#071421);color:#dceaf3;padding:20px 15px;position:sticky;top:0;height:100vh;overflow:auto}
.brand{display:flex;gap:10px;align-items:center;padding:4px 6px 22px}.logo{width:42px;height:42px;border-radius:11px;background:#fff;color:var(--navy);display:grid;place-items:center;font-weight:900}.brand b{font-size:14px;line-height:1.25}.brand small{display:block;color:#9eb9ca;margin-top:3px}
.navtitle{font-size:10px;letter-spacing:1.2px;text-transform:uppercase;color:#779ab1;margin:17px 9px 7px}.nav{display:block;width:100%;padding:10px;border:0;border-radius:8px;font-size:12px;margin:3px 0;text-align:left;background:transparent;color:#dceaf3;cursor:pointer}.nav:hover,.nav.active{background:#173b59;color:#fff}.nav .navcount{float:right;background:#294e69;border-radius:99px;padding:1px 6px;font-size:9px}.health{margin-top:24px;border:1px solid #244660;border-radius:11px;padding:12px;background:#0d2940;font-size:11px;line-height:1.5;color:#b9cdda}
main{min-width:0}header{height:68px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:16px;padding:0 26px;position:sticky;top:0;z-index:5}header h1{font-size:17px;margin:0;min-width:155px}.search{flex:1;max-width:650px}.search input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:#f8fafb}.run{margin-left:auto;font-size:11px;color:var(--muted);white-space:nowrap}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#28a664;margin-right:6px}.dot.bad{background:#cf3f35}
.content{padding:24px 27px 55px}.hero{display:flex;justify-content:space-between;gap:20px;margin-bottom:14px}.hero h2{font-size:25px;margin:0 0 6px}.hero p{font-size:13px;color:var(--muted);max-width:830px;line-height:1.5;margin:0}.pill{font-size:10px;font-weight:800;border-radius:99px;padding:5px 8px;background:#e8f2f8;color:#175f88;white-space:nowrap;height:max-content}
.segmented{display:flex;gap:5px;flex-wrap:wrap;margin:12px 0 10px}.segmented.lifecycle{margin-top:0;margin-bottom:17px}.segment{border:1px solid var(--line);background:#fff;color:#35566e;border-radius:99px;padding:8px 12px;font-size:10.5px;font-weight:800;cursor:pointer}.segment:hover,.segment.active{background:var(--navy2);border-color:var(--navy2);color:#fff}.segment.direct.active{background:#175f88;border-color:#175f88}.segment.indirect.active{background:var(--violet);border-color:var(--violet)}.segment.new.active{background:#20845a;border-color:#20845a}.segment.upcoming.active{background:#c85f00;border-color:#c85f00}.segment.activeflow.active{background:#2d5f88;border-color:#2d5f88}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:17px 0}.kpi{background:#fff;border:1px solid var(--line);border-radius:12px;padding:15px}.kpi .label{font-size:10px;text-transform:uppercase;color:var(--muted);letter-spacing:.45px}.kpi .value{font-size:27px;font-weight:850;margin:8px 0 4px}.kpi .note{font-size:10px;color:var(--muted)}
.analytics-grid{display:grid;grid-template-columns:minmax(260px,.65fr) minmax(480px,1.35fr);gap:13px;margin-bottom:14px}.panel{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}.panel.compact{padding:14px}.panel-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.panel h3{font-size:14px;margin:0 0 4px}.sub{font-size:10px;color:var(--muted);margin-bottom:12px}.impact-bars{display:flex;flex-direction:column;gap:7px}.barrow{display:grid;grid-template-columns:118px 1fr 28px;gap:7px;align-items:center;font-size:9px}.barlabel{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.track{height:7px;background:#e9eff3;border-radius:99px;overflow:hidden}.fill{height:100%;background:linear-gradient(90deg,#42a3c6,#174f76);border-radius:99px}.small-action{border:0;background:#eef5f9;color:#1c638c;border-radius:7px;padding:6px 8px;font-size:9px;font-weight:800;cursor:pointer}
.temporal-wrap{overflow-x:auto;padding-bottom:4px}.temporal-chart{min-width:500px;height:220px;display:grid;grid-template-columns:40px 1fr;grid-template-rows:1fr 30px}.y-axis{grid-row:1;display:flex;flex-direction:column;justify-content:space-between;align-items:flex-end;padding:0 7px 4px 0;font-size:8px;color:var(--muted)}.plot{grid-column:2;grid-row:1;position:relative;border-left:1px solid var(--line);border-bottom:1px solid var(--line);background:repeating-linear-gradient(to bottom,transparent 0,transparent calc(25% - 1px),#edf2f5 25%)}.month-bars{position:absolute;inset:0;display:flex;align-items:flex-end;gap:7px;padding:0 10px}.month-group{height:100%;flex:1;min-width:28px;display:flex;align-items:flex-end;justify-content:center;gap:3px}.month-bar{width:min(13px,38%);min-height:0;border-radius:4px 4px 0 0;cursor:pointer}.month-bar.direct{background:var(--blue)}.month-bar.indirect{background:var(--violet)}.month-bar:hover{filter:brightness(.88)}.x-axis{grid-column:2;grid-row:2;display:flex;gap:7px;padding:5px 10px 0}.month-label{flex:1;min-width:28px;text-align:center;font-size:8px;color:var(--muted);transform:rotate(-35deg);transform-origin:top center;white-space:nowrap}.legend{display:flex;gap:13px;align-items:center;font-size:9px;color:var(--muted);margin-top:7px}.legend span:before{content:"";display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}.legend .ld:before{background:var(--blue)}.legend .li:before{background:var(--violet)}
.secondary-grid{display:grid;grid-template-columns:1.05fr .95fr;gap:13px;margin-bottom:14px}.alerts-list{max-height:310px;overflow:auto}.alert{border-left:4px solid var(--blue);padding:9px 10px;background:#f7fafc;border-radius:7px;margin:8px 0;cursor:pointer}.alert.Crítica{border-left-color:var(--critical);background:#fff5f4}.alert.Alta{border-left-color:var(--high);background:#fff8ef}.alert.level2{border-left-color:var(--violet)}.alert b{font-size:10.5px;display:block}.alert span{font-size:10px;color:var(--muted);line-height:1.35}.alerttime{font-size:8.5px!important;color:#8292a0!important;margin-top:4px;display:block}
.area-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.area-card{border:1px solid var(--line);border-radius:9px;padding:9px}.area-card strong{font-size:10.5px}.area-card small{display:block;color:var(--muted);font-size:9px;margin-top:4px}.area-meter{height:5px;background:#e9eff3;border-radius:99px;margin-top:7px;overflow:hidden}.area-meter div{height:100%;background:linear-gradient(90deg,#55a7c5,#235679)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:14px 0 10px}select{padding:8px 9px;border:1px solid var(--line);border-radius:8px;background:white;font-size:11px}.toolbar .spacer{flex:1}.count{font-size:11px;color:var(--muted)}
.tablewrap{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:auto}table{width:100%;border-collapse:collapse;min-width:980px}th{background:#f7f9fb;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.5px;text-align:left;padding:10px;border-bottom:1px solid var(--line)}td{padding:11px 10px;border-bottom:1px solid #edf1f4;font-size:11px;vertical-align:top}tr:hover{background:#f8fbfd}.title{font-weight:750;font-size:11.5px;margin-bottom:4px}.bulletin{color:var(--blue);font-weight:800;font-size:9.5px}.badge{display:inline-block;padding:4px 7px;border-radius:99px;font-size:9px;font-weight:800}.badge.Crítica{background:#fde8e6;color:var(--critical)}.badge.Alta{background:#fff0df;color:#ae5200}.badge.Media{background:#fff6d8;color:#7c6100}.badge.Baja{background:#e8f4ec;color:#287143}.badge.life-new{background:#e5f5eb;color:#23734d}.badge.life-upcoming{background:#fff0df;color:#a94f00}.badge.life-active{background:#e7f0fb;color:#214f78}.level1{background:#e7f0fb;color:#164e7c}.level2{background:#eee9fb;color:#5b4298}.tags{display:flex;flex-wrap:wrap;gap:4px;max-width:310px}.tag{background:#edf4f8;color:#345a73;border-radius:5px;padding:3px 5px;font-size:8.5px}.details-btn{border:0;border-radius:7px;padding:6px 8px;background:#e7f2f8;color:#155e87;font-weight:750;font-size:9.5px;cursor:pointer}
.audit-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:13px;margin-top:14px}.source-table{width:100%;min-width:0}.source-table th,.source-table td{font-size:9.5px}.status-ok{color:var(--green);font-weight:800}.status-bad{color:var(--critical);font-weight:800}.health-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.health-card{border:1px solid var(--line);border-radius:9px;padding:10px}.health-card b{font-size:10px}.health-card div{font-size:18px;font-weight:850;margin:6px 0}.health-card small{font-size:8.5px;color:var(--muted)}
.modal{position:fixed;inset:0;background:#081521ad;display:none;justify-content:flex-end;z-index:20}.modal.open{display:flex}.drawer{width:min(720px,94vw);height:100%;background:white;overflow:auto}.dhead{background:linear-gradient(135deg,var(--navy),var(--navy2));color:white;padding:22px;position:relative}.close{position:absolute;right:16px;top:15px;background:#ffffff24;color:white;width:32px;height:32px;border:0;border-radius:7px;cursor:pointer}.dhead h2{font-size:21px;margin:7px 40px 6px 0}.dhead p{font-size:11px;color:#bfd2df;line-height:1.45}.dmeta{display:flex;gap:6px;flex-wrap:wrap;margin-top:11px}.dmeta span{background:#ffffff1c;border-radius:99px;padding:5px 7px;font-size:9px}.dbody{padding:20px 23px 35px}.section{margin-bottom:21px}.section h4{font-size:10px;text-transform:uppercase;letter-spacing:.55px;color:#496376;margin:0 0 9px}.callout{border-left:4px solid var(--blue);background:#f0f7fb;border-radius:7px;padding:11px;font-size:11.5px;line-height:1.5}.impactgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.impact{border:1px solid var(--line);border-radius:8px;padding:9px}.impact b{font-size:10px}.impact small{display:block;color:var(--muted);line-height:1.35;margin-top:4px}ul,ol{padding-left:18px}li{font-size:11.5px;line-height:1.45;margin:6px 0}a{color:var(--blue)}.empty{padding:28px;text-align:center;color:var(--muted);font-size:11px}.foot{font-size:9.5px;color:var(--muted);line-height:1.45;margin-top:12px}.anchor{scroll-margin-top:82px}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}.analytics-grid,.secondary-grid,.audit-grid{grid-template-columns:1fr}}
@media(max-width:760px){.shell{grid-template-columns:1fr}.sidebar{display:none}header{padding:0 14px}header h1{display:none}.content{padding:17px}.kpis{grid-template-columns:repeat(2,1fr)}.hero{display:block}.analytics-grid{grid-template-columns:1fr}.area-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="shell">
<aside class="sidebar">
  <div class="brand"><div class="logo">UAF</div><div><b>Observatorio Legislativo<br>Estratégico</b><small>Ley N° 19.913</small></div></div>
  <div class="navtitle">Vigilancia</div>
  <button class="nav active" data-nav="dashboard" onclick="navigate('dashboard',this)">Panel estratégico</button>
  <button class="nav" data-nav="new" onclick="navigate('new',this)">Nuevas / ingreso reciente <span class="navcount" id="navNew">0</span></button>
  <button class="nav" data-nav="upcoming" onclick="navigate('upcoming',this)">Próximos hitos <span class="navcount" id="navUpcoming">0</span></button>
  <button class="nav" data-nav="active" onclick="navigate('active',this)">En tramitación <span class="navcount" id="navActive">0</span></button>
  <button class="nav" data-nav="direct" onclick="navigate('direct',this)">Modificaciones directas <span class="navcount" id="navDirect">0</span></button>
  <button class="nav" data-nav="indirect" onclick="navigate('indirect',this)">Impactos legales indirectos <span class="navcount" id="navIndirect">0</span></button>
  <div class="navtitle">Decisión</div>
  <button class="nav" data-nav="impact" onclick="navigate('impact',this)">Matriz de impactos</button>
  <button class="nav" data-nav="alerts" onclick="navigate('alerts',this)">Alertas y cambios <span class="navcount" id="navAlerts">0</span></button>
  <button class="nav" data-nav="areas" onclick="navigate('areas',this)">Áreas responsables</button>
  <div class="navtitle">Control</div>
  <button class="nav" data-nav="audit" onclick="navigate('audit',this)">Auditoría de fuentes</button>
  <button class="nav" data-nav="health" onclick="navigate('health',this)">Salud del monitor</button>
  <div class="health" id="sideHealth"></div>
</aside>
<main>
<header><h1 id="headerTitle">Panel estratégico</h1><div class="search"><input id="q" placeholder="Buscar boletín, iniciativa, impacto o materia…"></div><div class="run"><span class="dot" id="runDot"></span><span id="lastRun"></span></div></header>
<div class="content">
<section class="hero anchor" id="dashboardSection"><div><h2>Cartera legislativa vigente con impacto UAF</h2><p>El panel publica únicamente iniciativas nuevas, con próximos hitos o con actividad legislativa reciente. Excluye leyes ya publicadas, proyectos terminados, archivados, retirados y antecedentes sin movimiento vigente, aunque aparezcan en catálogos históricos asociados a la Ley 19.913.</p></div><span class="pill">Solo tramitación vigente</span></section>
<div class="segmented" id="noveltyButtons">
  <button class="segment active" data-level="" onclick="setNoveltyFilter('',this)">Todas las novedades</button>
  <button class="segment direct" data-level="1" onclick="setNoveltyFilter('1',this)">Modifican Ley 19.913</button>
  <button class="segment indirect" data-level="2" onclick="setNoveltyFilter('2',this)">Otros cambios normativos</button>
</div>
<div class="segmented lifecycle" id="lifecycleButtons">
  <button class="segment active" data-life="" onclick="setLifecycleFilter('',this)">Todas las vigentes</button>
  <button class="segment new" data-life="new" onclick="setLifecycleFilter('new',this)">Nuevas / ingreso reciente</button>
  <button class="segment upcoming" data-life="upcoming" onclick="setLifecycleFilter('upcoming',this)">Próximo hito</button>
  <button class="segment activeflow" data-life="active" onclick="setLifecycleFilter('active',this)">En tramitación</button>
</div>
<section class="kpis">
  <div class="kpi"><div class="label">Iniciativas vigentes</div><div class="value" id="kTotal">0</div><div class="note">Sin antecedentes históricos</div></div>
  <div class="kpi"><div class="label">Nuevas / ingreso reciente</div><div class="value" id="kNew">0</div><div class="note">Dentro de ventana configurada</div></div>
  <div class="kpi"><div class="label">Próximo hito</div><div class="value" id="kUpcoming">0</div><div class="note">Urgencia, votación o cambio próximo</div></div>
  <div class="kpi"><div class="label">Modificación directa</div><div class="value" id="kDirect">0</div><div class="note">Ley 19.913 / UAF</div></div>
  <div class="kpi"><div class="label">Impacto potencial</div><div class="value" id="kIndirect">0</div><div class="note">Normativa relacionada</div></div>
</section>
<section class="analytics-grid anchor" id="impactSection">
  <div class="panel compact"><div class="panel-head"><div><h3>Exposición por dimensión</h3><div class="sub">Principales impactos del filtro activo</div></div><button class="small-action" onclick="clearImpact()">Limpiar</button></div><div class="impact-bars" id="impactBars"></div></div>
  <div class="panel anchor" id="temporalSection"><div class="panel-head"><div><h3>Análisis temporal de movimientos</h3><div class="sub">Movimientos detectados por año-mes, diferenciados por vinculación normativa</div></div><span class="pill" id="temporalTotal">0 movimientos</span></div><div class="temporal-wrap"><div class="temporal-chart" id="temporalChart"></div></div><div class="legend"><span class="ld">Modificación directa Ley 19.913</span><span class="li">Otros cambios normativos</span></div></div>
</section>
<section class="secondary-grid">
  <div class="panel anchor" id="alertsSection"><div class="panel-head"><div><h3>Novedades y alertas detectadas</h3><div class="sub">Historial acumulado, ordenado desde el cambio más reciente</div></div><span class="pill" id="alertCount">0</span></div><div class="alerts-list" id="alertList"></div></div>
  <div class="panel anchor" id="areasSection"><div class="panel-head"><div><h3>Áreas UAF potencialmente responsables</h3><div class="sub">Estimación derivada de las dimensiones de impacto</div></div></div><div class="area-grid" id="areaGrid"></div></div>
</section>
<section class="anchor" id="projectsSection">
  <div class="toolbar">
    <select id="level"><option value="">Nivel 1 y nivel 2</option><option value="1">Modificación directa Ley 19.913</option><option value="2">Otros cambios normativos</option></select>
    <select id="lifecycle"><option value="">Todas las vigentes</option><option value="new">Nuevas / ingreso reciente</option><option value="upcoming">Próximo hito</option><option value="active">En tramitación activa</option></select>
    <select id="priority"><option value="">Todas las prioridades</option><option>Crítica</option><option>Alta</option><option>Media</option><option>Baja</option></select>
    <select id="impact"><option value="">Todas las dimensiones</option></select>
    <div class="spacer"></div><span class="count" id="resultCount"></span>
  </div>
  <div class="tablewrap"><table><thead><tr><th>Iniciativa agrupada</th><th>Vigencia</th><th>Vinculación LA/FT</th><th>Último trámite oficial</th><th>Prioridad</th><th>Tópicos LA/FT</th><th>Probabilidad</th><th></th></tr></thead><tbody id="rows"></tbody></table></div>
</section>
<section class="audit-grid">
  <div class="panel anchor" id="auditSection"><div class="panel-head"><div><h3>Auditoría de fuentes</h3><div class="sub">Trazabilidad de fuentes oficiales consultadas</div></div></div><div id="sourceAudit"></div></div>
  <div class="panel anchor" id="healthSection"><div class="panel-head"><div><h3>Salud del monitor</h3><div class="sub">Resultado técnico de la última ejecución</div></div></div><div class="health-grid" id="healthGrid"></div><div class="foot" id="healthNote"></div></div>
</section>
<div class="foot">El panel excluye proyectos terminados o sin vigencia reciente. La clasificación de impacto es una inferencia automatizada. Debe validarse jurídicamente antes de adoptar decisiones institucionales. Cada ficha conserva vínculos a sus fuentes oficiales.</div>
</div>
</main>
</div>
<div class="modal" id="modal" onclick="if(event.target===this)closeModal()"><aside class="drawer"><div class="dhead"><button class="close" onclick="closeModal()">✕</button><div class="bulletin" id="dBulletin" style="color:#85cdec"></div><h2 id="dTitle"></h2><p id="dState"></p><div class="dmeta" id="dMeta"></div></div><div class="dbody" id="dBody"></div></aside></div>
<script>
const projects=__PROJECTS_JSON__;
const alerts=__ALERTS_JSON__;
const status=__STATUS_JSON__;
let current=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
const impactAreas={
 'Delitos base':['Inteligencia Financiera','Jurídica','Analítica Estratégica'],
 'Sujetos obligados':['Fiscalización','Registro y Difusión','Tecnología'],
 'Responsabilidades UAF':['Dirección','Jurídica','Operaciones'],
 'Acceso a información':['Tecnología y Datos','Jurídica','Auditoría'],
 'Reportes y operaciones':['Tecnología y Datos','Inteligencia Financiera','Fiscalización'],
 'Fiscalización y sanciones':['Fiscalización','Jurídica','Dirección'],
 'Tecnología y datos':['Tecnología y Datos','Ciberseguridad','Gobernanza de Datos'],
 'Presupuesto y dotación':['Administración y Finanzas','Personas','Dirección'],
 'Cooperación institucional':['Cooperación Interinstitucional','Dirección','Jurídica']
};
function dateValue(value){if(!value)return null;const s=String(value).trim();let m=s.match(/^(\d{4})-(\d{2})-(\d{2})/);if(m)return new Date(+m[1],+m[2]-1,+m[3]);m=s.match(/^(\d{2})[\/-](\d{2})[\/-](\d{4})/);if(m)return new Date(+m[3],+m[2]-1,+m[1]);const d=new Date(s);return isNaN(d)?null:d}
function monthKey(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`}
function monthLabel(k){const [y,m]=k.split('-');return `${m}/${String(y).slice(2)}`}
function filterLevel(){return document.getElementById('level').value}
function filterLifecycle(){return document.getElementById('lifecycle').value}
function baseFilteredProjects(){const q=document.getElementById('q').value.toLowerCase().trim(),level=filterLevel(),life=filterLifecycle(),priority=document.getElementById('priority').value,impact=document.getElementById('impact').value;return projects.filter(p=>{const hay=[p.bulletin,p.title,p.initiative_name,p.initiative_group_name,p.state,p.stage,p.commission,p.latest_movement,p.analysis_summary,p.linkage_summary,p.document_summary,p.lifecycle_status,...(p.laft_topics||[]),...(p.group_bulletins||[]),...Object.keys(p.impacts||{})].join(' ').toLowerCase();return p.is_current!==false&&(!q||hay.includes(q))&&(!level||String(p.relevance_level)===level)&&(!life||(p.lifecycle_flags||[]).includes(life))&&(!priority||p.priority===priority)&&(!impact||(p.impacts||{})[impact])})}
function setActiveNav(button){document.querySelectorAll('.nav').forEach(b=>b.classList.remove('active'));if(button)button.classList.add('active')}
function navigate(action,button){setActiveNav(button);const titles={dashboard:'Panel estratégico',new:'Nuevas iniciativas',upcoming:'Próximos hitos legislativos',active:'Iniciativas en tramitación',direct:'Modificaciones directas',indirect:'Impactos legales indirectos',impact:'Matriz de impactos',alerts:'Alertas y cambios',areas:'Áreas responsables',audit:'Auditoría de fuentes',health:'Salud del monitor'};document.getElementById('headerTitle').textContent=titles[action]||'Panel estratégico';if(action==='dashboard'){setNoveltyFilter('',document.querySelector('#noveltyButtons .segment[data-level=""]'));setLifecycleFilter('',document.querySelector('#lifecycleButtons .segment[data-life=""]'));document.getElementById('dashboardSection').scrollIntoView()}if(['new','upcoming','active'].includes(action)){setLifecycleFilter(action,document.querySelector(`#lifecycleButtons .segment[data-life="${action}"]`));document.getElementById('projectsSection').scrollIntoView()}if(action==='direct'){setNoveltyFilter('1',document.querySelector('#noveltyButtons .segment[data-level="1"]'));document.getElementById('projectsSection').scrollIntoView()}if(action==='indirect'){setNoveltyFilter('2',document.querySelector('#noveltyButtons .segment[data-level="2"]'));document.getElementById('projectsSection').scrollIntoView()}if(action==='impact')document.getElementById('impactSection').scrollIntoView();if(action==='alerts')document.getElementById('alertsSection').scrollIntoView();if(action==='areas')document.getElementById('areasSection').scrollIntoView();if(action==='audit')document.getElementById('auditSection').scrollIntoView();if(action==='health')document.getElementById('healthSection').scrollIntoView()}
function setNoveltyFilter(level,button){document.getElementById('level').value=level;document.querySelectorAll('#noveltyButtons .segment').forEach(b=>b.classList.remove('active'));if(button)button.classList.add('active');renderAll()}
function setLifecycleFilter(value,button){document.getElementById('lifecycle').value=value;document.querySelectorAll('#lifecycleButtons .segment').forEach(b=>b.classList.remove('active'));if(button)button.classList.add('active');renderAll()}
function syncSegments(){const level=filterLevel();document.querySelectorAll('#noveltyButtons .segment').forEach(b=>b.classList.toggle('active',b.dataset.level===level))}
function syncLifecycleSegments(){const life=filterLifecycle();document.querySelectorAll('#lifecycleButtons .segment').forEach(b=>b.classList.toggle('active',b.dataset.life===life))}
function clearImpact(){document.getElementById('impact').value='';renderAll()}
function initFilters(){const names=[...new Set(projects.flatMap(p=>Object.keys(p.impacts||{})))].sort();document.getElementById('impact').innerHTML='<option value="">Todas las dimensiones</option>'+names.map(x=>`<option>${esc(x)}</option>`).join('')}
function groupedProjects(){const map=new Map();baseFilteredProjects().forEach(p=>{const key=p.initiative_group_id||p.bulletin;const item=map.get(key)||{key,members:[],primary:p};item.members.push(p);const pd=dateValue(p.latest_movement_date||p.reference_date),cd=dateValue(item.primary.latest_movement_date||item.primary.reference_date);if((p.priority_score||0)>(item.primary.priority_score||0)||((p.priority_score||0)===(item.primary.priority_score||0)&&pd&&(!cd||pd>cd)))item.primary=p;map.set(key,item)});return [...map.values()].sort((a,b)=>(b.primary.priority_score||0)-(a.primary.priority_score||0))}
function renderKpis(){const current=projects.filter(p=>p.is_current!==false),groups=new Set(current.map(p=>p.initiative_group_id||p.bulletin));document.getElementById('kTotal').textContent=groups.size;document.getElementById('kNew').textContent=current.filter(p=>(p.lifecycle_flags||[]).includes('new')).length;document.getElementById('kUpcoming').textContent=current.filter(p=>(p.lifecycle_flags||[]).includes('upcoming')).length;document.getElementById('kDirect').textContent=current.filter(p=>p.relevance_level===1).length;document.getElementById('kIndirect').textContent=current.filter(p=>p.relevance_level===2).length;document.getElementById('navNew').textContent=current.filter(p=>(p.lifecycle_flags||[]).includes('new')).length;document.getElementById('navUpcoming').textContent=current.filter(p=>(p.lifecycle_flags||[]).includes('upcoming')).length;document.getElementById('navActive').textContent=current.filter(p=>(p.lifecycle_flags||[]).includes('active')).length;document.getElementById('navDirect').textContent=current.filter(p=>p.relevance_level===1).length;document.getElementById('navIndirect').textContent=current.filter(p=>p.relevance_level===2).length;document.getElementById('navAlerts').textContent=alerts.length}
function renderImpactBars(){const totals={};baseFilteredProjects().forEach(p=>Object.entries(p.impacts||{}).forEach(([name,v])=>totals[name]=(totals[name]||0)+(v.score||0)));const sorted=Object.entries(totals).sort((a,b)=>b[1]-a[1]).slice(0,6),max=Math.max(1,...sorted.map(x=>x[1]));document.getElementById('impactBars').innerHTML=sorted.length?sorted.map(([name,value])=>`<div class="barrow" title="${esc(name)}: ${value}"><span class="barlabel">${esc(name)}</span><div class="track"><div class="fill" style="width:${value/max*100}%"></div></div><b>${value}</b></div>`).join(''):'<div class="empty">Sin impactos para el filtro activo.</div>'}
function eventRows(){const out=[],seen=new Set();alerts.forEach(a=>{const d=dateValue(a.official_movement_date);if(!d)return;const group=a.initiative_group_id||a.bulletin,key=`${group}|${d.toISOString().slice(0,10)}|${String(a.official_movement_text||'').slice(0,80)}`;if(seen.has(key))return;seen.add(key);out.push({date:d,month:monthKey(d),level:+a.relevance_level||2,bulletin:a.bulletin,group,source:a.movement_source||'fuente oficial'})});projects.forEach(p=>{const d=dateValue(p.latest_movement_date||p.entry_date);if(!d)return;const group=p.initiative_group_id||p.bulletin,key=`${group}|${d.toISOString().slice(0,10)}|${String(p.latest_movement||'').slice(0,80)}`;if(seen.has(key))return;seen.add(key);out.push({date:d,month:monthKey(d),level:+p.relevance_level||2,bulletin:p.bulletin,group,source:p.metadata?.movement_source||'fuente oficial'})});return out}
function continuousMonths(keys){if(!keys.length)return[];let [sy,sm]=keys[0].split('-').map(Number),[ey,em]=keys[keys.length-1].split('-').map(Number);let d=new Date(sy,sm-1,1),end=new Date(ey,em-1,1),arr=[];while(d<=end){arr.push(monthKey(d));d=new Date(d.getFullYear(),d.getMonth()+1,1)}return arr.slice(-18)}
function renderTemporal(){const level=filterLevel(),events=eventRows().filter(e=>!level||String(e.level)===level),bucket={};events.forEach(e=>{bucket[e.month]??={direct:0,indirect:0};bucket[e.month][e.level===1?'direct':'indirect']++});const months=continuousMonths(Object.keys(bucket).sort());const max=Math.max(1,...months.flatMap(m=>[bucket[m]?.direct||0,bucket[m]?.indirect||0]));const ticks=[max,Math.round(max*.75),Math.round(max*.5),Math.round(max*.25),0];document.getElementById('temporalTotal').textContent=`${events.length} movimiento${events.length===1?'':'s'}`;if(!months.length){document.getElementById('temporalChart').innerHTML='<div class="empty" style="grid-column:1/3">Aún no hay fechas de movimientos. El gráfico se completará con las ejecuciones automáticas.</div>';return}document.getElementById('temporalChart').innerHTML=`<div class="y-axis">${ticks.map(x=>`<span>${x}</span>`).join('')}</div><div class="plot"><div class="month-bars">${months.map(m=>{const v=bucket[m]||{direct:0,indirect:0};return `<div class="month-group"><div class="month-bar direct" title="${m} · Directas: ${v.direct}" style="height:${v.direct?Math.max(5,v.direct/max*100):0}%"></div><div class="month-bar indirect" title="${m} · Otros cambios: ${v.indirect}" style="height:${v.indirect?Math.max(5,v.indirect/max*100):0}%"></div></div>`}).join('')}</div></div><div class="x-axis">${months.map(m=>`<span class="month-label">${monthLabel(m)}</span>`).join('')}</div>`}
function filteredAlerts(){const level=filterLevel(),allowed=new Set(baseFilteredProjects().map(p=>p.bulletin));return alerts.filter(a=>allowed.has(a.bulletin)&&(!level||String(a.relevance_level)===level)).sort((a,b)=>(dateValue(b.detected_at)||0)-(dateValue(a.detected_at)||0))}
function renderAlerts(){const list=filteredAlerts();document.getElementById('alertCount').textContent=list.length;document.getElementById('alertList').innerHTML=list.length?list.slice(0,30).map(a=>`<div class="alert ${esc(a.severity)} ${a.relevance_level===2?'level2':''}" onclick="openProject('${esc(a.bulletin)}')"><b>${esc(a.severity)} · Boletín ${esc(a.bulletin)}</b><span>${esc(a.initiative_name||a.title||'Iniciativa legislativa')}</span><span>${esc(a.linkage_summary||'')}</span><span class="alerttime">${esc(a.detected_at||'Fecha no disponible')} · ${a.relevance_level===1?'Ley 19.913':'Otro cambio normativo'}</span></div>`).join(''):'<div class="empty">No existen alertas acumuladas para el filtro seleccionado.</div>'}
function renderAreas(){const totals={};baseFilteredProjects().forEach(p=>Object.entries(p.impacts||{}).forEach(([impact,payload])=>(impactAreas[impact]||['Área técnica por definir']).forEach(area=>totals[area]=(totals[area]||0)+(payload.level||1))));const sorted=Object.entries(totals).sort((a,b)=>b[1]-a[1]).slice(0,8),max=Math.max(1,...sorted.map(x=>x[1]));document.getElementById('areaGrid').innerHTML=sorted.length?sorted.map(([area,value])=>`<div class="area-card"><strong>${esc(area)}</strong><small>Exposición estimada: ${value} puntos</small><div class="area-meter"><div style="width:${value/max*100}%"></div></div></div>`).join(''):'<div class="empty">Sin áreas para el filtro activo.</div>'}
function lifeClass(p){return p.lifecycle_code==='new'?'life-new':p.lifecycle_code==='upcoming'?'life-upcoming':'life-active'}
function renderRows(){const groups=groupedProjects(),bulletins=groups.reduce((n,g)=>n+g.members.length,0);document.getElementById('resultCount').textContent=`${groups.length} iniciativa${groups.length===1?'':'s'} · ${bulletins} boletín${bulletins===1?'':'es'}`;document.getElementById('rows').innerHTML=groups.length?groups.map(g=>{const p=g.primary,members=g.members.sort((a,b)=>(dateValue(b.latest_movement_date)||0)-(dateValue(a.latest_movement_date)||0)),name=p.initiative_group_name||p.initiative_name||p.title||'Iniciativa pendiente',bulletinText=members.map(x=>x.bulletin).join(', '),topics=[...new Set(members.flatMap(x=>x.laft_topics||[]))].slice(0,5),latest=members[0]||p;return `<tr><td><div class="title">${esc(name)}</div>${g.members.length>1?`<span class="badge level1" style="margin-top:5px">${g.members.length} boletines agrupados</span>`:''}<div class="bulletin">Boletín${g.members.length>1?'es':''} ${esc(bulletinText)}</div><div style="font-size:9px;color:#718493;margin-top:5px">${esc(p.title||'')}</div></td><td><span class="badge ${lifeClass(latest)}">${esc(latest.lifecycle_status||'En tramitación')}</span><div style="font-size:8.5px;color:#718493;margin-top:5px">${esc(latest.reference_date||'Fecha por verificar')}</div></td><td><span class="badge ${p.relevance_level===1?'level1':'level2'}">${p.relevance_level===1?'Modifica Ley 19.913':'Prevención LA/FT'}</span><div style="font-size:9px;color:#596f81;margin-top:6px;max-width:220px">${esc(p.linkage_summary||'')}</div></td><td><div>${esc(latest.latest_movement_date||'Fecha no disponible')}</div><div style="font-size:9px;color:#718493;margin-top:4px">${esc(latest.latest_movement||latest.stage||latest.state||'Sin movimiento verificado')}</div><div style="font-size:8px;color:#8797a5;margin-top:4px">${esc(latest.metadata?.movement_source||'Fuente oficial Cámara/Senado')}</div></td><td><span class="badge ${esc(p.priority)}">${esc(p.priority)}</span><div style="font-size:9px;margin-top:5px">${p.priority_score||0}/100</div></td><td><div class="tags">${topics.map(x=>`<span class="tag">${esc(x)}</span>`).join('')}</div></td><td>${p.probability||0}%</td><td><button class="details-btn" onclick="openProject('${esc(p.bulletin)}')">Ver iniciativa →</button></td></tr>`}).join(''):'<tr><td colspan="8"><div class="empty">No hay iniciativas vigentes con relación precisa a la Ley 19.913 o a prevención LA/FT.</div></td></tr>'}
function renderAudit(){const domains={};projects.forEach(p=>(p.source_urls||[]).forEach(u=>{try{const host=new URL(u).hostname.replace(/^www\./,'');domains[host]=(domains[host]||0)+1}catch(e){}}));const sourceHealth=status.sources||{};const rows=Object.entries(sourceHealth).map(([name,v])=>`<tr><td>${esc(name)}</td><td class="${v.ok?'status-ok':'status-bad'}">${v.ok?'Disponible':'Con error'}</td><td>${esc(v.items??'—')}</td><td>${esc(v.error||'Consulta completada')}</td></tr>`).join('');const domainsHtml=Object.entries(domains).sort((a,b)=>b[1]-a[1]).map(([d,n])=>`<span class="tag">${esc(d)} · ${n}</span>`).join('');document.getElementById('sourceAudit').innerHTML=`<table class="source-table"><thead><tr><th>Fuente</th><th>Estado</th><th>Registros</th><th>Detalle</th></tr></thead><tbody>${rows||'<tr><td colspan="4">Sin información de ejecución.</td></tr>'}</tbody></table><div class="tags" style="margin-top:10px;max-width:none">${domainsHtml}</div>`}
function renderHealth(){const sources=Object.values(status.sources||{}),ok=sources.filter(x=>x.ok).length,failed=sources.length-ok;document.getElementById('healthGrid').innerHTML=`<div class="health-card"><b>Fuentes disponibles</b><div>${ok}/${sources.length}</div><small>Consultas oficiales completadas</small></div><div class="health-card"><b>Iniciativas LA/FT</b><div>${status.initiative_groups??new Set(projects.map(p=>p.initiative_group_id||p.bulletin)).size}</div><small>Agrupadas en el panel</small></div><div class="health-card"><b>Irrelevantes descartadas</b><div>${status.irrelevant_discarded??0}</div><small>Sin vínculo suficiente con LA/FT</small></div>`;document.getElementById('healthNote').textContent=`${status.eligibility_rule||''} Inicio: ${status.started_at||'—'} · Término: ${status.finished_at||'—'} · Correo: ${status.email_message||'Sin información'}${failed?' · Hay fuentes con error; revise la auditoría.':''}`}
function updateHeader(){const finished=status.finished_at||'Sin primera ejecución';const sources=Object.values(status.sources||{});const allOk=sources.length&&sources.every(x=>x.ok);document.getElementById('lastRun').textContent=`Último barrido: ${finished}`;document.getElementById('runDot').classList.toggle('bad',sources.length>0&&!allOk);document.getElementById('sideHealth').innerHTML=`<b style="color:#fff">Estado del monitor</b><br>Último barrido: ${esc(finished)}<br>Fuentes correctas: ${sources.filter(x=>x.ok).length}/${sources.length}<br>Vigentes: ${status.projects_monitored??projects.length}<br>Descartadas: ${status.excluded_count??0}`}
function openProject(bulletin){current=projects.find(p=>p.bulletin===bulletin);if(!current)return;const group=projects.filter(p=>(p.initiative_group_id||p.bulletin)===(current.initiative_group_id||current.bulletin)).sort((a,b)=>(dateValue(b.latest_movement_date)||0)-(dateValue(a.latest_movement_date)||0)),latest=group[0]||current,allTopics=[...new Set(group.flatMap(p=>p.laft_topics||[]))].slice(0,10);document.getElementById('dBulletin').textContent=`Boletín${group.length>1?'es':''} ${group.map(p=>p.bulletin).join(', ')}`;document.getElementById('dTitle').textContent=current.initiative_group_name||current.initiative_name||current.title||'Iniciativa pendiente';document.getElementById('dState').textContent=[latest.stage,latest.state,latest.commission].filter(Boolean).join(' · ')||'Estado pendiente de verificación';document.getElementById('dMeta').innerHTML=`<span>${latest.lifecycle_status||'En tramitación'}</span><span>${current.relevance_label||''}</span><span>Confianza LA/FT ${current.laft_confidence||0}%</span><span>Prioridad ${current.priority||''}</span><span>${current.priority_score||0}/100</span>`;document.getElementById('dBody').innerHTML=`<div class="section"><h4>Qué propone la iniciativa</h4><div class="callout">${esc(current.document_summary||current.title||'Resumen pendiente de la fuente oficial.')}</div></div><div class="section"><h4>Por qué se vincula con la Ley 19.913 o LA/FT</h4><div class="callout"><b>${esc(current.relevance_level===1?'Impacto directo':'Impacto preventivo relacionado')}</b><br>${esc(current.linkage_summary||current.relevance_reason||'')}</div></div><div class="section"><h4>Principales tópicos detectados</h4><div class="tags" style="max-width:none">${allTopics.map(x=>`<span class="tag">${esc(x)}</span>`).join('')||'<span class="tag">Pendiente de extracción</span>'}</div></div>${group.length>1?`<div class="section"><h4>Boletines agrupados</h4><ul>${group.map(p=>`<li><b>${esc(p.bulletin)}</b> — ${esc(p.title||'Sin título')}</li>`).join('')}</ul></div>`:''}<div class="section"><h4>Último trámite oficial</h4><div class="callout"><b>${esc(latest.latest_movement_date||'Fecha no disponible')}</b> · ${esc(latest.latest_movement||latest.state||'Sin movimiento verificado')}<br><small>${esc(latest.metadata?.movement_source||'Fuente oficial Cámara/Senado')}</small></div></div><div class="section"><h4>Impacto institucional estimado</h4><div class="impactgrid">${(current.top_impacts||[]).map(x=>`<div class="impact"><b>${esc(x.name)} · ${x.level}/5</b><small>${esc((x.hits||[]).slice(0,4).join(', '))}</small><small>${esc(x.recommendation||'')}</small></div>`).join('')||'<div class="empty">Sin dimensiones clasificadas.</div>'}</div></div><div class="section"><h4>Decisiones sugeridas</h4><ol>${(current.decisions||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ol></div><div class="section"><h4>Fuentes oficiales</h4><ul>${[...new Set(group.flatMap(p=>p.source_urls||[]))].map(u=>`<li><a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a></li>`).join('')}</ul><div style="font-size:10px;color:#6b7d8d">Fechas tomadas de movimientos individualizados en las fichas oficiales; se excluyen listados laterales y “últimos vistos”.</div></div>`;document.getElementById('modal').classList.add('open');document.body.style.overflow='hidden'}
function closeModal(){document.getElementById('modal').classList.remove('open');document.body.style.overflow=''}
function renderAll(){syncSegments();syncLifecycleSegments();renderImpactBars();renderTemporal();renderAlerts();renderAreas();renderRows()}
function init(){initFilters();renderKpis();updateHeader();renderAudit();renderHealth();renderAll()}
['q','priority','impact'].forEach(id=>document.getElementById(id).addEventListener(id==='q'?'input':'change',renderAll));document.getElementById('level').addEventListener('change',()=>{syncSegments();renderAll()});document.getElementById('lifecycle').addEventListener('change',()=>{syncLifecycleSegments();renderAll()});document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});init();
</script>
</body>
</html>'''
