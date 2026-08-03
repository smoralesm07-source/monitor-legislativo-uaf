from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from .analysis import classify, compare_projects
from .config import DATA_DIR, DOCS_DIR, load_config
from .http_client import HttpClient
from .models import CandidateProject
from .notifier import send_alert_email
from .render import render_dashboard
from .sources import BCNAssociatedProjectsSource, CamaraOpenDataSource, SenadoSource
from .utils import iso_now, local_now, read_json, write_json

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
        self.bcn = BCNAssociatedProjectsSource(self.client)
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
        years = [now.year - offset for offset in range(int(self.config.get("discovery_years", 2)))]
        try:
            camara_items: list[CandidateProject] = []
            for year in years:
                camara_items.extend(self.camara.list_by_year(year))
            merge_many(camara_items)
            source_health["Cámara XML"] = {"ok": True, "items": len(camara_items)}
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló descubrimiento Cámara")
            source_health["Cámara XML"] = {"ok": False, "error": str(exc)}

        try:
            senate_recent = self.senado.recent_movements()
            merge_many(senate_recent)
            source_health["Senado movimientos"] = {"ok": True, "items": len(senate_recent)}
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló movimientos Senado")
            source_health["Senado movimientos"] = {"ok": False, "error": str(exc)}

        try:
            bcn_items = self.bcn.list_associated()
            merge_many(bcn_items)
            source_health["BCN Ley 19.913"] = {"ok": True, "items": len(bcn_items)}
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Falló lista BCN")
            source_health["BCN Ley 19.913"] = {"ok": False, "error": str(exc)}

        for bulletin in self.config.get("seed_bulletins", []):
            candidates.setdefault(bulletin, CandidateProject(
                bulletin=bulletin,
                title="",
                source_urls=[self.senado.DETAIL_URL.format(bulletin=bulletin)],
                discovered_from=["Configuración inicial"],
            ))
        for bulletin, old in previous_projects.items():
            previous_candidate = CandidateProject(
                bulletin=bulletin,
                title=old.get("title", ""), state=old.get("state", ""), stage=old.get("stage", ""),
                commission=old.get("commission", ""), urgency=old.get("urgency", ""),
                latest_movement=old.get("latest_movement", ""), latest_movement_date=old.get("latest_movement_date", ""),
                source_urls=old.get("source_urls", []), discovered_from=old.get("discovered_from", []),
                evidence_text=old.get("evidence_text", ""), raw_hash=old.get("raw_hash", ""), metadata=old.get("metadata", {}),
            )
            candidates.setdefault(bulletin, previous_candidate).merge(previous_candidate)

        seen_before = set(discovery.get("bulletins", {}))
        newly_discovered = set(candidates) - seen_before
        direct_bcn = {b for b, c in candidates.items() if c.metadata.get("bcn_associated")}
        seed = set(self.config.get("seed_bulletins", []))
        tracked = set(previous_projects)

        enriched_count = 0
        current_projects: dict[str, Any] = {}
        for bulletin, candidate in sorted(candidates.items()):
            initial = classify(candidate, self.config)
            should_enrich = (
                bulletin in seed or bulletin in tracked or bulletin in direct_bcn or
                initial["relevance_level"] > 0 or (bulletin in newly_discovered and not is_first_discovery)
            )
            if should_enrich:
                detail_success = False
                try:
                    candidate.merge(self.camara.detail(bulletin))
                    detail_success = True
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("No se obtuvo detalle Cámara para %s: %s", bulletin, exc)
                try:
                    candidate.merge(self.senado.detail(bulletin))
                    detail_success = True
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("No se obtuvo detalle Senado para %s: %s", bulletin, exc)
                if detail_success:
                    enriched_count += 1
            analyzed = classify(candidate, self.config)
            if analyzed["relevance_level"] > 0 or bulletin in tracked or bulletin in seed or bulletin in direct_bcn:
                current_projects[bulletin] = analyzed

        # Si fallaron todas las fuentes, no reemplazar el estado por información parcial.
        if source_health and not any(item.get("ok") for item in source_health.values()):
            current_projects = previous_projects

        alerts = compare_projects(previous_state, current_projects, self.config)
        finished_at = iso_now(self.timezone)
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
        }

        previous_alerts = read_json(DATA_DIR / "alerts.json", [])
        existing_ids = {item.get("id") for item in previous_alerts}
        merged_alerts = alerts + [item for item in previous_alerts if item.get("id") not in {a["id"] for a in alerts}]
        merged_alerts = merged_alerts[:250]

        new_discovery_map = discovery.get("bulletins", {})
        for bulletin, candidate in candidates.items():
            record = new_discovery_map.setdefault(bulletin, {"first_seen": finished_at})
            record["last_seen"] = finished_at
            record["title"] = candidate.title or record.get("title", "")
        write_json(DATA_DIR / "discovery_index.json", {"bulletins": new_discovery_map})
        write_json(DATA_DIR / "state.json", {"last_run_at": finished_at, "projects": current_projects})
        project_list = sorted(current_projects.values(), key=lambda item: item.get("priority_score", 0), reverse=True)
        write_json(DATA_DIR / "projects.json", project_list)
        write_json(DATA_DIR / "alerts.json", merged_alerts)
        write_json(DATA_DIR / "status.json", status)

        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        render_dashboard(project_list, alerts, status, DOCS_DIR / "index.html")
        write_json(DOCS_DIR / "projects.json", project_list)
        write_json(DOCS_DIR / "alerts.json", alerts)
        write_json(DOCS_DIR / "status.json", status)

        if alerts:
            history_path = DATA_DIR / "history.jsonl"
            with history_path.open("a", encoding="utf-8") as fh:
                for alert in alerts:
                    fh.write(json.dumps({"detected_at": finished_at, **alert}, ensure_ascii=False) + "\n")

        email_sent = False
        email_message = "Correo omitido por parámetro"
        if not no_email:
            try:
                email_sent, email_message = send_alert_email(alerts, status)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Falló envío de correo")
                email_message = f"Error al enviar correo: {exc}"
        status["email_sent"] = email_sent
        status["email_message"] = email_message
        write_json(DATA_DIR / "status.json", status)
        write_json(DOCS_DIR / "status.json", status)
        render_dashboard(project_list, alerts, status, DOCS_DIR / "index.html")
        return status


def render_only() -> Path:
    projects = read_json(DATA_DIR / "projects.json", [])
    alerts = read_json(DATA_DIR / "alerts.json", [])
    status = read_json(DATA_DIR / "status.json", {"finished_at": "", "sources": {}})
    return render_dashboard(projects, alerts, status, DOCS_DIR / "index.html")
