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


PERSISTED_METADATA_KEYS = {"bcn_associated", "newly_discovered", "recent_feed", "title_rank"}


def sanitize_project_record(project: dict[str, Any]) -> dict[str, Any]:
    """Elimina evidencia cruda y estructuras voluminosas antes de persistir o publicar."""
    clean = dict(project)
    clean.pop("evidence_text", None)
    metadata = clean.get("metadata") or {}
    clean["metadata"] = {
        key: metadata[key]
        for key in PERSISTED_METADATA_KEYS
        if key in metadata and isinstance(metadata[key], (str, int, float, bool, type(None)))
    }
    clean["source_urls"] = unique(clean.get("source_urls", []))[:20]
    clean["discovered_from"] = unique(clean.get("discovered_from", []))[:20]
    return clean


def _has_any(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if normalize_text(term) in text]


def assess_lifecycle(project: CandidateProject, config: dict[str, Any]) -> dict[str, Any]:
    """Determina si una iniciativa sigue siendo útil para la cartera activa del monitor."""
    today = local_now(config.get("timezone", "America/Santiago")).date()
    authoritative = normalize_text(" ".join([
        project.state, project.stage, project.urgency, project.latest_movement,
    ]))
    terminal_hits = _has_any(authoritative, config.get("terminal_state_terms", []))
    active_hits = _has_any(authoritative, config.get("active_state_terms", []))
    upcoming_hits = _has_any(authoritative, config.get("upcoming_terms", []))

    entry = parse_legislative_date(project.entry_date)
    movement = parse_legislative_date(project.latest_movement_date) or parse_legislative_date(project.latest_movement)
    reference = movement or entry
    recency_days = (today - reference).days if reference else None
    entry_days = (today - entry).days if entry else None

    new_days = int(config.get("new_project_days", 180))
    active_days = int(config.get("active_movement_days", 730))
    recent_entry = entry_days is not None and -31 <= entry_days <= new_days
    recent_movement = recency_days is not None and -31 <= recency_days <= active_days
    recent_feed = bool(project.metadata.get("recent_feed"))
    explicit_urgency = bool(project.urgency.strip())

    if terminal_hits:
        return {
            "is_current": False,
            "lifecycle_code": "terminal",
            "lifecycle_status": "Tramitación terminada",
            "lifecycle_reason": "La fuente oficial contiene un estado terminal: " + ", ".join(terminal_hits[:3]),
            "lifecycle_flags": [],
            "reference_date": reference.isoformat() if reference else "",
            "recency_days": recency_days,
        }

    flags: list[str] = []
    if recent_entry:
        flags.append("new")
    if upcoming_hits and (recent_movement or recent_entry or recent_feed or explicit_urgency):
        flags.append("upcoming")
    if recent_movement or recent_feed or (active_hits and recent_entry) or (active_hits and explicit_urgency):
        flags.append("active")

    if "upcoming" in flags:
        status = "Próximo hito legislativo"
        code = "upcoming"
        reason = "Se detectó una votación, urgencia, citación, paso de etapa u otro hito próximo."
    elif "new" in flags:
        status = "Nueva / ingreso reciente"
        code = "new"
        reason = f"La iniciativa ingresó dentro de los últimos {new_days} días."
    elif "active" in flags:
        status = "En tramitación activa"
        code = "active"
        reason = f"Registra actividad oficial dentro de los últimos {active_days} días."
    else:
        if active_hits and reference and recency_days is not None and recency_days > active_days:
            code = "stale"
            status = "Sin actividad reciente"
            reason = f"Aunque conserva una etapa legislativa, no registra movimientos dentro de los últimos {active_days} días."
        elif active_hits and not reference:
            code = "unverified"
            status = "Vigencia no comprobada"
            reason = "La etapa parece activa, pero no existe una fecha reciente que permita comprobar su vigencia."
        else:
            code = "historical"
            status = "Antecedente histórico"
            reason = "No existe evidencia oficial suficiente de ingreso reciente o tramitación activa."
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


def classify(project: CandidateProject, config: dict[str, Any]) -> dict[str, Any]:
    evidence = " ".join([
        project.title,
        project.state,
        project.stage,
        project.commission,
        project.urgency,
        project.latest_movement,
        project.evidence_text,
    ])
    normalized = normalize_text(evidence)

    direct_hits = [term for term in config["direct_terms"] if normalize_text(term) in normalized]
    if project.metadata.get("bcn_associated"):
        direct_hits.append("BCN: proyecto asociado a Ley 19.913")

    impacts: dict[str, dict[str, Any]] = {}
    secondary_score = 0
    for topic, rule in config["secondary_topics"].items():
        hits = [term for term in rule["terms"] if normalize_text(term) in normalized]
        hits = unique(hits)
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
        relevance_label = "Modificación directa / impacto explícito"
    elif secondary_score >= int(config["minimum_secondary_score"]):
        relevance_level = 2
        relevance_label = "Impacto legal potencial sobre la labor UAF"
    else:
        relevance_level = 0
        relevance_label = "Sin impacto suficiente"

    lifecycle = assess_lifecycle(project, config)
    top_impacts = sorted(
        ({"name": name, **payload} for name, payload in impacts.items()),
        key=lambda item: item["score"],
        reverse=True,
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

    summary_parts = []
    if direct_hits:
        summary_parts.append("La iniciativa presenta una vinculación expresa con la Ley 19.913 o con la UAF.")
    if top_impacts:
        summary_parts.append("Sus principales dimensiones de impacto son " + ", ".join(item["name"] for item in top_impacts[:3]) + ".")
    if lifecycle["is_current"]:
        summary_parts.append("Vigencia: " + lifecycle["lifecycle_status"] + ".")
    if project.latest_movement:
        summary_parts.append("Último antecedente detectado: " + project.latest_movement[:260])

    fingerprint_payload = {
        "title": project.title,
        "state": project.state,
        "stage": project.stage,
        "commission": project.commission,
        "urgency": project.urgency,
        "latest_movement": project.latest_movement,
        "latest_movement_date": project.latest_movement_date,
        "fallback_raw_hash": project.raw_hash if not any([project.state, project.stage, project.commission, project.urgency, project.latest_movement]) else "",
        "relevance_level": relevance_level,
        "impact_names": [item["name"] for item in top_impacts],
        "lifecycle_code": lifecycle["lifecycle_code"],
        "reference_date": lifecycle["reference_date"],
    }

    persisted_project = sanitize_project_record(asdict(project))
    return {
        **persisted_project,
        **lifecycle,
        "relevance_level": relevance_level,
        "relevance_label": relevance_label,
        "relevance_score": relevance_score,
        "priority_score": priority_score,
        "priority": priority,
        "probability": probability,
        "direct_hits": unique(direct_hits),
        "impacts": impacts,
        "top_impacts": top_impacts,
        "decisions": decisions,
        "analysis_summary": " ".join(summary_parts),
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
            alerts.append(build_alert("project_changed", old, new, config))

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
    if kind == "project_closed":
        changes.append({"field": "lifecycle", "before": str(old.get("lifecycle_status", "En tramitación") if old else ""), "after": new.get("lifecycle_status", "Tramitación terminada")})
    elif old:
        for field in watched:
            before = str(old.get(field, "") or "")
            after = str(new.get(field, "") or "")
            if before != after:
                changes.append({"field": field, "before": before[:1000], "after": after[:1000]})
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
