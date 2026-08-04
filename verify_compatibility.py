#!/usr/bin/env python3
from monitor_uaf.analysis import annotate_initiative_groups, classify, compare_projects, sanitize_project_record
from monitor_uaf.pipeline import MonitorPipeline, render_only
from monitor_uaf.documents import OfficialProjectDocumentSource
from monitor_uaf.press import ProjectPressSource
from monitor_uaf.render import prepare_dashboard_alerts, prepare_dashboard_projects, render_dashboard

checks = {
    "annotate_initiative_groups": annotate_initiative_groups,
    "classify": classify,
    "compare_projects": compare_projects,
    "sanitize_project_record": sanitize_project_record,
    "prepare_dashboard_alerts": prepare_dashboard_alerts,
    "prepare_dashboard_projects": prepare_dashboard_projects,
    "render_dashboard": render_dashboard,
    "MonitorPipeline": MonitorPipeline,
    "render_only": render_only,
    "ProjectPressSource": ProjectPressSource,
    "OfficialProjectDocumentSource": OfficialProjectDocumentSource,
}
for name, value in checks.items():
    if not callable(value):
        raise SystemExit(f"[ERROR] {name} no es invocable")
    print(f"[OK] {name}")
