from monitor_uaf.analysis import sanitize_project_record

def test_sanitize_project_record_exists_and_compacts_raw_content():
    record = {
        "bulletin": "16764-03",
        "title": "Proyecto",
        "metadata": {
            "raw_html": "x" * 50000,
            "senado_proceedings": [{"date": "17/04/2024", "substage": "Ingreso"}],
        },
    }
    result = sanitize_project_record(record, {"compat": True})
    assert result["bulletin"] == "16764-03"
    assert "raw_html" not in result["metadata"]
    assert result["metadata"]["senado_proceedings"][0]["date"] == "17/04/2024"
