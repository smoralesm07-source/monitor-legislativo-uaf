from monitor_uaf.documents import OfficialProjectDocumentSource
from monitor_uaf.analysis import (
    annotate_initiative_groups,
    classify,
    compare_projects,
    sanitize_project_record,
)
from monitor_uaf.render import (
    prepare_dashboard_alerts,
    prepare_dashboard_projects,
    render_dashboard,
)


def test_import_contract_for_pipeline_and_maintenance():
    assert callable(annotate_initiative_groups)
    assert callable(classify)
    assert callable(compare_projects)
    assert callable(sanitize_project_record)
    assert callable(prepare_dashboard_alerts)
    assert callable(prepare_dashboard_projects)
    assert callable(render_dashboard)
    assert callable(OfficialProjectDocumentSource)


def test_annotate_initiative_groups_refundidos_and_matrix():
    projects = [
        {
            "bulletin": "16764-03",
            "entry_date": "2024-04-17",
            "refundido": "16764-03 / 16783-03 / 15462-03 *matriz*",
            "metadata": {},
        },
        {
            "bulletin": "16783-03",
            "entry_date": "2024-04-18",
            "related_bulletins": ["16764-03", "15462-03"],
            "metadata": {},
        },
        {
            "bulletin": "15462-03",
            "entry_date": "2022-10-01",
            "metadata": {"is_matrix": True},
        },
    ]

    result = annotate_initiative_groups(projects)

    assert result is projects
    by_id = {item["bulletin"]: item for item in projects}
    assert by_id["15462-03"]["initiative_group_role"] == "Matriz"
    assert by_id["16764-03"]["initiative_group_primary"] == "15462-03"
    assert by_id["16783-03"]["initiative_group_size"] == 3
    assert set(by_id["16764-03"]["initiative_group_bulletins"]) == {
        "16764-03",
        "16783-03",
        "15462-03",
    }


def test_annotate_initiative_groups_accepts_state_mapping():
    state = {
        "16764-03": {
            "bulletin": "16764-03",
            "related_bulletins": ["16783-03"],
        },
        "16783-03": {
            "bulletin": "16783-03",
            "related_bulletins": ["16764-03"],
        },
    }

    result = annotate_initiative_groups(state, {"compat": True})

    assert result is state
    assert state["16764-03"]["is_grouped_initiative"] is True
    assert state["16783-03"]["initiative_group_size"] == 2
