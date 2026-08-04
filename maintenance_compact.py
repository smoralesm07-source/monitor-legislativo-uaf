#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from monitor_uaf.analysis import sanitize_project_record
from monitor_uaf.config import DATA_DIR, DOCS_DIR, load_config
from monitor_uaf.render import prepare_dashboard_alerts, prepare_dashboard_projects, render_dashboard
from monitor_uaf.utils import read_json, write_json

MAX_BYTES = {
    DATA_DIR / "state.json": 8_000_000,
    DATA_DIR / "projects.json": 5_000_000,
    DATA_DIR / "alerts.json": 4_000_000,
    DOCS_DIR / "index.html": 9_000_000,
}


def compact() -> None:
    config = load_config()
    excluded_cfg = config.get("excluded_bulletins", {}) or {}
    excluded = set(excluded_cfg if isinstance(excluded_cfg, dict) else excluded_cfg)
    state = read_json(DATA_DIR / "state.json", {"projects": {}})
    projects_mapping = state.get("projects", {}) if isinstance(state, dict) else {}
    if isinstance(projects_mapping, dict):
        clean_mapping = {
            key: sanitize_project_record(value)
            for key, value in projects_mapping.items()
            if isinstance(value, dict) and key not in excluded
        }
    else:
        clean_mapping = {
            item["bulletin"]: sanitize_project_record(item)
            for item in prepare_dashboard_projects(projects_mapping)
            if item.get("bulletin") not in excluded
        }
    state = {**(state if isinstance(state, dict) else {}), "projects": clean_mapping}
    project_source = list(clean_mapping.values()) or [
        item for item in read_json(DATA_DIR / "projects.json", [])
        if item.get("bulletin") not in excluded
    ] or [
        item for item in read_json(DATA_DIR / "bootstrap_projects.json", [])
        if item.get("bulletin") not in excluded
    ]
    projects = prepare_dashboard_projects(project_source)
    alerts = prepare_dashboard_alerts([
        item for item in read_json(DATA_DIR / "alerts.json", [])
        if item.get("bulletin") not in excluded
    ])
    status = read_json(DATA_DIR / "status.json", {"sources": {}})
    discovery = read_json(DATA_DIR / "discovery_index.json", {"bulletins": {}})
    if isinstance(discovery, dict) and isinstance(discovery.get("bulletins"), dict):
        discovery["bulletins"] = {
            bulletin: value for bulletin, value in discovery["bulletins"].items()
            if bulletin not in excluded
        }

    write_json(DATA_DIR / "state.json", state)
    write_json(DATA_DIR / "discovery_index.json", discovery)
    write_json(DATA_DIR / "projects.json", projects)
    write_json(DATA_DIR / "alerts.json", alerts)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DOCS_DIR / "projects.json", projects)
    write_json(DOCS_DIR / "alerts.json", alerts)
    write_json(DOCS_DIR / "status.json", status)
    render_dashboard(projects, alerts, status, DOCS_DIR / "index.html")


def check_sizes() -> None:
    oversized = []
    for path, limit in MAX_BYTES.items():
        if path.exists() and path.stat().st_size > limit:
            oversized.append(f"{path}: {path.stat().st_size:,} > {limit:,} bytes")
    if oversized:
        raise SystemExit("Archivos sobredimensionados:\n" + "\n".join(oversized))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not args.check_only:
        compact()
    check_sizes()
    print("Mantenimiento y validación completados.")


if __name__ == "__main__":
    main()
