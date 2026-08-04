from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from monitor_uaf.analysis import sanitize_project_record
from monitor_uaf.config import DATA_DIR, DOCS_DIR, load_config
from monitor_uaf.render import prepare_dashboard_alerts, prepare_dashboard_projects, render_dashboard
from monitor_uaf.utils import read_json, write_json

GENERATED_FILES = [
    DATA_DIR / "state.json",
    DATA_DIR / "projects.json",
    DATA_DIR / "alerts.json",
    DATA_DIR / "history.jsonl",
    DOCS_DIR / "index.html",
    DOCS_DIR / "projects.json",
    DOCS_DIR / "alerts.json",
]


def compact_history(path: Path, max_entries: int) -> None:
    if not path.exists():
        return
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                entries.append(prepare_dashboard_alerts([value])[0])
    entries = entries[-max_entries:]
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    temp.replace(path)


def compact_repository() -> dict[str, int]:
    config = load_config()
    state = read_json(DATA_DIR / "state.json", {"projects": {}})
    raw_projects = state.get("projects", {}) if isinstance(state, dict) else {}
    compact_projects = {
        bulletin: sanitize_project_record(project)
        for bulletin, project in raw_projects.items()
        if isinstance(project, dict)
    }
    compact_state = {
        "last_run_at": state.get("last_run_at", "") if isinstance(state, dict) else "",
        "projects": compact_projects,
    }
    write_json(DATA_DIR / "state.json", compact_state)

    state_project_list = sorted(
        compact_projects.values(),
        key=lambda item: item.get("priority_score", 0),
        reverse=True,
    )
    public_projects = prepare_dashboard_projects(state_project_list)
    alerts = prepare_dashboard_alerts(read_json(DATA_DIR / "alerts.json", []))
    status = read_json(DATA_DIR / "status.json", {"finished_at": "", "sources": {}})

    write_json(DATA_DIR / "projects.json", public_projects)
    write_json(DATA_DIR / "alerts.json", alerts)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DOCS_DIR / "projects.json", public_projects)
    write_json(DOCS_DIR / "alerts.json", alerts)
    write_json(DOCS_DIR / "status.json", status)
    render_dashboard(public_projects, alerts, status, DOCS_DIR / "index.html")

    compact_history(DATA_DIR / "history.jsonl", int(config.get("history_max_entries", 2000)))
    return {str(path): path.stat().st_size for path in GENERATED_FILES if path.exists()}


def check_sizes(max_mb: float) -> dict[str, int]:
    sizes = {str(path): path.stat().st_size for path in GENERATED_FILES if path.exists()}
    maximum = int(max_mb * 1024 * 1024)
    oversized = {path: size for path, size in sizes.items() if size > maximum}
    if oversized:
        details = ", ".join(f"{path}={size / 1024 / 1024:.2f} MB" for path, size in oversized.items())
        raise SystemExit(
            f"Archivos generados sobre el límite interno de {max_mb:.1f} MB: {details}. "
            "Se canceló antes de crear otro commit sobredimensionado."
        )
    return sizes


def main() -> int:
    parser = argparse.ArgumentParser(description="Compacta y valida los archivos persistentes del monitor")
    parser.add_argument("--check-only", action="store_true", help="Solo valida tamaños; no modifica archivos")
    args = parser.parse_args()
    config = load_config()
    max_mb = float(config.get("max_generated_file_mb", 8))
    sizes = check_sizes(max_mb) if args.check_only else compact_repository()
    if not args.check_only:
        sizes = check_sizes(max_mb)
    for path, size in sorted(sizes.items()):
        print(f"{path}: {size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
