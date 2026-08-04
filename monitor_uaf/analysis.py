from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from .models import CandidateProject
from .utils import (
    BULLETIN_RE,
    contains_term,
    local_now,
    matching_terms,
    normalize_text,
    parse_legislative_date,
    stable_hash,
    unique,
)


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

PERSISTED_METADATA_KEYS = {
    "bcn_associated", "newly_discovered", "recent_feed", "title_rank",
    "movement_rank", "movement_source", "official_date_verified",
}


def sanitize_project_record(project: dict[str, Any]) -> dict[str, Any]:
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
    clean["related_bulletins"] = unique(clean.get("related_bulletins", []))[:20]
    clean["group_bulletins"] = unique(clean.get("group_bulletins", []))[:20]
    clean["laft_topics"] = unique(clean.get("laft_topics", []))[:12]
    return clean


def _hits(text: str, terms: list[str]) -> list[str]:
    return matching_terms(text, terms)


def assess_lifecycle(project: CandidateProject, config: dict[str, Any]) -> dict[str, Any]:
    today = local_now(config.get("timezone", "America/Santiago")).date()
    authoritative = normalize_text(" ".join([
        project.state, project.stage, project.urgency, project.latest_movement,
    ]))
    terminal_hits = _hits(authoritative, config.get("terminal_state_terms", []))
    active_hits = _hits(authoritative, config.get("active_state_terms", []))
    upcoming_hits = _hits(authoritative, config.get("upcoming_terms", []))

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
        status, code = "Próximo hito legislativo", "upcoming"
        reason = "Se detectó una votación, urgencia, citación, paso de etapa u otro hito próximo."
    elif "new" in flags:
        status, code = "Nueva / ingreso reciente", "new"
        reason = f"La iniciativa ingresó dentro de los últimos {new_days} días."
    elif "active" in flags:
        status, code = "En tramitación activa", "active"
        reason = f"Registra actividad oficial dentro de los últimos {active_days} días."
    else:
        if active_hits and reference and recency_days is not None and recency_days > active_days:
            code, status = "stale", "Sin actividad reciente"
            reason = f"Aunque conserva una etapa legislativa, no registra movimientos dentro de los últimos {active_days} días."
        elif active_hits and not reference:
            code, status = "unverified", "Vigencia no comprobada"
            reason = "La etapa parece activa, pero no existe una fecha oficial reciente que permita comprobar su vigencia."
        else:
            code, status = "historical", "Antecedente histórico"
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


def _extract_related_bulletins(project: CandidateProject) -> list[str]:
    text = " ".join([project.title, project.latest_movement, project.evidence_text])
    normalized = normalize_text(text)
    related: list[str] = []
    for match in BULLETIN_RE.finditer(text):
        bulletin = match.group(1)
        if bulletin == project.bulletin:
            continue
        start = max(0, match.start() - 160)
        end = min(len(text), match.end() + 160)
        window = normalize_text(text[start:end])
        if any(contains_term(window, term) for term in [
            "refundido", "refundida", "fusionar", "fusionado", "fusionada",
            "tramitación conjunta", "tramitacion conjunta", "conjuntamente",
            "proyecto relacionado", "boletín asociado", "boletin asociado",
        ]):
            related.append(bulletin)
    # Algunas fuentes sitúan la palabra de relación lejos del número; se usa una regla
    # conservadora solo si todo el texto contiene una señal inequívoca de refundición.
    if any(contains_term(normalized, term) for term in ["refundido con", "refundida con", "se fusiona con"]):
        related.extend(b for b in BULLETIN_RE.findall(text) if b != project.bulletin)
    return unique(related)


def _initiative_name(project: CandidateProject, config: dict[str, Any]) -> str:
    aliases = config.get("initiative_names", {})
    if project.bulletin in aliases:
        return aliases[project.bulletin]
    title = re.sub(r"\s+", " ", project.title or "").strip(" .")
    if not title:
        return f"Iniciativa boletín {project.bulletin}"
    normalized = normalize_text(title)
    semantic_aliases = [
        ("subsistema de inteligencia economica", "Sistema de Inteligencia Económica"),
        ("beneficiarios finales", "Registro de Beneficiarios Finales"),
        ("secreto bancario", "Acceso a Información Bancaria"),
        ("transacciones en dinero efectivo", "Límites a Transacciones en Efectivo"),
        ("operaciones prendarias", "Trazabilidad de Operaciones Prendarias"),
    ]
    for term, alias in semantic_aliases:
        if contains_term(normalized, term):
            return alias
    # Mantiene un nombre comprensible y evita fórmulas legislativas demasiado extensas.
    title = re.sub(r"^(proyecto de ley que\s+)", "", title, flags=re.IGNORECASE)
    return title[:135] + ("…" if len(title) > 135 else "")


