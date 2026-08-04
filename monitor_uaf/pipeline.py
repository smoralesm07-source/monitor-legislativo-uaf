from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from .analysis import annotate_initiative_groups, classify, compare_projects, sanitize_project_record
from .config import DATA_DIR, DOCS_DIR, load_config
from .http_client import HttpClient
from .models import CandidateProject
from .notifier import filter_unsent_alerts, send_alert_email, updated_email_log
from .render import prepare_dashboard_alerts, prepare_dashboard_projects, render_dashboard
from .sources import CamaraOpenDataSource, SenadoSource
from .utils import iso_now, local_now, parse_legislative_date, read_json, write_json

LOGGER = logging.getLogger(__name__)


class MonitorPipeline:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_config()
        self.client = HttpClient(
            timeout=int(self.config.get("request_timeout_seconds", 35)),
            retries=int(self.config.get("request_retries", 3)),
        )
        self.camara = CamaraOpenDataSource(self.client)
        self.senado = SenadoSource(self.client)
        self.timezone = self.config["timezone"]

    def run(self, *, no_email: bool = False) -> dict[str, Any]:
        started_at = iso_now(self.timezone)
        previous_state = read_json(DATA_DIR / "state.json", {"projects": {}})
        discovery = read_json(DATA_DIR / "discovery_index.json", {"bulletins": {}})
        previous_projects: dict[str, Any] = previous_state.get("projects", {})
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
            source_health["Cámara XML"] = {"ok": True, "items": len(camara_items), "years": years}
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló descubrimiento Cámara")
            source_health["Cámara XML"] = {"ok": False, "error": str(exc)}

        try:
            since = now.date().replace(year=now.year - int(self.config.get("discovery_years", 3)))
            senate_items = self.senado.recent_movements(since)
            merge_many(senate_items)
            source_health["Senado XML movimientos"] = {
                "ok": True,
                "items": len(senate_items),
                "since": since.isoformat(),
                "note": "Descubrimiento de boletines con movimientos oficiales desde la fecha indicada.",
            }
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló descubrimiento Senado")
            source_health["Senado XML movimientos"] = {"ok": False, "error": str(exc)}

        for bulletin in self.config.get("seed_bulletins", []):
            candidates.setdefault(
                bulletin,
                CandidateProject(
                    bulletin=bulletin,
                    title="",
                    source_urls=[self.senado.DETAIL_URL.format(bulletin=bulletin)],
                    discovered_from=["Configuración inicial vigente"],
                ),
            )

        # Los proyectos ya vigentes se vuelven a consultar aunque no aparezcan en las listas recientes.
        for bulletin, old in previous_projects.items():
            previous_candidate = CandidateProject(
                bulletin=bulletin,
                title=old.get("title", ""),
                entry_date=old.get("entry_date", ""),
                initiative_type=old.get("initiative_type", ""),
                origin_chamber=old.get("origin_chamber", ""),
                state=old.get("state", ""),
                stage=old.get("stage", ""),
                commission=old.get("commission", ""),
                urgency=old.get("urgency", ""),
                latest_movement=old.get("latest_movement", ""),
                latest_movement_date=old.get("latest_movement_date", ""),
                legislative_history=old.get("legislative_history", []),
                source_urls=[u for u in old.get("source_urls", []) if "bcn.cl" not in u and "leychile.cl" not in u],
                discovered_from=old.get("discovered_from", []),
                # La evidencia cruda de ejecuciones anteriores nunca se reinyecta: fue la
                # causa del crecimiento acumulativo de state.json en versiones previas.
                evidence_text="",
                raw_hash=old.get("raw_hash", ""),
                metadata={
                    key: value
                    for key, value in (old.get("metadata", {}) or {}).items()
                    if key in {"newly_discovered", "recent_feed", "title_rank", "movement_rank", "movement_source", "official_date_verified"}
                },
            )
            candidates.setdefault(bulletin, previous_candidate).merge(previous_candidate)

        seen_before = set(discovery.get("bulletins", {}))
        newly_discovered = set(candidates) - seen_before
        seed = set(self.config.get("seed_bulletins", []))
        tracked = set(previous_projects)

        enriched_count = 0
        camara_detail_ok = 0
        camara_detail_fail = 0
        senado_detail_ok = 0
        senado_detail_fail = 0
        irrelevant_count = 0
        current_projects: dict[str, Any] = {}
        excluded_projects: dict[str, Any] = {}
        for bulletin, candidate in sorted(candidates.items()):
            candidate.metadata["newly_discovered"] = bulletin in newly_discovered and not is_first_discovery
            initial = classify(candidate, self.config)
            should_enrich = (
                bulletin in seed
                or bulletin in tracked
                or initial["relevance_level"] > 0
                or (bulletin in newly_discovered and not is_first_discovery)
            )
            if should_enrich:
                detail_success = False
                try:
                    candidate.merge(self.camara.detail(bulletin))
                    camara_detail_ok += 1
                    detail_success = True
                except Exception as exc:  # noqa: BLE001
                    camara_detail_fail += 1
                    LOGGER.warning("No se obtuvo detalle Cámara para %s: %s", bulletin, exc)
                try:
                    candidate.merge(self.senado.detail(bulletin))
                    senado_detail_ok += 1
                    detail_success = True
                except Exception as exc:  # noqa: BLE001
                    senado_detail_fail += 1
                    LOGGER.warning("No se obtuvo detalle Senado para %s: %s", bulletin, exc)
                if detail_success:
                    enriched_count += 1

            analyzed = classify(candidate, self.config)
            if analyzed["relevance_level"] <= 0:
                irrelevant_count += 1
                continue
            if analyzed.get("is_current"):
                current_projects[bulletin] = analyzed
            else:
                excluded_projects[bulletin] = analyzed

        source_health["Cámara detalle oficial"] = {
            "ok": camara_detail_ok > 0,
            "items": camara_detail_ok,
            "errors": camara_detail_fail,
            "attempts": camara_detail_ok + camara_detail_fail,
            "note": "Fechas y movimientos obtenidos del XML oficial por boletín.",
        }
        source_health["Senado fichas oficiales"] = {
            "ok": senado_detail_ok > 0,
            "items": senado_detail_ok,
            "errors": senado_detail_fail,
            "attempts": senado_detail_ok + senado_detail_fail,
            "note": "Se consultan las fichas oficiales; no se usa la lista de 'últimos vistos' para fechar trámites.",
        }

        current_projects = annotate_initiative_groups(current_projects, self.config)

        # Si fallaron todas las fuentes, conserva solo la cartera previa que todavía
        # tenga una fecha oficial reciente. Esto evita resucitar proyectos históricos.
        if source_health and not any(item.get("ok") for item in source_health.values()):
            cutoff = local_now(self.timezone).date() - timedelta(days=int(self.config.get("active_movement_days", 730)))
            current_projects = {}
            for bulletin, project in previous_projects.items():
                reference = parse_legislative_date(
                    project.get("reference_date")
                    or project.get("latest_movement_date")
                    or project.get("entry_date")
                )
                if (
                    project.get("relevance_level") in {1, 2}
                    and project.get("is_current")
                    and reference
                    and reference >= cutoff
                ):
                    current_projects[bulletin] = sanitize_project_record(project)
            excluded_projects = {}

        # Compacta incluso estados heredados de v1.0.3: nunca persistir evidencia cruda.
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
        lifecycle_counts = Counter(
            flag
            for item in current_projects.values()
            for flag in item.get("lifecycle_flags", [])
        )
        status = {
            "version": self.config.get("version"),
            "started_at": started_at,
            "finished_at": finished_at,
            "sources": source_health,
            "candidates_discovered": len(candidates),
            "newly_discovered": len(newly_discovered),
            "projects_monitored": len(current_projects),
            "projects_enriched": enriched_count,
            "alerts_generated": len(alerts),
            "baseline": not bool(previous_projects),
            "lifecycle_counts": dict(lifecycle_counts),
            "excluded_count": len(excluded_projects),
            "irrelevant_discarded": irrelevant_count,
            "initiative_groups": len({item.get("initiative_group_id", item.get("bulletin")) for item in current_projects.values()}),
            "direct_projects": sum(1 for item in current_projects.values() if item.get("relevance_level") == 1),
            "laft_related_projects": sum(1 for item in current_projects.values() if item.get("relevance_level") == 2),
            "legislative_history_years": int(self.config.get("legislative_history_years", 3)),
            "exclusion_counts": dict(exclusion_counts),
            "eligibility_rule": (
                "Solo se publican iniciativas vigentes detectadas en Cámara o Senado que modifican la Ley 19.913 "
                "o presentan una conexión explícita y verificable con prevención de LA/FT o delitos base."
            ),
        }

        previous_alerts = read_json(DATA_DIR / "alerts.json", [])
        new_ids = {a["id"] for a in alerts_with_time}
        merged_alerts = alerts_with_time + [item for item in previous_alerts if item.get("id") not in new_ids]
        # Elimina del historial visible las alertas de boletines que la nueva clasificación
        # precisa determinó ajenos a Ley 19.913/LAFT.
        merged_alerts = [item for item in merged_alerts if item.get("bulletin") in current_projects][:250]

        new_discovery_map = discovery.get("bulletins", {})
        for bulletin, candidate in candidates.items():
            record = new_discovery_map.setdefault(bulletin, {"first_seen": finished_at})
            record["last_seen"] = finished_at
            record["title"] = candidate.title or record.get("title", "")
        write_json(DATA_DIR / "discovery_index.json", {"bulletins": new_discovery_map})
        write_json(DATA_DIR / "state.json", {"last_run_at": finished_at, "projects": current_projects})
        state_project_list = sorted(current_projects.values(), key=lambda item: item.get("priority_score", 0), reverse=True)
        project_list = prepare_dashboard_projects(state_project_list)
        merged_alerts = prepare_dashboard_alerts(merged_alerts)
        write_json(DATA_DIR / "projects.json", project_list)
        write_json(DATA_DIR / "alerts.json", merged_alerts)
        write_json(DATA_DIR / "status.json", status)
        write_json(
            DATA_DIR / "exclusion_summary.json",
            {
                "generated_at": finished_at,
                "total": len(excluded_projects),
                "by_reason": {**dict(exclusion_counts), "irrelevant_no_laft": irrelevant_count},
                "rule": status["eligibility_rule"],
            },
        )

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

        email_log_path = DATA_DIR / "email_log.json"
        email_log = read_json(email_log_path, {"sent_alert_ids": [], "last_sent_at": ""})
        unsent_alerts = filter_unsent_alerts(alerts_with_time, email_log)

        email_sent = False
        email_message = "Correo omitido por parámetro"
        if not no_email:
            if not unsent_alerts:
                email_message = "Sin alertas legislativas nuevas no enviadas"
            else:
                try:
                    email_sent, email_message = send_alert_email(unsent_alerts, status)
                    if email_sent:
                        email_log = updated_email_log(
                            email_log,
                            unsent_alerts,
                            finished_at,
                            max_ids=int(self.config.get("email_log_max_ids", 2000)),
                        )
                        write_json(email_log_path, email_log)
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("Falló envío de correo")
                    email_message = f"Error al enviar correo: {exc}"
        status["email_sent"] = email_sent
        status["email_message"] = email_message
        status["email_alerts_detected"] = len(alerts_with_time)
        status["email_alerts_pending"] = len(unsent_alerts)
        status["email_alerts_previously_sent"] = len(alerts_with_time) - len(unsent_alerts)
        write_json(DATA_DIR / "status.json", status)
        write_json(DOCS_DIR / "status.json", status)
        render_dashboard(project_list, merged_alerts, status, DOCS_DIR / "index.html")
        return status


def render_only() -> Path:
    projects = read_json(DATA_DIR / "projects.json", [])
    alerts = read_json(DATA_DIR / "alerts.json", [])
    status = read_json(DATA_DIR / "status.json", {"finished_at": "", "sources": {}})
    return render_dashboard(projects, alerts, status, DOCS_DIR / "index.html")
