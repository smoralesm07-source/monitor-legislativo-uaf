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


def test_classification_does_not_persist_raw_evidence():
    evidence = "ley 19.913 " * 100_000
    project = CandidateProject(
        bulletin="19998-25",
        title="Modifica la ley 19.913",
        evidence_text=evidence,
        metadata={"camara_movements": [evidence], "bcn_associated": True},
    )
    result = classify(project, CONFIG)
    assert "evidence_text" not in result
    assert "camara_movements" not in result["metadata"]
    assert result["metadata"]["bcn_associated"] is True


def test_candidate_merge_limits_evidence_growth():
    first = CandidateProject(bulletin="19997-25", evidence_text="A" * 100_000)
    second = CandidateProject(bulletin="19997-25", evidence_text="B" * 100_000)
    first.merge(second)
    assert len(first.evidence_text) <= 120_000
    before = first.evidence_text
    first.merge(second)
    assert first.evidence_text == before


def test_dashboard_does_not_embed_large_raw_evidence(tmp_path):
    from monitor_uaf.render import render_dashboard

    project = classify(
        CandidateProject(
            bulletin="19996-25",
            title="Modifica la ley N° 19.913",
            evidence_text="Texto legislativo extenso " * 200_000,
            latest_movement="Ingreso de proyecto",
            latest_movement_date="2026-08-03",
        ),
        CONFIG,
    )
    output = tmp_path / "index.html"
    render_dashboard([project], [], {"sources": {}}, output)
    assert output.stat().st_size < 500_000
    assert "Texto legislativo extenso" not in output.read_text(encoding="utf-8")


def test_acronym_ros_does_not_match_profesores_or_otros():
    project = CandidateProject(
        bulletin="19990-04",
        title="Mejora la formación de profesores y asigna otros recursos a educación",
        evidence_text="Establece sanciones administrativas y una plataforma de datos para establecimientos educacionales.",
    )
    result = classify(project, CONFIG)
    assert result["relevance_level"] == 0
    assert "Reportes y operaciones" not in result["impacts"]


def test_education_project_with_generic_financial_words_is_excluded():
    project = CandidateProject(
        bulletin="19991-04",
        title="Fortalece el financiamiento de la educación pública",
        evidence_text="Regula presupuesto, bancos de datos, sanciones y fiscalización de universidades.",
    )
    result = classify(project, CONFIG)
    assert result["relevance_level"] == 0
    assert "educación" in " ".join(CONFIG["noise_domain_terms"])


def test_secondary_laft_requires_precise_anchor_and_builds_useful_summary():
    project = CandidateProject(
        bulletin="19992-07",
        title="Crea un registro nacional de beneficiarios finales",
        evidence_text="El registro permitirá identificar al titular real y prevenir el lavado de activos mediante intercambio de información financiera.",
    )
    result = classify(project, CONFIG)
    assert result["relevance_level"] == 2
    assert result["laft_confidence"] >= CONFIG["minimum_secondary_confidence"]
    assert "beneficiario final" in result["linkage_summary"]
    assert result["laft_topics"]


def test_known_initiative_has_short_reference_name():
    project = CandidateProject(
        bulletin="15975-25",
        title="Crea el Subsistema de Inteligencia Económica y establece otras medidas para la prevención y alerta de actividades que digan relación con el crimen organizado",
        evidence_text="Modifica la ley 19.913 y fortalece a la Unidad de Análisis Financiero.",
    )
    result = classify(project, CONFIG)
    assert result["initiative_name"] == "Sistema de Inteligencia Económica"
    assert "Modifica o afecta expresamente" in result["linkage_summary"]


def test_candidate_merge_keeps_description_and_newest_date_together():
    first = CandidateProject(
        bulletin="19993-25",
        latest_movement="10/10/2025 | Ingreso de proyecto",
        latest_movement_date="2025-10-10",
        metadata={"movement_rank": 3, "movement_source": "Fuente A"},
    )
    second = CandidateProject(
        bulletin="19993-25",
        latest_movement="18/07/2026 | Informe de Comisión",
        latest_movement_date="2026-07-18",
        metadata={"movement_rank": 5, "movement_source": "Cámara XML oficial"},
    )
    first.merge(second)
    assert first.latest_movement_date == "2026-07-18"
    assert "Informe de Comisión" in first.latest_movement
    assert first.metadata["movement_source"] == "Cámara XML oficial"


def test_senado_detail_uses_project_timeline_not_unrelated_recent_list(monkeypatch):
    from types import SimpleNamespace
    from monitor_uaf.sources import SenadoSource

    source = SenadoSource(HttpClient())
    html = (FIXTURES / "senado_detail.html").read_text(encoding="utf-8")
    monkeypatch.setattr(source.client, "get", lambda url: SimpleNamespace(text=html))
    project = source.detail("19992-07")
    assert project.latest_movement_date == "2026-07-18"
    assert "Informe de Comisión" in project.latest_movement
    assert "25/10/2025" not in project.latest_movement
    assert project.metadata["movement_source"] == "Senado ficha oficial"


def test_initiative_groups_refunded_bulletins():
    from monitor_uaf.analysis import annotate_initiative_groups

    p1 = classify(CandidateProject(bulletin="16764-03", title="Limita transacciones en efectivo", evidence_text="Modifica la ley 19.913"), CONFIG)
    p2 = classify(CandidateProject(bulletin="15462-03", title="Regula pagos en efectivo", evidence_text="Modifica la ley 19.913"), CONFIG)
    grouped = annotate_initiative_groups({"16764-03": p1, "15462-03": p2}, CONFIG)
    assert grouped["16764-03"]["initiative_group_id"] == grouped["15462-03"]["initiative_group_id"]
    assert grouped["16764-03"]["group_size"] == 2


def test_parse_senate_textual_date_with_de_and_comma():
    from monitor_uaf.utils import parse_legislative_date
    assert parse_legislative_date("Miércoles 15 de Enero, 2026") .isoformat() == "2026-01-15"


def test_alert_uses_official_movement_date_not_detection_date():
    old = classify(CandidateProject(
        bulletin="19994-25", title="Modifica la ley 19.913", state="Primer trámite",
        latest_movement="01/05/2026 | Ingreso", latest_movement_date="2026-05-01"
    ), CONFIG)
    new = classify(CandidateProject(
        bulletin="19994-25", title="Modifica la ley 19.913", state="Segundo trámite",
        latest_movement="22/07/2026 | Pasa a segundo trámite", latest_movement_date="2026-07-22",
        metadata={"movement_source": "Cámara XML oficial"}
    ), CONFIG)
    alerts = compare_projects({"projects": {"19994-25": old}}, {"19994-25": new}, CONFIG)
    assert alerts[0]["official_movement_date"] == "2026-07-22"
    assert alerts[0]["movement_source"] == "Cámara XML oficial"


def test_analysis_only_migration_does_not_generate_alert():
    old = classify(CandidateProject(
        bulletin="19995-25", title="Modifica la ley 19.913", state="Primer trámite",
        latest_movement="01/06/2026 | Ingreso", latest_movement_date="2026-06-01"
    ), CONFIG)
    new = dict(old)
    new["initiative_name"] = "Nuevo nombre analítico más claro"
    new["laft_topics"] = ["secreto bancario"]
    new["fingerprint"] = "huella-analitica-distinta"
    assert compare_projects({"projects": {"19995-25": old}}, {"19995-25": new}, CONFIG) == []
