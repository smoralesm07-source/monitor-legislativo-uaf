from pathlib import Path

from monitor_uaf.analysis import classify, compare_projects
from monitor_uaf.config import load_config
from monitor_uaf.http_client import HttpClient
from monitor_uaf.models import CandidateProject
from monitor_uaf.sources import CamaraOpenDataSource

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = load_config()


def test_direct_classification():
    project = CandidateProject(
        bulletin="19000-25",
        title="Modifica la ley N° 19.913 para incorporar nuevos sujetos obligados",
        evidence_text="La Unidad de Análisis Financiero fiscalizará a nuevas entidades reportantes.",
    )
    result = classify(project, CONFIG)
    assert result["relevance_level"] == 1
    assert "Sujetos obligados" in result["impacts"]


def test_secondary_classification():
    project = CandidateProject(
        bulletin="19001-07",
        title="Crea un registro nacional de beneficiarios finales",
        evidence_text="El registro permitirá intercambio de información con el SII y acceso a bases de datos.",
    )
    result = classify(project, CONFIG)
    assert result["relevance_level"] == 2
    assert "Acceso a información" in result["impacts"]


def test_baseline_does_not_alert():
    current = {"19000-25": classify(CandidateProject(bulletin="19000-25", title="Modifica la ley 19.913"), CONFIG)}
    assert compare_projects({"projects": {}}, current, CONFIG) == []


def test_change_generates_alert():
    old_project = classify(CandidateProject(bulletin="19000-25", title="Modifica la ley 19.913", stage="Primer trámite"), CONFIG)
    new_project = classify(CandidateProject(bulletin="19000-25", title="Modifica la ley 19.913", stage="Segundo trámite aprobado"), CONFIG)
    alerts = compare_projects({"projects": {"19000-25": old_project}}, {"19000-25": new_project}, CONFIG)
    assert len(alerts) == 1
    assert alerts[0]["bulletin"] == "19000-25"
    assert alerts[0]["severity"] in {"Crítica", "Alta"}


def test_camara_year_parser(monkeypatch):
    source = CamaraOpenDataSource(HttpClient())
    xml_data = (FIXTURES / "camara_year.xml").read_bytes()
    monkeypatch.setattr(source, "_call", lambda method, params: xml_data)
    projects = source.list_by_year(2026)
    assert {p.bulletin for p in projects} == {"19000-25", "19001-07"}


def test_camara_detail_parser(monkeypatch):
    source = CamaraOpenDataSource(HttpClient())
    xml_data = (FIXTURES / "camara_detail.xml").read_bytes()
    monkeypatch.setattr(source, "_call", lambda method, params: xml_data)
    project = source.detail("19000-25")
    assert project.bulletin == "19000-25"
    assert "Primer trámite" in project.stage
    assert "Suma urgencia" in project.urgency


def test_dashboard_includes_active_navigation_and_temporal_chart(tmp_path):
    from monitor_uaf.render import render_dashboard

    project = classify(
        CandidateProject(
            bulletin="19002-25",
            title="Modifica la ley N° 19.913 para incorporar nuevos sujetos obligados",
            latest_movement="Pasa a segundo trámite constitucional",
            latest_movement_date="2026-08-03",
        ),
        CONFIG,
    )
    alert = {
        "id": "demo-alert",
        "detected_at": "2026-08-03T12:00:00-04:00",
        "bulletin": project["bulletin"],
        "title": project["title"],
        "severity": "Alta",
        "relevance_level": 1,
        "changes": [],
    }
    output = tmp_path / "index.html"
    render_dashboard([project], [alert], {"alerts_generated": 1, "sources": {}}, output)
    page = output.read_text(encoding="utf-8")
    assert "Análisis temporal de movimientos" in page
    assert "Modifican Ley 19.913" in page
    assert "navigate('direct'" in page
    assert "demo-alert" in page