def _specific_topics(impacts: dict[str, dict[str, Any]], basis_hits: list[str]) -> list[str]:
    preferred: list[str] = []
    for payload in sorted(impacts.values(), key=lambda item: item.get("score", 0), reverse=True):
        preferred.extend(payload.get("hits", []))
    preferred.extend(basis_hits)
    generic = {"sanciones", "bancos", "presupuesto", "datos", "fiscalizacion", "supervision"}
    canonical = {
        "beneficiarios finales": "beneficiario final",
        "intercambio de informacion": "intercambio de información",
        "operaciones sospechosas": "operación sospechosa",
        "sujetos obligados": "sujeto obligado",
        "entidades reportantes": "entidad reportante",
        "delitos precedentes": "delito precedente",
        "delitos base": "delito base",
    }
    out: list[str] = []
    seen: set[str] = set()
    for item in preferred:
        norm = normalize_text(item)
        if norm in generic:
            continue
        display = canonical.get(norm, item)
        key = normalize_text(display)
        if key and key not in seen:
            seen.add(key)
            out.append(display)
    return out[:8]


def classify(project: CandidateProject, config: dict[str, Any]) -> dict[str, Any]:
    title_text = normalize_text(project.title)
    evidence = " ".join([
        project.title, project.state, project.stage, project.commission,
        project.urgency, project.latest_movement, project.evidence_text,
    ])
    normalized = normalize_text(evidence)

    direct_hits = _hits(normalized, config.get("direct_terms", []))
    if project.metadata.get("bcn_associated"):
        direct_hits.append("BCN: proyecto asociado a Ley 19.913")
    direct_hits = unique(direct_hits)

    explicit_laft_hits = _hits(normalized, config.get("laft_anchor_terms", []))
    high_precision_hits = _hits(normalized, config.get("high_precision_secondary_terms", []))
    mechanism_hits = _hits(normalized, config.get("laft_mechanism_terms", []))
    predicate_hits = _hits(normalized, config.get("predicate_crime_terms", []))
    financial_hits = _hits(normalized, config.get("financial_traceability_terms", []))
    control_hits = _hits(normalized, config.get("control_terms", []))
    noise_hits = _hits(title_text, config.get("noise_domain_terms", []))

    title_laft_hits = unique(
        _hits(title_text, config.get("laft_anchor_terms", []))
        + _hits(title_text, config.get("high_precision_secondary_terms", []))
        + _hits(title_text, config.get("laft_mechanism_terms", []))
    )

    explicit_laft = bool(explicit_laft_hits)
    high_precision = bool(high_precision_hits)
    combined_laft = bool(mechanism_hits and (predicate_hits or financial_hits) and control_hits)
    financial_crime_link = bool(financial_hits and predicate_hits and mechanism_hits)
    secondary_gate = explicit_laft or high_precision or combined_laft or financial_crime_link

    # Un dominio ajeno (educación, salud, medio ambiente, etc.) se descarta cuando la
    # relación LA/FT no aparece en el título ni mediante una señal explícita de alta precisión.
    noise_block = bool(noise_hits and not explicit_laft and not high_precision and not title_laft_hits)

    impacts: dict[str, dict[str, Any]] = {}
    secondary_score = 0
    if direct_hits or (secondary_gate and not noise_block):
        for topic, rule in config.get("secondary_topics", {}).items():
            hits = _hits(normalized, rule.get("terms", []))
            if hits:
                title_hits = _hits(title_text, rule.get("terms", []))
                raw = int(rule.get("weight", 0)) + min(len(hits) - 1, 4) * 2 + min(len(title_hits), 2) * 3
                score = min(raw, 20)
                secondary_score += score
                impacts[topic] = {
                    "score": score,
                    "level": min(5, max(1, round(score / 4))),
                    "hits": hits[:10],
                    "recommendation": IMPACT_RECOMMENDATIONS.get(topic, "Realizar análisis técnico y jurídico específico."),
                }

    basis_hits = unique(explicit_laft_hits + high_precision_hits + mechanism_hits + predicate_hits + financial_hits)
    confidence = 0
    if explicit_laft:
        confidence += 55
    if high_precision:
        confidence += 55
    if combined_laft:
        confidence += 25
    if financial_crime_link:
        confidence += 20
    confidence += min(15, len(title_laft_hits) * 5)
    confidence += min(15, len(set(impacts)) * 3)
    if noise_block:
        confidence = max(0, confidence - 60)
    confidence = min(100, confidence)

    direct_score = 60 if direct_hits else 0
    relevance_score = min(100, direct_score + secondary_score + min(20, confidence // 4))
    minimum_confidence = int(config.get("minimum_secondary_confidence", 55))
    minimum_score = int(config.get("minimum_secondary_score", 18))
    if direct_hits:
        relevance_level = 1
        relevance_label = "Modificación directa / impacto explícito en Ley 19.913"
        relevance_reason = "El texto menciona expresamente la Ley 19.913, la UAF o una modificación asociada oficialmente a esa ley."
    elif secondary_gate and not noise_block and confidence >= minimum_confidence and secondary_score >= minimum_score:
        relevance_level = 2
        relevance_label = "Impacto LA/FT potencial sobre la labor UAF"
        relevance_reason = "No modifica expresamente la Ley 19.913, pero contiene mecanismos o materias directamente vinculadas con prevención LA/FT."
    else:
        relevance_level = 0
        relevance_label = "Sin relación LA/FT suficiente"
        if noise_block:
            relevance_reason = "La iniciativa pertenece a un dominio ajeno y no presenta una conexión LA/FT explícita o de alta precisión."
        elif not secondary_gate:
            relevance_reason = "No se detectó una ancla LA/FT ni una combinación financiera-criminal suficientemente precisa."
        else:
            relevance_reason = "La evidencia LA/FT no supera los umbrales de confianza y especificidad."

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

    initiative_name = _initiative_name(project, config)
    related_bulletins = _extract_related_bulletins(project)
    laft_topics = _specific_topics(impacts, basis_hits)
    topic_phrase = ", ".join(laft_topics[:5]) or "materias LA/FT por precisar en el texto oficial"
    if relevance_level == 1:
        linkage_summary = f"Modifica o afecta expresamente la Ley 19.913/UAF. Los tópicos relevantes detectados son: {topic_phrase}."
    elif relevance_level == 2:
        linkage_summary = f"No modifica directamente la Ley 19.913, pero se vincula con prevención LA/FT por: {topic_phrase}."
    else:
        linkage_summary = relevance_reason

    descriptions = config.get("initiative_descriptions", {})
    document_summary = descriptions.get(project.bulletin)
    if not document_summary:
        if relevance_level > 0:
            document_summary = f"{initiative_name}: la evidencia oficial disponible concentra su relación con la UAF/LAFT en {topic_phrase}."
        else:
            document_summary = f"{initiative_name}: sin vínculo LA/FT suficiente para incorporarlo al monitor."

    summary_parts = [linkage_summary]
    if top_impacts:
        summary_parts.append("Impactos institucionales principales: " + ", ".join(item["name"] for item in top_impacts[:3]) + ".")
    if project.latest_movement_date:
        source = project.metadata.get("movement_source", "fuente oficial")
        summary_parts.append(f"Último trámite oficial: {project.latest_movement_date} ({source}).")

    fingerprint_payload = {
        "title": project.title,
        "initiative_name": initiative_name,
        "state": project.state,
        "stage": project.stage,
        "commission": project.commission,
        "urgency": project.urgency,
        "latest_movement": project.latest_movement,
        "latest_movement_date": project.latest_movement_date,
        "relevance_level": relevance_level,
        "laft_topics": laft_topics,
        "impact_names": [item["name"] for item in top_impacts],
        "lifecycle_code": lifecycle["lifecycle_code"],
        "reference_date": lifecycle["reference_date"],
    }

    persisted_project = sanitize_project_record(asdict(project))
    return {
        **persisted_project,
        **lifecycle,
        "initiative_name": initiative_name,
        "related_bulletins": related_bulletins,
        "relevance_level": relevance_level,
        "relevance_label": relevance_label,
        "relevance_reason": relevance_reason,
        "relevance_score": relevance_score,
        "laft_confidence": confidence,
        "priority_score": priority_score,
        "priority": priority,
        "probability": probability,
        "direct_hits": direct_hits,
        "relevance_basis": basis_hits[:20],
        "laft_topics": laft_topics,
        "impacts": impacts,
        "top_impacts": top_impacts,
        "decisions": decisions,
        "linkage_summary": linkage_summary,
        "document_summary": document_summary,
        "analysis_summary": " ".join(summary_parts),
        "fingerprint": stable_hash(fingerprint_payload),
    }


def annotate_initiative_groups(projects: dict[str, dict[str, Any]], config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Agrupa boletines refundidos o pertenecientes a una misma iniciativa conocida."""
    parent = {bulletin: bulletin for bulletin in projects}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        if a not in projects or b not in projects:
            return
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for bulletin, project in projects.items():
        for related in project.get("related_bulletins", []):
            union(bulletin, related)
    for group in config.get("initiative_groups", []):
        members = [b for b in group.get("bulletins", []) if b in projects]
        for member in members[1:]:
            union(members[0], member)

    components: dict[str, list[str]] = {}
    for bulletin in projects:
        components.setdefault(find(bulletin), []).append(bulletin)

    configured_names: dict[str, str] = {}
    for group in config.get("initiative_groups", []):
        for bulletin in group.get("bulletins", []):
            configured_names[bulletin] = group.get("name", "")

    for members in components.values():
        members = sorted(members)
        configured = next((configured_names[b] for b in members if configured_names.get(b)), "")
        primary = max(
            (projects[b] for b in members),
            key=lambda item: (item.get("priority_score", 0), item.get("reference_date", "")),
        )
        group_name = configured or primary.get("initiative_name") or primary.get("title")
        group_id = stable_hash(members)[:12]
        for bulletin in members:
            projects[bulletin]["initiative_group_id"] = group_id
            projects[bulletin]["initiative_group_name"] = group_name
            projects[bulletin]["group_bulletins"] = members
            projects[bulletin]["group_size"] = len(members)
    return projects


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
        if contains_term(text, term):
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
        material_fields = [
            "title", "state", "stage", "commission", "urgency", "latest_movement",
            "latest_movement_date", "relevance_level", "lifecycle_code", "reference_date",
        ]
        if any(str(old.get(field, "") or "") != str(new.get(field, "") or "") for field in material_fields):
            alerts.append(build_alert("project_changed", old, new, config))

    for bulletin, old in previous_projects.items():
        if bulletin in current or old.get("is_current") is not True:
            continue
        closed = (excluded or {}).get(bulletin)
        if closed and closed.get("lifecycle_code") == "terminal":
            alerts.append(build_alert("project_closed", old, closed, config))

    return sorted(alerts, key=lambda item: (severity_rank(item["severity"]), item["priority_score"]), reverse=True)


def build_alert(kind: str, old: dict[str, Any] | None, new: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    watched = [
        "title", "state", "stage", "commission", "urgency",
        "latest_movement", "latest_movement_date", "relevance_level", "lifecycle_code",
    ]
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
        changes.append({"field": "project", "before": "", "after": "Nueva iniciativa LA/FT relevante detectada"})

    change_text = normalize_text(" ".join(change["after"] for change in changes))
    critical_hit = any(contains_term(change_text, term) for term in config.get("critical_change_terms", []))
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
        "initiative_name": new.get("initiative_name", new.get("title", "")),
        "initiative_group_id": new.get("initiative_group_id", new.get("bulletin", "")),
        "group_bulletins": new.get("group_bulletins", [new.get("bulletin", "")]),
        "linkage_summary": new.get("linkage_summary", ""),
        "official_movement_date": new.get("latest_movement_date", ""),
        "official_movement_text": new.get("latest_movement", ""),
        "movement_source": (new.get("metadata") or {}).get("movement_source", ""),
        "severity": severity,
        "priority_score": new.get("priority_score", 0),
        "relevance_level": new.get("relevance_level", 0),
        "relevance_label": new.get("relevance_label", ""),
        "lifecycle_status": new.get("lifecycle_status", ""),
        "changes": changes,
        "top_impacts": new.get("top_impacts", [])[:5],
        "laft_topics": new.get("laft_topics", [])[:8],
        "decisions": new.get("decisions", [])[:4],
        "source_urls": new.get("source_urls", []),
    }


def severity_rank(value: str) -> int:
    return {"Crítica": 3, "Alta": 2, "Media": 1, "Baja": 0}.get(value, 0)
