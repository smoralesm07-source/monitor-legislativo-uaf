from pathlib import Path

from monitor_uaf.analysis import classify, compare_projects
from monitor_uaf.config import load_config
from monitor_uaf.http_client import FetchResult, HttpClient
from monitor_uaf.models import CandidateProject
from monitor_uaf.sources import CamaraOpenDataSource, SenadoSource

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



def test_senado_detail_parser_includes_proceedings_and_presentations(monkeypatch):
    source = SenadoSource(HttpClient())
    html_data = (FIXTURES / "senado_detail.html").read_bytes()
    monkeypatch.setattr(
        source.client,
        "get",
        lambda url, params=None: FetchResult(url=url, status_code=200, content=html_data, content_type="text/html; charset=utf-8"),
    )
    project = source.detail("16764-03")
    assert project.entry_date == "Miércoles 17 de Abril, 2024"
    assert project.origin_chamber == "Senado"
    assert project.initiative_type == "Moción"
    assert project.metadata["project_type"] == "Proyecto de ley"
    assert "16783-03" in project.metadata["refunded"]
    assert len(project.metadata["senado_proceedings"]) == 3
    assert project.metadata["senado_proceedings"][0]["documents"][0]["url"].endswith("/docs/mocion.pdf")
    assert len(project.metadata["commission_presentations"]) == 2
    assert project.latest_movement_date == "2024-08-27"


def test_new_commission_presentation_generates_alert():
    from datetime import timedelta
    from monitor_uaf.utils import local_now

    recent = (local_now(CONFIG["timezone"]).date() - timedelta(days=10)).isoformat()
    base = dict(
        bulletin="19998-25",
        title="Modifica la ley 19.913",
        entry_date=recent,
        state="Primer trámite constitucional",
        latest_movement="Cuenta del proyecto",
        latest_movement_date=recent,
    )
    old_project = CandidateProject(**base, metadata={
        "senado_detail_schema": "2",
        "commission_presentations": [{"date": recent, "title": "Presentación inicial", "organization": "UAF", "commission": "Hacienda", "documents": []}],
    })
    new_project = CandidateProject(**base, metadata={
        "senado_detail_schema": "2",
        "commission_presentations": [
            {"date": recent, "title": "Presentación inicial", "organization": "UAF", "commission": "Hacienda", "documents": []},
            {"date": recent, "title": "Nueva presentación", "organization": "Ministerio de Hacienda", "commission": "Hacienda", "documents": []},
        ],
    })
    old = classify(old_project, CONFIG)
    new = classify(new_project, CONFIG)
    alerts = compare_projects({"projects": {"19998-25": old}}, {"19998-25": new}, CONFIG)
    assert len(alerts) == 1
    assert any(change["field"] == "presentaciones_comision" for change in alerts[0]["changes"])

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
    assert "Cronología de tramitación" in page
    assert "Presentaciones ante comisión" in page
    assert "Decisiones sugeridas" not in page
    assert "Dimensiones de impacto" not in page


def test_terminal_project_is_excluded_from_active_portfolio():
    project = CandidateProject(
        bulletin="12000-25",
        title="Modifica la ley 19.913",
        state="Tramitación terminada (Ley N° 21.999 - Diario Oficial)",
        latest_movement_date="2026-07-01",
    )
    result = classify(project, CONFIG)
    assert result["relevance_level"] == 1
    assert result["is_current"] is False
    assert result["lifecycle_code"] == "terminal"


def test_stale_first_stage_is_not_considered_current():
    project = CandidateProject(
        bulletin="9000-25",
        title="Modifica la ley 19.913",
        entry_date="10/03/2002",
        state="Primer trámite constitucional",
        latest_movement="Cuenta del proyecto",
        latest_movement_date="10/03/2002",
    )
    result = classify(project, CONFIG)
    assert result["is_current"] is False
    assert result["lifecycle_code"] == "stale"


def test_recent_project_is_current_and_new():
    from datetime import timedelta
    from monitor_uaf.utils import local_now

    recent = (local_now(CONFIG["timezone"]).date() - timedelta(days=20)).isoformat()
    project = CandidateProject(
        bulletin="19999-25",
        title="Modifica la ley 19.913",
        entry_date=recent,
        state="Primer trámite constitucional",
        latest_movement="Ingreso de proyecto",
        latest_movement_date=recent,
    )
    result = classify(project, CONFIG)
    assert result["is_current"] is True
    assert "new" in result["lifecycle_flags"]
    assert "active" in result["lifecycle_flags"]
