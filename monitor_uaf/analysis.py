from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from .models import CandidateProject
from .utils import local_now, normalize_text, parse_legislative_date, stable_hash, unique


IMPACT_RECOMMENDATIONS = {
    "Delitos base": "Actualizar taxonomías, matrices de riesgo, tipologías y fuentes vinculadas al nuevo delito precedente.",
    "Sujetos obligados": "Dimensionar el universo potencial, brechas de inscripción, capacitación, fiscalización y capacidad del portal de reportes.",
    "Responsabilidades UAF": "Definir responsable institucional, procesos, protocolos, controles y capacidad operativa requerida.",
    "Acceso a información": "Diseñar reglas de acceso, trazabilidad, auditoría, seguridad y coordinación con custodios de datos.",
    "Reportes y operaciones": "Estimar volumen, calidad y utilidad de los nuevos reportes; ajustar validaciones y reglas de análisis.",
    "Fiscalización y sanciones": "Revisar modelo supervisor, criterios de riesgo, procedimientos sancionatorios y recursos necesarios.",
    "Tecnología y datos": "Evaluar interoperabilidad, almacenamiento, calidad, ciberseguridad y cambios en sistemas institucionales.",
    "Presupuesto y dotación": "Preparar estimación de costo, perfiles, dotación, licencias, infraestructura y plazo de implementación.",
    "Cooperación institucional": "Definir convenios, responsables, estándares de intercambio y mecanismos de gobernanza interinstitucional.",
}


def _has_any(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if normalize_text(term) in text]


