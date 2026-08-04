from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from .analysis import annotate_initiative_groups, classify, compare_projects, sanitize_project_record
from .config import DATA_DIR, DOCS_DIR, load_config
from .http_client import HttpClient
from .models import CandidateProject
from .notifier import send_alert_email
from .documents import OfficialProjectDocumentSource
from .press import ProjectPressSource
from .render import render_dashboard
from .sources import BCNAssociatedProjectsSource, CamaraOpenDataSource, CamaraWebDetailSource, SenadoSource
from .utils import iso_now, local_now, parse_legislative_date, read_json, write_json

LOGGER = logging.getLogger(__name__)


def _project_order(item: dict[str, Any]) -> tuple[str, int, int, int]:
    """Ordena primero por la última modificación oficial del boletín.

    La pertinencia se usa como desempate, no como agrupación principal. Los
    proyectos sin movimiento fechado quedan detrás de aquellos con actividad
    verificada y se ordenan por fecha de ingreso.
    """
    level = int(item.get("relevance_level", 9) or 9)
    level_rank = 2 if level == 1 else 1 if level == 2 else 0
    reference_date = str(
        item.get("latest_movement_date")
        or item.get("reference_date")
        or item.get("entry_date")
        or "0000-00-00"
    )
    return (
        reference_date,
        level_rank,
        int(item.get("pertinence_score", 0) or 0),
        int(item.get("priority_score", 0) or 0),
    )



def _continuity_needed(
    current_count: int,
    continuity_count: int,
    verified_details: int,
    config: dict[str, Any],
) -> bool:
    """Evita que una falla de extracción publique un tablero vacío.

    La reducción solo activa respaldo si no hubo validaciones individuales
    suficientes. Un cierre legislativo real sí puede reducir la cartera porque
    vendrá acompañado de fichas oficiales verificadas.
    """
    if not config.get("continuity_fallback_enabled", True) or continuity_count <= 0:
        return False
    if current_count == 0 and verified_details == 0:
        return True
    ratio = current_count / max(continuity_count, 1)
    minimum_ratio = float(config.get("continuity_min_ratio", 0.35))
    minimum_verified = int(config.get("continuity_min_verified_details", 1))
    return ratio < minimum_ratio and verified_details < minimum_verified


