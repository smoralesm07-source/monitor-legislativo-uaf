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
    assert project.latest_movement_date == "2024-06-04"


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
    assert "Materias con mayor actividad y avance" in page
    assert "Modifican Ley 19.913" in page
    assert "setLevel('1')" in page
    assert "demo-alert" in page
    assert "Cronología de tramitación" in page
    assert "Presentaciones ante comisión" in page
    assert "Decisiones sugeridas" not in page
    assert "Áreas UAF potencialmente responsables" not in page
    assert "Cobertura de prensa vinculada" in page


def test_terminal_project_is_excluded_from_active_portfolio():
    project = CandidateProject(
        bulletin="12000-25",
        title="Modifica la ley 19.913",
        state="Tramitación terminada (Ley N° 21.999 - Diario Oficial)",
        latest_movement_date="2026-07-01",
        metadata={"official_status_verified": True, "movement_verified": True},
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
        metadata={
            "entry_date_verified": True,
            "movement_verified": True,
            "official_status_verified": True,
        },
    )
    result = classify(project, CONFIG)
    assert result["is_current"] is False
    assert result["lifecycle_code"] in {"historical", "stale"}


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
        metadata={
            "entry_date_verified": True,
            "movement_verified": True,
            "official_status_verified": True,
        },
    )
    result = classify(project, CONFIG)
    assert result["is_current"] is True
    assert "new" in result["lifecycle_flags"]
    assert "active" in result["lifecycle_flags"]


def test_senado_current_stage_overrides_historical_stage(monkeypatch):
    source = SenadoSource(HttpClient())
    html_data = (FIXTURES / "senado_16808_detail.html").read_bytes()
    monkeypatch.setattr(source.client, "get", lambda url, params=None: FetchResult(url=url, status_code=200, content=html_data, content_type="text/html; charset=utf-8"))
    project = source.detail("16808-25")
    assert project.stage == "Segundo trámite constitucional (Senado)"
    assert project.commission == "Primer informe de comisión de Seguridad Pública"
    assert project.latest_movement_date == "2026-06-03"
    assert "Cristián Araya" in project.metadata["promoters"]


def test_authoritative_merge_keeps_senate_current_stage():
    camara = CandidateProject(
        bulletin="16808-25", stage="Primer trámite constitucional", commission="Primer informe",
        metadata={"field_ranks": {"stage": 60, "commission": 60}},
    )
    senado = CandidateProject(
        bulletin="16808-25", stage="Segundo trámite constitucional (Senado)",
        commission="Primer informe de comisión de Seguridad Pública",
        metadata={"field_ranks": {"stage": 100, "commission": 100}},
    )
    camara.merge(senado)
    assert camara.stage.startswith("Segundo trámite")
    assert "Seguridad Pública" in camara.commission


def test_strategic_reading_does_not_repeat_latest_movement():
    project = CandidateProject(
        bulletin="16808-25",
        title="Modifica la ley N° 19.913 para prevenir el lavado de activos asociado al comercio ilegal",
        latest_movement="Oficio a Cámara revisora",
        metadata={"promoters": ["Cristián Araya", "Chiara Barchiesi"]},
    )
    result = classify(project, CONFIG)
    assert "Oficio a Cámara revisora" not in result["analysis_summary"]
    assert "Cristián Araya" in result["analysis_summary"]
    assert "comercio ilegal" in result["matter_summary"].lower()
    assert result["affected_legal_areas"]


def test_press_parser_filters_and_keeps_project_mention():
    from monitor_uaf.press import ProjectPressSource
    source = ProjectPressSource(HttpClient(), CONFIG)
    content = (FIXTURES / "google_news_16808.xml").read_bytes()
    rows = source._parse(content, '"16808-25"')
    assert len(rows) == 1
    assert rows[0]["outlet"] == "Diario Constitucional"


def test_official_document_scanner_detects_uaf_in_later_indications(monkeypatch):
    from monitor_uaf.documents import OfficialProjectDocumentSource

    source = OfficialProjectDocumentSource(HttpClient(), CONFIG)
    page = (FIXTURES / "camara_documents_18216.html").read_bytes()
    indication = (FIXTURES / "indications_18216.html").read_bytes()

    def fake_get(url, params=None):
        if "verDoc.aspx" in url:
            return FetchResult(url=url, status_code=200, content=indication, content_type="text/html; charset=utf-8")
        return FetchResult(url=url, status_code=200, content=page, content_type="text/html; charset=utf-8")

    monkeypatch.setattr(source.client, "get", fake_get)
    project = CandidateProject(
        bulletin="18216-05",
        title="Para la reconstrucción nacional y el desarrollo económico y social",
        entry_date="2026-04-22",
    )
    enriched = source.scan(project)
    result = classify(project.merge(enriched), CONFIG)
    assert result["relevance_level"] == 1
    assert enriched.metadata["official_documents_matched"]
    assert "Unidad de Análisis Financiero" in enriched.evidence_text
    assert "impacto UAF no surge del título" in result["matter_summary"]


