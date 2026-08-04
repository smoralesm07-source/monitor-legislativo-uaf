#!/usr/bin/env python3
"""Verifica el contrato de importaciones antes de ejecutar el monitor."""

checks = []

try:
    from monitor_uaf.analysis import (
        annotate_initiative_groups,
        classify,
        compare_projects,
        sanitize_project_record,
    )
    checks.append(("monitor_uaf.analysis", True, "OK"))
except Exception as exc:
    checks.append(("monitor_uaf.analysis", False, f"{type(exc).__name__}: {exc}"))

try:
    from monitor_uaf.render import (
        prepare_dashboard_alerts,
        prepare_dashboard_projects,
        render_dashboard,
    )
    checks.append(("monitor_uaf.render", True, "OK"))
except Exception as exc:
    checks.append(("monitor_uaf.render", False, f"{type(exc).__name__}: {exc}"))

failed = False
for module, ok, detail in checks:
    print(f"[{'OK' if ok else 'ERROR'}] {module}: {detail}")
    failed = failed or not ok

raise SystemExit(1 if failed else 0)
