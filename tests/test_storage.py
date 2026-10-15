import hashlib
import sqlite3

import pytest

from src.storage import (
    StorageError,
    get_analysis_history,
    get_anomaly_findings,
    initialize_database,
    save_analysis,
)


def usable_report() -> dict:
    return {
        "status": "complete",
        "configuration": {"min_history": 7, "thresholds_pct": {"revenue": 30.0}},
        "summary": {"anomaly_count": 1, "evaluated_rows": 2, "excluded_rows": 0},
        "input_validation": {"is_valid": True, "row_count": 9, "errors": [], "warnings": []},
        "anomalies": [{
            "date": "2026-01-09",
            "metric": "revenue",
            "observed_value": 150.0,
            "baseline_value": 100.0,
            "change_value": 50.0,
            "percentage_change": 50.0,
            "direction": "increase",
            "severity": "high",
            "threshold_pct": 30.0,
            "baseline_count": 7,
            "explanation": "Revenue was elevated against its historical baseline.",
        }],
    }


def source_metadata(content: bytes = b"synthetic sample") -> dict:
    return {
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "file_type": "csv",
        "size_bytes": len(content),
        "row_count": 9,
    }


def test_initializes_expected_tables(tmp_path) -> None:
    path = tmp_path / "nested" / "agent.sqlite3"

    initialize_database(path)

    with sqlite3.connect(path) as connection:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
    assert {"analysis_runs", "anomaly_findings", "source_files"}.issubset(names)


def test_saves_and_retrieves_analysis_and_findings(tmp_path) -> None:
    path = tmp_path / "agent.sqlite3"
    initialize_database(path)

    saved = save_analysis(path, source_metadata=source_metadata(), analysis_report=usable_report())
    history = get_analysis_history(path)
    findings = get_anomaly_findings(path, saved["run_id"])

    assert saved["created"] is True
    assert len(history) == 1
    assert history[0]["status"] == "complete"
    assert history[0]["file_type"] == "csv"
    assert findings[0]["metric"] == "revenue"
    assert findings[0]["observed_value"] == 150.0
    assert findings[0]["explanation"].startswith("Revenue")


def test_repeated_analysis_is_idempotent(tmp_path) -> None:
    path = tmp_path / "agent.sqlite3"
    report = usable_report()
    source = source_metadata()

    first = save_analysis(path, source_metadata=source, analysis_report=report)
    second = save_analysis(path, source_metadata=source, analysis_report=report)

    assert first == {"run_id": second["run_id"], "created": True}
    assert second["created"] is False
    assert len(get_analysis_history(path)) == 1
    assert len(get_anomaly_findings(path, first["run_id"])) == 1


def test_does_not_save_invalid_analysis(tmp_path) -> None:
    path = tmp_path / "agent.sqlite3"
    report = usable_report()
    report["status"] = "invalid_input"

    with pytest.raises(ValueError, match="Only completed analyses"):
        save_analysis(path, source_metadata=source_metadata(), analysis_report=report)


def test_rejects_analysis_with_no_valid_rows(tmp_path) -> None:
    report = usable_report()
    report["input_validation"] = {
        "row_count": 1,
        "errors": [{"code": "invalid_date", "row_numbers": [2]}],
        "warnings": [],
    }

    with pytest.raises(ValueError, match="no valid data rows"):
        save_analysis(tmp_path / "agent.sqlite3", source_metadata=source_metadata(), analysis_report=report)


def test_saves_usable_rows_and_validation_details_without_source_values(tmp_path) -> None:
    path = tmp_path / "agent.sqlite3"
    report = usable_report()
    report["input_validation"] = {
        "is_valid": False,
        "row_count": 9,
        "errors": [{
            "severity": "error",
            "code": "missing_values",
            "message": "'revenue' contains missing values.",
            "row_numbers": [2],
            "columns": ["revenue"],
        }],
        "warnings": [],
    }

    result = save_analysis(path, source_metadata=source_metadata(), analysis_report=report)
    history = get_analysis_history(path)

    assert result["created"] is True
    assert history[0]["excluded_rows"] == 1
    assert "row_numbers" in history[0]["validation_json"]
    assert "missing_values" in history[0]["validation_json"]


def test_rejects_malformed_finding_before_writing(tmp_path) -> None:
    report = usable_report()
    report["anomalies"] = [{"metric": "revenue"}]

    with pytest.raises(ValueError, match="missing required fields"):
        save_analysis(tmp_path / "agent.sqlite3", source_metadata=source_metadata(), analysis_report=report)


def test_database_errors_are_wrapped(tmp_path) -> None:
    not_a_directory = tmp_path / "a_file"
    not_a_directory.write_text("not a directory", encoding="utf-8")

    with pytest.raises(StorageError, match="Could not initialize"):
        initialize_database(not_a_directory / "agent.sqlite3")


def test_history_limit_is_validated_before_query(tmp_path) -> None:
    with pytest.raises(ValueError, match="limit must be an integer"):
        get_analysis_history(tmp_path / "agent.sqlite3", limit="1; DROP TABLE analysis_runs")