def test_seed_contains_bulletin_18216_05():
    assert "18216-05" in CONFIG["seed_bulletins"]


def test_dashboard_orders_by_latest_movement_and_has_watch_cards(tmp_path):
    from monitor_uaf.render import render_dashboard

    direct = classify(CandidateProject(
        bulletin="18216-05",
        title="Proyecto económico con obligación de reportar a la Unidad de Análisis Financiero",
        entry_date="2026-04-22",
        stage="Discusión de informe de Comisión Mixta (Senado)",
        latest_movement_date="2026-07-04",
        evidence_text="Los bancos deberán reportar operaciones sospechosas a la UAF.",
        metadata={"movement_verified": True, "official_status_verified": True},
    ), CONFIG)
    secondary = classify(CandidateProject(
        bulletin="19010-07",
        title="Crea un registro de beneficiarios finales",
        entry_date="2026-07-01",
        stage="Primer trámite constitucional",
        latest_movement_date="2026-08-01",
        metadata={"movement_verified": True, "official_status_verified": True},
    ), CONFIG)
    output = tmp_path / "index.html"
    render_dashboard([secondary, direct], [], {"sources": {}}, output)
    page = output.read_text(encoding="utf-8")
    assert "Materias con mayor actividad y avance" in page
    assert "stageWeight" in page
    # La tabla principal ordena por última modificación: el proyecto de agosto va primero.
    table_start = page.index('id="rows"')
    assert page.index("19010-07", table_start) < page.index("18216-05", table_start)
    assert "Cambios a la Ley N.º 19.913 que hay que tener en vista" in page
    assert "Áreas UAF potencialmente responsables" not in page


def test_dashboard_excludes_historical_origin_bulletin(tmp_path):
    from monitor_uaf.render import render_dashboard

    historical = {
        "bulletin": "2975-07",
        "title": "Crea la Unidad de Análisis Financiero",
        "is_current": True,
        "lifecycle_code": "active",
        "relevance_level": 1,
        "latest_movement_date": "2026-08-01",
    }
    current = {
        "bulletin": "16808-25",
        "title": "Proyecto vigente",
        "is_current": True,
        "lifecycle_code": "active",
        "relevance_level": 1,
        "latest_movement_date": "2026-07-15",
    }
    output = tmp_path / "index.html"
    render_dashboard([historical, current], [], {"sources": {}}, output)
    page = output.read_text(encoding="utf-8")
    assert "2975-07" not in page
    assert "16808-25" in page


def test_document_scanner_reads_links_from_senate_documents_column(monkeypatch):
    from monitor_uaf.documents import OfficialProjectDocumentSource

    source = OfficialProjectDocumentSource(HttpClient(), CONFIG)
    indication = (FIXTURES / "indications_18216.html").read_bytes()
    empty_page = b"<html><body><h1>Ficha sin enlaces adicionales</h1></body></html>"

    def fake_get(url, params=None):
        if "senado.cl/documentos/informe.pdf" in url:
            return FetchResult(
                url=url,
                status_code=200,
                content=indication,
                content_type="text/html; charset=utf-8",
            )
        return FetchResult(
            url=url,
            status_code=200,
            content=empty_page,
            content_type="text/html; charset=utf-8",
        )

    monkeypatch.setattr(source.client, "get", fake_get)
    project = CandidateProject(
        bulletin="18216-05",
        title="Para la reconstrucción nacional y el desarrollo económico y social",
        metadata={
            "senado_proceedings": [
                {
                    "date": "2026-07-22",
                    "substage": "Cuenta oficio aprobación de informe de Comisión Mixta",
                    "stage": "Discusión de informe de Comisión Mixta (Senado)",
                    "documents": [
                        {
                            "label": "Informe de Comisión Mixta",
                            "url": "https://senado.cl/documentos/informe.pdf",
                        }
                    ],
                }
            ]
        },
    )
    enriched = source.scan(project, include_all=True)
    reviews = enriched.metadata["official_document_reviews"]
    assert len(reviews) == 1
    assert reviews[0]["kind"] == "Informe de Comisión Mixta"
    assert "Unidad de Análisis Financiero" in reviews[0]["summary"]
    assert reviews[0]["date"] == "2026-07-22"


def test_prepare_dashboard_projects_sorts_by_latest_modification():
    from monitor_uaf.render import prepare_dashboard_projects

    rows = [
        {
            "bulletin": "15975-25",
            "is_current": True,
            "lifecycle_code": "active",
            "relevance_level": 1,
            "latest_movement_date": "2026-06-09",
        },
        {
            "bulletin": "16808-25",
            "is_current": True,
            "lifecycle_code": "active",
            "relevance_level": 1,
            "latest_movement_date": "2026-07-15",
        },
    ]
    ordered = prepare_dashboard_projects(rows)
    assert [row["bulletin"] for row in ordered] == ["16808-25", "15975-25"]