def assess_lifecycle(project: CandidateProject, config: dict[str, Any]) -> dict[str, Any]:
    """Determina vigencia con evidencia oficial y fechas del mismo boletín.

    Una etiqueta histórica de "primer trámite" no basta. Para aparecer en el
    dashboard la iniciativa debe tener ingreso reciente, movimiento legislativo
    verificado dentro de la ventana o una señal vigente de la lista oficial de
    proyectos recientes. Los estados terminales y exclusiones expresas prevalecen.
    """
    today = local_now(config.get("timezone", "America/Santiago")).date()
    exclusions = config.get("excluded_bulletins", {}) or {}
    exclusion_reason = exclusions.get(project.bulletin) if isinstance(exclusions, dict) else (
        "Exclusión configurada" if project.bulletin in exclusions else ""
    )
    if exclusion_reason:
        return {
            "is_current": False,
            "lifecycle_code": "excluded",
            "lifecycle_status": "Antecedente excluido",
            "lifecycle_reason": str(exclusion_reason),
            "lifecycle_flags": [],
            "reference_date": "",
            "recency_days": None,
        }

    metadata = project.metadata or {}
    authoritative = normalize_text(" ".join([
        project.state,
        project.stage,
        project.urgency,
        str(metadata.get("official_registry_status", "") or ""),
    ]))
    terminal_hits = _has_any(authoritative, config.get("terminal_state_terms", []))
    active_hits = _has_any(authoritative, config.get("active_state_terms", []))
    upcoming_hits = _has_any(
        normalize_text(" ".join([project.stage, project.urgency, project.latest_movement])),
        config.get("upcoming_terms", []),
    )

    entry_verified = bool(metadata.get("entry_date_verified"))
    movement_verified = bool(metadata.get("movement_verified"))
    status_verified = bool(metadata.get("official_status_verified"))
    current_list_verified = bool(metadata.get("senate_current_list_verified"))

    entry = parse_legislative_date(project.entry_date) if entry_verified else None
    movement = None
    if movement_verified:
        movement = parse_legislative_date(project.latest_movement_date)
    reference = movement or entry
    recency_days = (today - reference).days if reference else None
    entry_days = (today - entry).days if entry else None

    new_days = int(config.get("new_project_days", 180))
    active_days = int(config.get("active_movement_days", 730))
    recent_entry = entry_days is not None and -31 <= entry_days <= new_days
    recent_movement = movement is not None and recency_days is not None and -31 <= recency_days <= active_days
    historical_cutoff_year = int(config.get("historical_entry_cutoff_year", 2018))
    old_entry_without_recent_movement = bool(
        entry and entry.year < historical_cutoff_year and not recent_movement
    )
    explicit_urgency = (
        status_verified
        and bool(project.urgency.strip())
        and normalize_text(project.urgency) not in {"sin urgencia", "sin urgencia informada", "sin urgencia actual"}
    )

    if terminal_hits and status_verified:
        return {
            "is_current": False,
            "lifecycle_code": "terminal",
            "lifecycle_status": "Tramitación terminada",
            "lifecycle_reason": "La ficha oficial contiene un estado terminal: " + ", ".join(unique(terminal_hits)[:3]),
            "lifecycle_flags": [],
            "reference_date": reference.isoformat() if reference else "",
            "recency_days": recency_days,
        }

    if old_entry_without_recent_movement:
        return {
            "is_current": False,
            "lifecycle_code": "historical",
            "lifecycle_status": "Antecedente histórico",
            "lifecycle_reason": (
                f"El proyecto ingresó antes de {historical_cutoff_year} y no registra "
                f"movimientos oficiales dentro de los últimos {active_days} días."
            ),
            "lifecycle_flags": [],
            "reference_date": reference.isoformat() if reference else "",
            "recency_days": recency_days,
        }

    flags: list[str] = []
    if recent_entry:
        flags.append("new")
    if upcoming_hits and (recent_movement or recent_entry or explicit_urgency or current_list_verified):
        flags.append("upcoming")
    if recent_movement or explicit_urgency or current_list_verified:
        flags.append("active")

    # Con validación obligatoria, no se publica una ficha cuya etapa solo provenga
    # de un catálogo histórico o de una versión anterior sin evidencia actual.
    has_official_evidence = (
        status_verified or movement_verified or current_list_verified
        or (entry_verified and recent_entry)
    )
    if config.get("official_validation_required", True) and not has_official_evidence:
        return {
            "is_current": False,
            "lifecycle_code": "unverified",
            "lifecycle_status": "Vigencia no comprobada",
            "lifecycle_reason": "No fue posible validar la vigencia en una ficha o movimiento oficial del mismo boletín.",
            "lifecycle_flags": [],
            "reference_date": "",
            "recency_days": None,
        }

    if "upcoming" in flags:
        status = "Próximo hito legislativo"
        code = "upcoming"
        reason = "La fuente oficial registra una votación, urgencia, citación, paso de etapa u otro hito próximo."
    elif "new" in flags:
        status = "Nueva / ingreso reciente"
        code = "new"
        reason = f"La iniciativa ingresó dentro de los últimos {new_days} días."
    elif "active" in flags:
        status = "En tramitación activa"
        code = "active"
        if current_list_verified and not recent_movement:
            reason = "La lista oficial del Senado la mantiene entre los proyectos recientes en tramitación."
        else:
            reason = f"Registra actividad legislativa fechada y verificada dentro de los últimos {active_days} días."
    else:
        if movement and recency_days is not None and recency_days > active_days:
            code = "stale"
            status = "Sin actividad reciente"
            reason = f"No registra movimientos legislativos verificados dentro de los últimos {active_days} días."
        elif active_hits and status_verified:
            code = "stale"
            status = "Sin actividad reciente"
            reason = "La ficha conserva una etapa formalmente abierta, pero no registra ingreso o movimiento reciente dentro de la ventana configurada."
        else:
            code = "historical"
            status = "Antecedente histórico"
            reason = "No existe evidencia oficial suficiente de ingreso reciente o actividad legislativa vigente."
        return {
            "is_current": False,
            "lifecycle_code": code,
            "lifecycle_status": status,
            "lifecycle_reason": reason,
            "lifecycle_flags": [],
            "reference_date": reference.isoformat() if reference else "",
            "recency_days": recency_days,
        }

    return {
        "is_current": True,
        "lifecycle_code": code,
        "lifecycle_status": status,
        "lifecycle_reason": reason,
        "lifecycle_flags": unique(flags),
        "reference_date": reference.isoformat() if reference else "",
        "recency_days": recency_days,
    }


