from pathlib import Path

from monitor_uaf.render import (
    prepare_dashboard_alerts,
    prepare_dashboard_projects,
    render_dashboard,
)


def test_prepare_dashboard_projects_accepts_state_mapping_and_deduplicates():
    state = {
        "16764-03": {
            "bulletin": "16764-03",
            "title": "Límite al efectivo",
            "priority_score": 80,
            "metadata": {"raw_html": "x" * 50000},
        },
        "18373-07": {
            "bulletin": "18373-07",
            "title": "Secreto bancario",
            "priority_score": 90,
        },
    }
    result = prepare_dashboard_projects(state)
    assert [item["bulletin"] for item in result] == ["18373-07", "16764-03"]
    assert "raw_html" not in result[1].get("metadata", {})


def test_prepare_dashboard_alerts_accepts_container_and_removes_duplicates():
    alert = {
        "bulletin": "16764-03",
        "type": "new_proceeding",
        "detected_at": "2026-08-04T10:00:00",
        "message": "Nuevo movimiento",
    }
    result = prepare_dashboard_alerts({"alerts": [alert, alert]})
    assert len(result) == 1
    assert result[0]["bulletin"] == "16764-03"


def test_render_dashboard_accepts_prepared_records(tmp_path: Path):
    output = tmp_path / "index.html"
    projects = prepare_dashboard_projects([{"bulletin": "16764-03", "title": "Proyecto"}])
    alerts = prepare_dashboard_alerts([])
    generated = render_dashboard(projects, alerts, {"finished_at": "2026-08-04"}, output)
    assert generated.exists()
    assert "16764-03" in generated.read_text(encoding="utf-8")
