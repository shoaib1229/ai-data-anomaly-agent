import hashlib

from src.alerts import create_email_preview, finding_identity
from src.storage import claim_unpreviewed_findings, get_previewed_finding_keys, save_analysis


def finding(**overrides) -> dict:
    item = {
        "date": "2026-09-20",
        "metric": "revenue",
        "metric_label": "Revenue",
        "observed_value": 150.0,
        "baseline_value": 100.0,
        "percentage_change": 50.0,
        "direction": "increase",
        "severity": "critical",
        "explanation": "Revenue is notably above its recent baseline.",
    }
    item.update(overrides)
    return item


def saved_run(db_path, content: bytes = b"alert sample") -> int:
    report = {
        "status": "complete",
        "configuration": {"baseline_window": 7},
        "summary": {"anomaly_count": 1, "evaluated_rows": 1},
        "input_validation": {"row_count": 8, "errors": [], "warnings": []},
        "anomalies": [],
    }
    saved = save_analysis(
        db_path,
        source_metadata={
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "file_type": "csv",
            "size_bytes": 12,
            "row_count": 8,
        },
        analysis_report=report,
    )
    return saved["run_id"]


def test_formats_professional_subject_and_plain_text_details() -> None:
    preview = create_email_preview([finding()], analysis_run_id=12)

    assert preview["subject"] == "AI Data Anomaly Alert — 1 finding (1 critical)"
    assert "Subject:" not in preview["body"]
    assert "Analysis run: 12" in preview["body"]
    assert "Revenue — 2026-09-20" in preview["body"]
    assert "Observed value: 150.00" in preview["body"]
    assert "Historical baseline: 100.00" in preview["body"]
    assert "Percentage change: +50.0%" in preview["body"]
    assert "Severity: Critical" in preview["body"]
    assert "does not establish statistical certainty" in preview["body"]


def test_empty_findings_returns_clear_no_alert_message() -> None:
    preview = create_email_preview([], analysis_run_id=8)

    assert preview["included_count"] == 0
    assert "No new findings" in preview["subject"]
    assert "No anomaly findings were detected" in preview["body"]


def test_multiple_findings_include_overall_priority_summary() -> None:
    lower = finding(metric="traffic", metric_label="Traffic", severity="medium", percentage_change=-35.0)
    higher = finding(metric="refunds", metric_label="Refunds", severity="critical", percentage_change=60.0)

    preview = create_email_preview([lower, higher], analysis_run_id=3)

    assert preview["included_count"] == 2
    assert "2 new findings" in preview["summary"]
    assert "Most important: Refunds" in preview["summary"]
    assert "Traffic — 2026-09-20" in preview["body"]
    assert "Refunds — 2026-09-20" in preview["body"]


def test_missing_optional_fields_and_zero_baseline_are_safe() -> None:
    sparse = {"metric": "conversion_rate", "observed_value": 0.08, "baseline_value": 0.0}

    preview = create_email_preview([sparse], analysis_run_id=1)

    assert "Conversion Rate" in preview["body"]
    assert "Observed value: 8.00%" in preview["body"]
    assert "Historical baseline: 0.00%" in preview["body"]
    assert "Percentage change:" not in preview["body"]
    assert "Severity: Unspecified" in preview["body"]
    assert "does not establish statistical certainty" in preview["body"]


def test_duplicate_findings_are_claimed_once_per_run(tmp_path) -> None:
    db_path = tmp_path / "alerts.sqlite3"
    run_id = saved_run(db_path)
    duplicate = finding()
    repeated_input = [duplicate, duplicate.copy()]

    first_preview_findings = claim_unpreviewed_findings(db_path, run_id, repeated_input)
    first_preview = create_email_preview(first_preview_findings, analysis_run_id=run_id)
    second_preview_findings = claim_unpreviewed_findings(db_path, run_id, repeated_input)
    second_preview = create_email_preview(
        repeated_input,
        analysis_run_id=run_id,
        previously_included=get_previewed_finding_keys(db_path, run_id),
    )

    assert first_preview["included_count"] == 1
    assert len(first_preview["finding_keys"]) == 1
    assert second_preview_findings == []
    assert second_preview["included_count"] == 0
    assert second_preview["suppressed_count"] == 2
    assert finding_identity(run_id, duplicate) in get_previewed_finding_keys(db_path, run_id)


def test_same_finding_is_eligible_for_a_different_analysis_run(tmp_path) -> None:
    db_path = tmp_path / "alerts.sqlite3"
    first_run = saved_run(db_path, b"first analysis")
    second_run = saved_run(db_path, b"second analysis")
    sample_finding = finding()

    assert claim_unpreviewed_findings(db_path, first_run, [sample_finding]) == [sample_finding]
    assert claim_unpreviewed_findings(db_path, second_run, [sample_finding]) == [sample_finding]