class MonitorPipeline:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_config()
        self.client = HttpClient(
            timeout=int(self.config.get("request_timeout_seconds", 35)),
            retries=int(self.config.get("request_retries", 3)),
        )
        self.camara = CamaraOpenDataSource(self.client)
        self.camara_web = CamaraWebDetailSource(self.client, self.config.get("camara_project_ids", {}))
        self.senado = SenadoSource(self.client)
        self.bcn = BCNAssociatedProjectsSource(self.client)
        self.documents = OfficialProjectDocumentSource(self.client, self.config)
        self.press = ProjectPressSource(self.client, self.config)
        self.timezone = self.config["timezone"]

    def run(self, *, no_email: bool = False) -> dict[str, Any]:
        started_at = iso_now(self.timezone)
        previous_state = read_json(DATA_DIR / "state.json", {"projects": {}})
        discovery = read_json(DATA_DIR / "discovery_index.json", {"bulletins": {}})
        previous_projects: dict[str, Any] = previous_state.get("projects", {})
        bootstrap_rows = read_json(DATA_DIR / "bootstrap_projects.json", [])
        bootstrap_projects = {
            item.get("bulletin"): item
            for item in bootstrap_rows
            if isinstance(item, dict) and item.get("bulletin")
        }
        excluded_cfg = self.config.get("excluded_bulletins", {}) or {}
        excluded_bulletins = set(excluded_cfg if isinstance(excluded_cfg, dict) else excluded_cfg)
        # La depuración es previa a cualquier respaldo: un boletín excluido no puede
        # reaparecer por fallback de estado, alertas históricas o fallas de fuentes.
        previous_projects = {
            bulletin: value for bulletin, value in previous_projects.items()
            if bulletin not in excluded_bulletins
        }
        bootstrap_projects = {
            bulletin: value for bulletin, value in bootstrap_projects.items()
            if bulletin not in excluded_bulletins
        }
        continuity_projects = previous_projects or bootstrap_projects
        if isinstance(previous_state, dict):
            previous_state["projects"] = previous_projects
        if isinstance(discovery, dict) and isinstance(discovery.get("bulletins"), dict):
            discovery["bulletins"] = {
                bulletin: value for bulletin, value in discovery["bulletins"].items()
                if bulletin not in excluded_bulletins
            }
        is_first_discovery = not bool(discovery.get("bulletins"))

        source_health: dict[str, dict[str, Any]] = {}
        candidates: dict[str, CandidateProject] = {}

        def merge_many(items: list[CandidateProject]) -> None:
            for item in items:
                if item.bulletin in candidates:
                    candidates[item.bulletin].merge(item)
                else:
                    candidates[item.bulletin] = item

        now = local_now(self.timezone)
        years = [now.year - offset for offset in range(int(self.config.get("discovery_years", 3)))]
        try:
            camara_items: list[CandidateProject] = []
            for year in years:
                camara_items.extend(self.camara.list_by_year(year))
            merge_many(camara_items)
            source_health["Cámara XML"] = {"ok": bool(camara_items), "items": len(camara_items), "years": years, "degraded": not bool(camara_items), "note": "Sin filas: posible cambio de esquema o indisponibilidad." if not camara_items else "Descubrimiento estructurado operativo."}
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló descubrimiento Cámara")
            source_health["Cámara XML"] = {"ok": False, "error": str(exc)}

        try:
            senate_current = self.senado.list_current_projects(
                int(self.config.get("senate_discovery_days", 420))
            )
            merge_many(senate_current)
            source_health["Senado proyectos recientes"] = {
                "ok": bool(senate_current),
                "items": len(senate_current),
                "degraded": not bool(senate_current),
                "note": "Portada oficial: solo filas En tramitación con fecha reciente.",
            }
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló descubrimiento de proyectos recientes del Senado")
            source_health["Senado proyectos recientes"] = {"ok": False, "error": str(exc)}

        try:
            senate_recent = self.senado.recent_movements()
            merge_many(senate_recent)
            source_health["Senado actividad reciente"] = {
                "ok": True,
                "items": len(senate_recent),
                "note": "Filas exactas de Sala y comisiones tratadas recientemente.",
            }
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló actividad reciente del Senado")
            source_health["Senado actividad reciente"] = {"ok": False, "error": str(exc)}

        try:
            bcn_items = self.bcn.list_associated()
            merge_many(bcn_items)
            source_health["BCN Ley 19.913"] = {
                "ok": True,
                "items": len(bcn_items),
                "note": "Solo descubrimiento histórico; Cámara o Senado deben acreditar vigencia.",
            }
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló lista BCN")
            source_health["BCN Ley 19.913"] = {"ok": False, "error": str(exc)}

        for bulletin in self.config.get("seed_bulletins", []):
            if bulletin in excluded_bulletins:
                continue
            candidates.setdefault(
                bulletin,
                CandidateProject(
                    bulletin=bulletin,
                    source_urls=[self.senado.DETAIL_URL.format(bulletin=bulletin)],
                    discovered_from=["Configuración inicial vigente"],
                ),
            )

        for bulletin in excluded_bulletins:
            candidates.pop(bulletin, None)

        # La ficha anterior es respaldo de continuidad, con autoridad menor que
        # cualquier nueva extracción oficial.
        for bulletin, old in continuity_projects.items():
            previous_meta = dict(old.get("metadata", {}) or {})
            previous_meta["field_ranks"] = {field: 5 for field in CandidateProject._SCALAR_FIELDS}
            # La ficha heredada sirve como respaldo descriptivo, pero no puede
            # acreditar por sí sola que un proyecto siga vigente. Esto evita que
            # boletines históricos reaparezcan cuando una fuente puntual falla.
            for verification_key in (
                "entry_date_verified", "official_status_verified", "movement_verified",
                "movement_authoritative", "senate_current_list_verified",
                "official_detail_verified",
            ):
                previous_meta[verification_key] = False
            previous_meta["inherited_fallback"] = True
            previous_candidate = CandidateProject(
                bulletin=bulletin,
                title=old.get("title", ""), entry_date=old.get("entry_date", ""),
                initiative_type=old.get("initiative_type", ""), origin_chamber=old.get("origin_chamber", ""),
                state=old.get("state", ""), stage=old.get("stage", ""), commission=old.get("commission", ""),
                urgency=old.get("urgency", ""), latest_movement=old.get("latest_movement", ""),
                latest_movement_date=old.get("latest_movement_date", ""), source_urls=old.get("source_urls", []),
                discovered_from=old.get("discovered_from", []), evidence_text=old.get("evidence_text", ""),
                raw_hash=old.get("raw_hash", ""), metadata=previous_meta,
            )
            candidates.setdefault(bulletin, previous_candidate).merge(previous_candidate)

        seen_before = set(discovery.get("bulletins", {}))
        newly_discovered = set(candidates) - seen_before
        direct_bcn = {b for b, c in candidates.items() if c.metadata.get("bcn_associated")}
        seed = set(self.config.get("seed_bulletins", []))
        tracked = set(continuity_projects)

        # Revisión documental de proyectos recientes: permite detectar referencias
        # incorporadas en indicaciones, informes u oficios aunque el título no sea LA/FT.
        document_scanned = 0
        document_matches = 0
        if self.config.get("official_document_scan_enabled", True):
            scan_days = int(self.config.get("official_document_scan_days", 420))
            scan_limit = int(self.config.get("official_document_scan_max_candidates_per_run", 35))
            today = local_now(self.timezone).date()
            eligible_for_scan = []
            for bulletin, candidate in candidates.items():
                if bulletin in excluded_bulletins:
                    continue
                initial = classify(candidate, self.config)
                entry = parse_legislative_date(candidate.entry_date)
                recent = bool(entry and -31 <= (today - entry).days <= scan_days)
                if bulletin in seed or bulletin in tracked or initial["relevance_level"] == 0 and recent:
                    eligible_for_scan.append((entry.isoformat() if entry else "", bulletin, candidate))
            eligible_for_scan.sort(reverse=True)
            for _, bulletin, candidate in eligible_for_scan[:scan_limit]:
                try:
                    scanned = self.documents.scan(candidate, include_all=False)
                    document_scanned += 1
                    if scanned.metadata.get("official_documents_matched"):
                        document_matches += len(scanned.metadata["official_documents_matched"] or [])
                    candidate.merge(scanned)
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("No se pudo revisar documentos oficiales para %s: %s", bulletin, exc)
            source_health["Documentos oficiales"] = {
                "ok": True,
                "items": document_matches,
                "projects_searched": document_scanned,
                "note": "Indicaciones, informes y oficios; permite descubrir impacto UAF posterior al ingreso.",
            }

        enriched_count = 0
        verified_stage_count = 0
        verified_movement_count = 0
        verified_detail_bulletins: set[str] = set()
        current_projects: dict[str, Any] = {}
        excluded_projects: dict[str, Any] = {}
        for bulletin, candidate in sorted(candidates.items()):
            if bulletin in excluded_bulletins:
                continue
            candidate.metadata["newly_discovered"] = bulletin in newly_discovered and not is_first_discovery
            initial = classify(candidate, self.config)
            should_enrich = (
                bulletin in seed or bulletin in tracked or bulletin in direct_bcn
                or initial["relevance_level"] > 0
                or (bulletin in newly_discovered and not is_first_discovery)
            )
            if should_enrich:
                detail_success = False
                try:
                    camara_detail = self.camara.detail(bulletin)
                    candidate.merge(camara_detail)
                    detail_success = True
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("No se obtuvo detalle Cámara para %s: %s", bulletin, exc)
                try:
                    camara_web_detail = self.camara_web.detail(bulletin)
                    candidate.merge(camara_web_detail)
                    detail_success = True
                    source_health.setdefault("Cámara web fichas", {"ok": True, "items": 0})
                    source_health["Cámara web fichas"]["items"] += 1
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("No se obtuvo ficha web Cámara para %s: %s", bulletin, exc)
                    source_health.setdefault("Cámara web fichas", {"ok": False, "items": 0, "errors": 0})
                    source_health["Cámara web fichas"]["errors"] = source_health["Cámara web fichas"].get("errors", 0) + 1
                try:
                    # La ficha individual del Senado se consulta después. Sus
                    # campos de etapa e informe tienen la mayor autoridad, pero
                    # el movimiento se fusiona por fecha entre fuentes oficiales.
                    senate_detail = self.senado.detail(bulletin)
                    candidate.merge(senate_detail)
                    detail_success = True
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("No se obtuvo detalle Senado para %s: %s", bulletin, exc)
                if detail_success:
                    enriched_count += 1
                if candidate.metadata.get("official_status_verified") and candidate.stage:
                    verified_stage_count += 1
                    verified_detail_bulletins.add(bulletin)
                if candidate.metadata.get("movement_verified") and candidate.latest_movement_date:
                    verified_movement_count += 1
                    verified_detail_bulletins.add(bulletin)

                # Con la ficha legislativa ya enriquecida se revisan también los
                # documentos enlazados en la columna Documentos del Senado y las
                # presentaciones ante comisión. Esta segunda pasada construye
                # reseñas para la ficha, no solo señales de descubrimiento.
                try:
                    document_detail = self.documents.scan(candidate, include_all=True)
                    candidate.merge(document_detail)
                    document_scanned += 1
                    document_matches += len(
                        document_detail.metadata.get("official_document_reviews", []) or []
                    )
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("No se pudieron reseñar documentos de %s: %s", bulletin, exc)

            analyzed = classify(candidate, self.config)
            if analyzed["relevance_level"] <= 0:
                continue
            if analyzed.get("is_current"):
                current_projects[bulletin] = analyzed
            else:
                excluded_projects[bulletin] = analyzed

        if self.config.get("official_document_scan_enabled", True):
            source_health["Documentos oficiales"] = {
                "ok": True,
                "items": document_matches,
                "projects_searched": document_scanned,
                "note": (
                    "Se leen enlaces de Cámara y de la columna Documentos del Senado; "
                    "las reseñas son extractivas y quedan vinculadas al documento original."
                ),
            }

        # Continuidad operacional: una caída, bloqueo 403 o cambio de HTML no
        # puede reemplazar el último conjunto válido por un tablero vacío.
        fallback_used = _continuity_needed(
            len(current_projects),
            len(continuity_projects),
            len(verified_detail_bulletins),
            self.config,
        )
        if fallback_used:
            current_projects = {
                bulletin: {**project, "data_continuity_fallback": True}
                for bulletin, project in continuity_projects.items()
                if bulletin not in excluded_bulletins
            }
            excluded_projects = {}

        annotate_initiative_groups(current_projects)

        # Cobertura de prensa: complemento documental, separado del fingerprint
        # legislativo para no producir correos por noticias nuevas.
        if self.config.get("press_enabled", True) and current_projects:
            try:
                searched, press_items = self.press.enrich(current_projects)
                source_health["Prensa de proyectos"] = {
                    "ok": True,
                    "items": press_items,
                    "projects_searched": searched,
                    "note": "Google News Chile + lista blanca; no modifica el estado legislativo.",
                }
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falló cobertura de prensa")
                source_health["Prensa de proyectos"] = {"ok": False, "error": str(exc)}

        current_projects = {
            bulletin: sanitize_project_record(project)
            for bulletin, project in current_projects.items()
        }
        excluded_projects = {
            bulletin: sanitize_project_record(project)
            for bulletin, project in excluded_projects.items()
        }

        alerts = compare_projects(previous_state, current_projects, self.config, excluded_projects)
        finished_at = iso_now(self.timezone)
        alerts_with_time = [{"detected_at": finished_at, **alert} for alert in alerts]
        exclusion_counts = Counter(item.get("lifecycle_code", "unknown") for item in excluded_projects.values())
        lifecycle_counts = Counter(flag for item in current_projects.values() for flag in item.get("lifecycle_flags", []))
        status = {
            "version": self.config.get("version"),
            "started_at": started_at,
            "finished_at": finished_at,
            "sources": source_health,
            "candidates_discovered": len(candidates),
            "newly_discovered": len(newly_discovered),
            "projects_monitored": len(current_projects),
            "projects_enriched": enriched_count,
            "stages_verified": verified_stage_count,
            "movements_verified": verified_movement_count,
            "verified_detail_bulletins": len(verified_detail_bulletins),
            "continuity_fallback_used": fallback_used,
            "data_freshness": "último estado válido conservado" if fallback_used else "actualizado desde fuentes oficiales",
            "alerts_generated": len(alerts),
            "baseline": not bool(previous_projects),
            "lifecycle_counts": dict(lifecycle_counts),
            "excluded_count": len(excluded_projects),
            "exclusion_counts": dict(exclusion_counts),
            "eligibility_rule": (
                "Solo iniciativas recientes o con movimiento legislativo verificado, de relevancia directa para la Ley 19.913 "
                "o pertinencia LA/FT comprobable. La etapa e informe provienen de la ficha individual oficial; las fechas "
                "solo se publican cuando pertenecen a una fila de tramitación del mismo boletín."
            ),
        }

        previous_alerts = [
            item for item in read_json(DATA_DIR / "alerts.json", [])
            if item.get("bulletin") not in excluded_bulletins
        ]
        new_ids = {a["id"] for a in alerts_with_time}
        merged_alerts = alerts_with_time + [item for item in previous_alerts if item.get("id") not in new_ids]
        merged_alerts = merged_alerts[:250]

        new_discovery_map = {
            bulletin: value for bulletin, value in discovery.get("bulletins", {}).items()
            if bulletin not in excluded_bulletins
        }
        for bulletin, candidate in candidates.items():
            if bulletin in excluded_bulletins:
                continue
            record = new_discovery_map.setdefault(bulletin, {"first_seen": finished_at})
            record["last_seen"] = finished_at
            record["title"] = candidate.title or record.get("title", "")

        project_list = sorted(current_projects.values(), key=_project_order, reverse=True)
        write_json(DATA_DIR / "discovery_index.json", {"bulletins": new_discovery_map})
        write_json(DATA_DIR / "state.json", {"last_run_at": finished_at, "projects": current_projects})
        write_json(DATA_DIR / "projects.json", project_list)
        write_json(DATA_DIR / "alerts.json", merged_alerts)
        write_json(DATA_DIR / "status.json", status)
        write_json(DATA_DIR / "exclusion_summary.json", {
            "generated_at": finished_at,
            "total": len(excluded_projects),
            "by_reason": dict(exclusion_counts),
            "rule": status["eligibility_rule"],
        })

        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        render_dashboard(project_list, merged_alerts, status, DOCS_DIR / "index.html")
        write_json(DOCS_DIR / "projects.json", project_list)
        write_json(DOCS_DIR / "alerts.json", merged_alerts)
        write_json(DOCS_DIR / "status.json", status)

        if alerts:
            history_path = DATA_DIR / "history.jsonl"
            with history_path.open("a", encoding="utf-8") as fh:
                for alert in alerts_with_time:
                    fh.write(json.dumps(alert, ensure_ascii=False) + "\n")

        email_sent = False
        email_message = "Correo omitido por parámetro"
        if not no_email:
            try:
                email_sent, email_message = send_alert_email(alerts_with_time, status)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falló envío de correo")
                email_message = f"Error al enviar correo: {exc}"
        status["email_sent"] = email_sent
        status["email_message"] = email_message
        write_json(DATA_DIR / "status.json", status)
        write_json(DOCS_DIR / "status.json", status)
        render_dashboard(project_list, merged_alerts, status, DOCS_DIR / "index.html")
        return status


def render_only() -> Path:
    projects = read_json(DATA_DIR / "projects.json", [])
    alerts = read_json(DATA_DIR / "alerts.json", [])
    status = read_json(DATA_DIR / "status.json", {"finished_at": "", "sources": {}})
    return render_dashboard(projects, alerts, status, DOCS_DIR / "index.html")
