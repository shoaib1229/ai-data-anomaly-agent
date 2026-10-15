from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_upload_renders_history_and_anomaly_views(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_ANOMALY_AGENT_DB_PATH", str(tmp_path / "dashboard.sqlite3"))
    sample = (PROJECT_ROOT / "data" / "sample" / "daily_business_metrics.csv").read_bytes()

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run(timeout=30)
    app.file_uploader[0].set_value(("daily_business_metrics.csv", sample, "text/csv")).run(timeout=30)

    assert not app.exception
    assert any("AI Data Anomaly Agent" in item.value for item in app.title)
    assert any("Revenue trend" in item.value for item in app.subheader)
    assert any("Analysis history" in item.value for item in app.subheader)
    assert not any(str(tmp_path) in item.value for item in app.caption)


def test_dashboard_malformed_upload_shows_safe_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AI_ANOMALY_AGENT_DB_PATH", str(tmp_path / "malformed.sqlite3"))

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py")).run(timeout=30)
    app.file_uploader[0].set_value(
        ("bad.xlsx", b"not a workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ).run(timeout=30)

    assert not app.exception
    errors = [item.value for item in app.error]
    assert any("Could not read this file" in message for message in errors)
    assert not any(str(tmp_path) in message for message in errors)