def _matter_profile(project: CandidateProject, relevance_level: int, impacts: dict[str, dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    """Construye una lectura material separada del último movimiento legislativo."""
    title = project.title.strip()
    normalized = normalize_text(" ".join([title, project.evidence_text]))
    promoters = unique(project.metadata.get("promoters", []) if isinstance(project.metadata.get("promoters", []), list) else [project.metadata.get("promoters", "")])
    areas: list[str] = []

    mapping = [
        (("ley 19.913", "unidad de analisis financiero", "uaf"), "Ley N.º 19.913 y estatuto orgánico de la UAF"),
        (("articulo 3", "sujeto obligado", "entidad reportante"), "Sujetos obligados, deberes de reporte e inscripción"),
        (("articulo 27", "delito precedente", "delitos base"), "Catálogo de delitos precedentes del lavado de activos"),
        (("comercio ilegal", "contrabando", "mercaderias falsificadas", "propiedad industrial"), "Comercio ilícito, contrabando y falsificación"),
        (("secreto bancario", "reserva bancaria", "informacion bancaria"), "Acceso y reserva de información financiera"),
        (("dinero en efectivo", "transacciones en efectivo"), "Límites al efectivo y trazabilidad de medios de pago"),
        (("remesa", "transferencia de dinero"), "Remesas y transferencias transfronterizas"),
        (("activo virtual", "criptoactivo", "fintech"), "Activos virtuales y servicios financieros digitales"),
        (("decomiso", "comiso"), "Decomiso y recuperación de activos"),
        (("sancion", "multa", "fiscalizacion"), "Fiscalización y régimen sancionatorio"),
        (("intercambio de informacion", "interoperabilidad", "inteligencia economica"), "Intercambio de información y coordinación interinstitucional"),
    ]
    for terms, label in mapping:
        if any(term in normalized for term in terms):
            areas.append(label)
    areas.extend(name for name in impacts if name not in areas)
    areas = unique(areas)[:10]

    if "reconstruccion nacional" in normalized and ("unidad de analisis financiero" in normalized or "operacion sospechosa" in normalized):
        matter = (
            "La iniciativa contiene un paquete amplio de reconstrucción y desarrollo económico. Dentro de su tramitación "
            "se incorporaron disposiciones que exigen a bancos analizar determinadas operaciones y reportar a la Unidad de "
            "Análisis Financiero aquellas que resulten sospechosas, además de mecanismos de colaboración e intercambio de "
            "información con organismos públicos. Su impacto UAF no surge del título, sino de indicaciones y textos posteriores."
        )
    elif "comercio ilegal" in normalized:
        matter = (
            "La iniciativa busca fortalecer la prevención y sanción del lavado de activos vinculado al comercio ilegal. "
            "Su foco es seguir la ruta financiera de cadenas de contrabando, falsificación y comercialización ilícita, "
            "incorporando o reforzando deberes preventivos y herramientas de análisis bajo la Ley N.º 19.913."
        )
    elif "propiedad industrial" in normalized:
        matter = (
            "La iniciativa propone incorporar delitos contra la propiedad industrial al catálogo de delitos precedentes "
            "del lavado de activos, conectando la falsificación y comercialización fraudulenta con el análisis patrimonial."
        )
    elif "inteligencia economica" in normalized:
        matter = (
            "La iniciativa crea o fortalece un sistema de inteligencia económica para enfrentar el crimen organizado, "
            "con efectos sobre las facultades de análisis, el acceso a información y la coordinación de la UAF con otros organismos."
        )
    elif "dinero en efectivo" in normalized or "transacciones en efectivo" in normalized:
        matter = (
            "La iniciativa regula operaciones de alto valor realizadas en efectivo para aumentar la trazabilidad de los pagos "
            "y reducir espacios de ocultamiento o fraccionamiento de fondos de origen ilícito."
        )
    elif "secreto bancario" in normalized or "reserva bancaria" in normalized:
        matter = (
            "La iniciativa modifica el procedimiento o las condiciones de acceso a información bancaria, materia relevante "
            "para la oportunidad, trazabilidad y control jurídico del análisis financiero."
        )
    elif title:
        matter = f"La iniciativa aborda la siguiente materia: {title.rstrip('.')}."
    else:
        matter = "La materia de la iniciativa está pendiente de una extracción más completa desde el texto oficial."

    if relevance_level == 1:
        matter += " Su relación con la UAF es directa porque modifica o menciona expresamente la Ley N.º 19.913 o sus funciones."
    elif relevance_level == 2:
        matter += " Su relación con la UAF es indirecta, por sus efectos sobre el sistema preventivo LA/FT o los delitos base."
    return matter, promoters, areas

def classify(project: CandidateProject, config: dict[str, Any]) -> dict[str, Any]:
    evidence = " ".join([
        project.title, project.state, project.stage, project.commission,
        project.urgency, project.latest_movement, project.evidence_text,
        " ".join(project.metadata.get("matters", []) if isinstance(project.metadata.get("matters", []), list) else []),
    ])
    normalized = normalize_text(evidence)

    direct_hits = [term for term in config["direct_terms"] if normalize_text(term) in normalized]
    if project.metadata.get("bcn_associated"):
        direct_hits.append("BCN: proyecto asociado a Ley 19.913")

    impacts: dict[str, dict[str, Any]] = {}
    secondary_score = 0
    for topic, rule in config["secondary_topics"].items():
        hits = unique([term for term in rule["terms"] if normalize_text(term) in normalized])
        if hits:
            raw = int(rule["weight"]) + min(len(hits) - 1, 4) * 2
            score = min(raw, 20)
            secondary_score += score
            impacts[topic] = {
                "score": score,
                "level": min(5, max(1, round(score / 4))),
                "hits": hits[:12],
                "recommendation": IMPACT_RECOMMENDATIONS.get(topic, "Realizar análisis técnico y jurídico específico."),
            }

    direct_score = 55 if direct_hits else 0
    relevance_score = min(100, direct_score + secondary_score)
    if direct_hits:
        relevance_level = 1
        relevance_label = "Ley 19.913 o impacto explícito en funciones UAF"
    elif secondary_score >= int(config["minimum_secondary_score"]):
        relevance_level = 2
        relevance_label = "Otra materia LA/FT con impacto potencial"
    else:
        relevance_level = 0
        relevance_label = "Sin impacto suficiente"

    lifecycle = assess_lifecycle(project, config)
    top_impacts = sorted(
        ({"name": name, **payload} for name, payload in impacts.items()),
        key=lambda item: item["score"], reverse=True,
    )
    decisions = unique([item["recommendation"] for item in top_impacts[:5]])
    if relevance_level == 1:
        decisions.insert(0, "Revisar artículo por artículo la modificación propuesta a la Ley 19.913 y asignar responsable institucional.")

    probability = estimate_probability(project)
    priority_score = min(100, round(relevance_score * 0.72 + probability * 0.28))
    if priority_score >= 80:
        priority = "Crítica"
    elif priority_score >= 62:
        priority = "Alta"
    elif priority_score >= 42:
        priority = "Media"
    else:
        priority = "Baja"

    matter_summary, promoters, affected_areas = _matter_profile(project, relevance_level, impacts)
    promoter_text = ", ".join(promoters[:8])
    analysis_parts = [matter_summary]
    if promoter_text:
        if "mensaje" in normalize_text(project.initiative_type):
            analysis_parts.append("Iniciativa del Ejecutivo promovida por " + promoter_text + ".")
        else:
            analysis_parts.append("Promovida por " + promoter_text + (" y otros parlamentarios." if len(promoters) > 8 else "."))
    if affected_areas:
        analysis_parts.append("Ámbitos jurídicos afectados: " + "; ".join(affected_areas[:6]) + ".")

    # La pertinencia ordena primero las modificaciones directas y luego las demás
    # materias LA/FT, combinando precisión jurídica, etapa y actividad reciente.
    stage_bonus = 0
    stage_norm = normalize_text(project.stage)
    if "tercer tramite" in stage_norm or "comision mixta" in stage_norm:
        stage_bonus = 18
    elif "segundo tramite" in stage_norm:
        stage_bonus = 12
    elif "primer tramite" in stage_norm:
        stage_bonus = 5
    pertinence_score = (200 if relevance_level == 1 else 100 if relevance_level == 2 else 0) + relevance_score + stage_bonus

    fingerprint_payload = {
        "title": project.title,
        "state": project.state,
        "stage": project.stage,
        "commission": project.commission,
        "urgency": project.urgency,
        "latest_movement": project.latest_movement,
        "latest_movement_date": project.latest_movement_date,
        "promoters": promoters,
        "matters": project.metadata.get("matters", []),
        "legislative_detail_hash": stable_hash({
            "senado_proceedings": project.metadata.get("senado_proceedings", []),
            "commission_presentations": project.metadata.get("commission_presentations", []),
            "official_document_reviews": [
                {
                    "url": item.get("url", ""),
                    "date": item.get("date", ""),
                    "text_hash": item.get("text_hash", ""),
                }
                for item in project.metadata.get("official_document_reviews", []) or []
                if isinstance(item, dict)
            ],
        }),
        "fallback_raw_hash": project.raw_hash if not any([project.state, project.stage, project.commission, project.urgency, project.latest_movement]) else "",
        "relevance_level": relevance_level,
        "impact_names": [item["name"] for item in top_impacts],
        "lifecycle_code": lifecycle["lifecycle_code"],
        "reference_date": lifecycle["reference_date"],
    }

    return {
        **asdict(project),
        **lifecycle,
        "relevance_level": relevance_level,
        "relevance_label": relevance_label,
        "relevance_score": relevance_score,
        "pertinence_score": pertinence_score,
        "priority_score": priority_score,
        "priority": priority,
        "probability": probability,
        "direct_hits": unique(direct_hits),
        "impacts": impacts,
        "top_impacts": top_impacts,
        "decisions": decisions,
        "promoters": promoters,
        "affected_legal_areas": affected_areas,
        "matter_summary": matter_summary,
        "analysis_summary": " ".join(analysis_parts),
        "fingerprint": stable_hash(fingerprint_payload),
    }


def estimate_probability(project: CandidateProject) -> int:
    text = normalize_text(" ".join([project.state, project.stage, project.urgency, project.latest_movement]))
    score = 35
    rules = [
        ("urgencia inmediata", 28), ("discusion inmediata", 28), ("suma urgencia", 22),
        ("simple urgencia", 14), ("comision mixta", 24), ("tercer tramite", 23),
        ("segundo tramite", 17), ("primer tramite", 8), ("aprobado", 18),
        ("despachado", 25), ("votacion", 10), ("informe", 7), ("archivado", -30),
        ("rechazado", -18), ("retirado", -35), ("tramitacion terminada", -45),
    ]
    for term, delta in rules:
        if term in text:
            score += delta
    return max(5, min(98, score))


def compare_projects(
    previous: dict[str, Any],
    current: dict[str, Any],
    config: dict[str, Any],
    excluded: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    previous_projects = previous.get("projects", {}) if previous else {}
    first_run = not bool(previous_projects)
    if first_run and not config.get("baseline_sends_email", False):
        return alerts

    for bulletin, new in current.items():
        if new.get("relevance_level", 0) == 0:
            continue
        old = previous_projects.get(bulletin)
        if old is None:
            alerts.append(build_alert("new_project", None, new, config))
            continue
        if old.get("fingerprint") != new.get("fingerprint"):
            alert = build_alert("project_changed", old, new, config)
            # Una nueva versión del extractor puede enriquecer fichas históricas sin que
            # exista un cambio legislativo real. Solo alertar si hay diferencias materiales.
            if alert.get("changes"):
                alerts.append(alert)

    # Solo avisar cierres reales de proyectos que ya habían sido validados por esta versión.
    for bulletin, old in previous_projects.items():
        if bulletin in current or old.get("is_current") is not True:
            continue
        closed = (excluded or {}).get(bulletin)
        if closed and closed.get("lifecycle_code") == "terminal":
            alerts.append(build_alert("project_closed", old, closed, config))

    return sorted(alerts, key=lambda item: (severity_rank(item["severity"]), item["priority_score"]), reverse=True)


def build_alert(kind: str, old: dict[str, Any] | None, new: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    watched = ["title", "state", "stage", "commission", "urgency", "latest_movement", "latest_movement_date", "relevance_level", "lifecycle_code"]
    changes: list[dict[str, str]] = []

    def newest_summary(items: list[dict[str, Any]], kind: str) -> str:
        if not items:
            return "Sin registros"
        item = items[-1]
        if kind == "tramitacion":
            return " · ".join(filter(None, [str(item.get("date", "")), str(item.get("substage", "")), str(item.get("stage", ""))]))[:1000]
        return " · ".join(filter(None, [str(item.get("date", "")), str(item.get("title", "")), str(item.get("organization", "")), str(item.get("commission", ""))]))[:1000]
    if kind == "project_closed":
        changes.append({"field": "lifecycle", "before": str(old.get("lifecycle_status", "En tramitación") if old else ""), "after": new.get("lifecycle_status", "Tramitación terminada")})
    elif old:
        for field in watched:
            before = str(old.get(field, "") or "")
            after = str(new.get(field, "") or "")
            if before != after:
                changes.append({"field": field, "before": before[:1000], "after": after[:1000]})

        old_meta = old.get("metadata", {}) or {}
        new_meta = new.get("metadata", {}) or {}
        # No alertar por el enriquecimiento inicial de la versión 1.0.4. A partir de
        # la segunda ejecución, cualquier fila nueva o modificada sí genera novedad.
        if old_meta.get("senado_detail_schema"):
            for key, field, kind in [
                ("senado_proceedings", "tramitacion", "tramitacion"),
                ("commission_presentations", "presentaciones_comision", "presentacion"),
            ]:
                before_items = old_meta.get(key, []) or []
                after_items = new_meta.get(key, []) or []
                if stable_hash(before_items) != stable_hash(after_items):
                    changes.append({
                        "field": field,
                        "before": f"{len(before_items)} registro(s). {newest_summary(before_items, kind)}",
                        "after": f"{len(after_items)} registro(s). {newest_summary(after_items, kind)}",
                    })
    else:
        changes.append({"field": "project", "before": "", "after": "Nueva iniciativa relevante detectada"})

    change_text = normalize_text(" ".join(change["after"] for change in changes))
    critical_hit = any(normalize_text(term) in change_text for term in config["critical_change_terms"])
    if kind == "project_closed":
        severity = "Alta"
    elif new.get("relevance_level") == 1 and critical_hit:
        severity = "Crítica"
    elif new.get("relevance_level") == 1:
        severity = "Alta"
    elif critical_hit or new.get("priority_score", 0) >= 70:
        severity = "Alta"
    else:
        severity = "Media"

    alert_id = stable_hash({"kind": kind, "bulletin": new["bulletin"], "changes": changes, "fingerprint": new.get("fingerprint")})[:20]
    return {
        "id": alert_id,
        "kind": kind,
        "bulletin": new["bulletin"],
        "title": new.get("title", ""),
        "severity": severity,
        "priority_score": new.get("priority_score", 0),
        "relevance_level": new.get("relevance_level", 0),
        "relevance_label": new.get("relevance_label", ""),
        "lifecycle_status": new.get("lifecycle_status", ""),
        "changes": changes,
        "top_impacts": new.get("top_impacts", [])[:5],
        "decisions": new.get("decisions", [])[:4],
        "source_urls": new.get("source_urls", []),
    }


def severity_rank(value: str) -> int:
    return {"Crítica": 3, "Alta": 2, "Media": 1, "Baja": 0}.get(value, 0)

def sanitize_project_record(record: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Devuelve una copia compacta y serializable de una ficha legislativa.

    Esta función mantiene compatibilidad con ``maintenance_compact.py``.
    Acepta argumentos adicionales para tolerar distintas versiones del script
    de mantenimiento y elimina únicamente contenido bruto o duplicado que no
    es necesario para comparar proyectos ni construir el dashboard.
    """
    if not isinstance(record, dict):
        return {}

    # Límites conservadores: mantienen la cronología legislativa y las
    # presentaciones ante comisión, pero evitan que una página HTML/XML completa
    # termine guardada dentro de state.json o projects.json.
    max_default_string = int(kwargs.get("max_string", 12_000) or 12_000)
    max_default_list = int(kwargs.get("max_list", 250) or 250)

    drop_keys = {
        "raw_html", "html_raw", "page_html", "source_html",
        "raw_xml", "xml_raw", "response_body", "response_text",
        "downloaded_content", "full_document_text", "document_full_text",
        "binary_content", "base64", "screenshot_data",
    }
    string_limits = {
        "title": 2_000,
        "state": 2_000,
        "stage": 2_000,
        "commission": 2_000,
        "urgency": 1_000,
        "latest_movement": 5_000,
        "evidence_text": 12_000,
        "analysis_summary": 8_000,
        "document_summary": 8_000,
        "linkage_summary": 8_000,
        "lifecycle_reason": 4_000,
        "description": 6_000,
        "substage": 4_000,
        "organization": 2_000,
        "url": 4_000,
    }
    list_limits = {
        "senado_proceedings": 300,
        "commission_presentations": 300,
        "legislative_history": 400,
        "proceedings": 300,
        "presentations": 300,
        "documents": 300,
        "source_urls": 60,
        "discovered_from": 60,
        "related_bulletins": 60,
        "group_bulletins": 60,
        "laft_topics": 80,
        "direct_hits": 80,
        "relevance_basis": 100,
        "top_impacts": 30,
        "decisions": 30,
        "changes": 100,
    }

    def compact(value: Any, key: str = "", depth: int = 0) -> Any:
        if depth > 12:
            return None
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            limit = string_limits.get(key, max_default_string)
            return value[:limit]
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for raw_key, raw_value in value.items():
                child_key = str(raw_key)
                if child_key.lower() in drop_keys:
                    continue
                cleaned[child_key] = compact(raw_value, child_key, depth + 1)
            return cleaned
        if isinstance(value, (list, tuple, set)):
            limit = list_limits.get(key, max_default_list)
            items = list(value)[-limit:] if key in {
                "senado_proceedings", "commission_presentations",
                "legislative_history", "proceedings", "presentations",
            } else list(value)[:limit]
            return [compact(item, key, depth + 1) for item in items]
        return str(value)[:max_default_string]

    cleaned = compact(record)
    return cleaned if isinstance(cleaned, dict) else {}

def annotate_initiative_groups(projects: Any, *args: Any, **kwargs: Any) -> Any:
    """Anota proyectos refundidos o relacionados sin alterar el tipo de entrada.

    Compatibilidad:
    - lista de fichas;
    - diccionario ``boletín -> ficha``;
    - contenedor ``{"projects": ...}``;
    - una ficha individual.

    La función modifica las fichas en el objeto recibido y también lo devuelve.
    Esto permite usarla tanto como procedimiento como función de transformación.
    """
    import hashlib
    import re
    from collections import defaultdict
    from copy import deepcopy

    bulletin_re = re.compile(r"(?<!\d)(\d{3,6}\s*-\s*\d{1,3})(?!\d)")

    def normalize_bulletin(value: Any) -> str:
        text = str(value or "").strip()
        match = bulletin_re.search(text)
        if not match:
            return ""
        return re.sub(r"\s+", "", match.group(1))

    relation_keys = (
        "related_bulletins",
        "group_bulletins",
        "refunded_bulletins",
        "refundidos",
        "merged_with",
        "bulletins_refunded",
        "initiative_group_bulletins",
        "boletines_refundidos",
        "boletines_relacionados",
    )
    text_keys = (
        "refunded",
        "refundido",
        "related_projects",
        "title",
        "evidence_text",
        "latest_movement",
        "stage",
        "state",
        "description",
    )

    def values_to_bulletins(value: Any) -> set[str]:
        found: set[str] = set()
        if value is None:
            return found
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in relation_keys or str(key).lower() in text_keys:
                    found.update(values_to_bulletins(child))
                elif isinstance(child, (dict, list, tuple, set)):
                    found.update(values_to_bulletins(child))
            return found
        if isinstance(value, (list, tuple, set)):
            for child in value:
                found.update(values_to_bulletins(child))
            return found
        for raw in bulletin_re.findall(str(value)):
            normalized = normalize_bulletin(raw)
            if normalized:
                found.add(normalized)
        return found

    def record_relations(record: dict[str, Any]) -> set[str]:
        found: set[str] = set()
        for key in relation_keys:
            found.update(values_to_bulletins(record.get(key)))
        metadata = record.get("metadata")
        if isinstance(metadata, dict):
            for key in relation_keys:
                found.update(values_to_bulletins(metadata.get(key)))
            for key in text_keys:
                found.update(values_to_bulletins(metadata.get(key)))
        for key in text_keys:
            found.update(values_to_bulletins(record.get(key)))
        return found

    def matrix_candidate(record: dict[str, Any]) -> str:
        # Primero respeta campos estructurados, si existen.
        for source in (record, record.get("metadata") if isinstance(record.get("metadata"), dict) else {}):
            for key in (
                "matrix_bulletin",
                "matriz_bulletin",
                "primary_bulletin",
                "initiative_group_primary",
                "group_primary",
            ):
                candidate = normalize_bulletin(source.get(key))
                if candidate:
                    return candidate

        # Luego detecta expresiones como "15462-03 *matriz*".
        joined = " ".join(
            str(record.get(key, "") or "")
            for key in ("refunded", "refundido", "evidence_text", "latest_movement", "description")
        )
        metadata = record.get("metadata")
        if isinstance(metadata, dict):
            joined += " " + " ".join(str(metadata.get(key, "") or "") for key in text_keys)

        patterns = (
            r"(\d{3,6}\s*-\s*\d{1,3})\s*(?:\*|\(|\[)?\s*matriz",
            r"matriz\s*(?:\:|-)?\s*(\d{3,6}\s*-\s*\d{1,3})",
        )
        for pattern in patterns:
            match = re.search(pattern, joined, flags=re.IGNORECASE)
            if match:
                return normalize_bulletin(match.group(1))
        return ""

    container_kind = "single"
    container = projects
    records: list[dict[str, Any]] = []

    if isinstance(projects, dict) and "projects" in projects:
        container_kind = "wrapped"
        inner = projects.get("projects")
        if isinstance(inner, dict):
            records = [item for item in inner.values() if isinstance(item, dict)]
        elif isinstance(inner, list):
            records = [item for item in inner if isinstance(item, dict)]
    elif isinstance(projects, dict) and "bulletin" not in projects:
        container_kind = "mapping"
        records = [item for item in projects.values() if isinstance(item, dict)]
    elif isinstance(projects, list):
        container_kind = "list"
        records = [item for item in projects if isinstance(item, dict)]
    elif isinstance(projects, dict):
        records = [projects]
    else:
        return projects

    by_bulletin: dict[str, dict[str, Any]] = {}
    for record in records:
        bulletin = normalize_bulletin(
            record.get("bulletin")
            or record.get("boletin")
            or record.get("id")
        )
        if bulletin:
            record.setdefault("bulletin", bulletin)
            by_bulletin[bulletin] = record

    graph: dict[str, set[str]] = defaultdict(set)
    explicit_matrix: dict[str, str] = {}

    for bulletin, record in by_bulletin.items():
        graph[bulletin].add(bulletin)
        matrix = matrix_candidate(record)
        if matrix:
            explicit_matrix[bulletin] = matrix

        relations = record_relations(record)
        relations.add(bulletin)
        for related in relations:
            graph[bulletin].add(related)
            graph[related].add(bulletin)

    visited: set[str] = set()
    components: list[set[str]] = []

    for node in list(graph):
        if node in visited:
            continue
        stack = [node]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            stack.extend(graph.get(current, set()) - visited)
        components.append(component)

    for component in components:
        present = sorted(item for item in component if item in by_bulletin)
        if not present:
            continue

        primary_candidates = [
            candidate
            for bulletin in present
            for candidate in [explicit_matrix.get(bulletin, "")]
            if candidate and candidate in component
        ]

        if primary_candidates:
            primary = primary_candidates[0]
        else:
            # Prefiere la ficha marcada como matriz y, luego, la de ingreso más antiguo.
            marked = [
                bulletin
                for bulletin in present
                if bool(by_bulletin[bulletin].get("is_matrix"))
                or bool(by_bulletin[bulletin].get("is_matriz"))
                or bool(
                    (by_bulletin[bulletin].get("metadata") or {}).get("is_matrix")
                    if isinstance(by_bulletin[bulletin].get("metadata"), dict)
                    else False
                )
            ]
            if marked:
                primary = marked[0]
            else:
                def sort_key(bulletin: str) -> tuple[str, str]:
                    date = str(by_bulletin[bulletin].get("entry_date", "") or "9999-99-99")
                    return (date, bulletin)
                primary = sorted(present, key=sort_key)[0]

        all_bulletins = sorted(component)
        digest = hashlib.sha1("|".join(all_bulletins).encode("utf-8")).hexdigest()[:12]
        group_id = f"grp-{digest}"

        for bulletin in present:
            record = by_bulletin[bulletin]
            grouped = len(all_bulletins) > 1
            role = "Matriz" if grouped and bulletin == primary else ("Refundido" if grouped else "Individual")

            annotations = {
                "initiative_group_id": group_id if grouped else "",
                "initiative_group_bulletins": all_bulletins if grouped else [bulletin],
                "initiative_group_size": len(all_bulletins) if grouped else 1,
                "initiative_group_primary": primary if grouped else bulletin,
                "initiative_group_role": role,
                "is_grouped_initiative": grouped,
                "is_group_primary": bulletin == primary,
                # Alias de compatibilidad para versiones previas o posteriores.
                "group_id": group_id if grouped else "",
                "group_bulletins": all_bulletins if grouped else [bulletin],
                "group_primary": primary if grouped else bulletin,
            }
            record.update(annotations)

            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                record["metadata"] = metadata
            metadata.update(
                {
                    "initiative_group_id": annotations["initiative_group_id"],
                    "initiative_group_bulletins": annotations["initiative_group_bulletins"],
                    "initiative_group_primary": annotations["initiative_group_primary"],
                    "initiative_group_role": annotations["initiative_group_role"],
                }
            )

    return container
