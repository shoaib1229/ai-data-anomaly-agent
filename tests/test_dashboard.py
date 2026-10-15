from src.dashboard import filter_anomalies


def test_filter_anomalies_by_metric_and_severity_case_insensitively() -> None:
    findings = [
        {"metric": "revenue", "severity": "critical"},
        {"metric": "orders", "severity": "medium"},
        {"metric": "revenue", "severity": "high"},
    ]

    selected = filter_anomalies(
        findings,
        metrics={"REVENUE"},
        severities={"critical", "HIGH"},
    )

    assert selected == [findings[0], findings[2]]


def test_filter_anomalies_with_empty_selection_returns_no_findings() -> None:
    findings = [{"metric": "revenue", "severity": "high"}]

    assert filter_anomalies(findings, metrics=set()) == []


def test_filter_anomalies_without_filters_returns_all_findings() -> None:
    findings = [{"metric": "revenue", "severity": "high"}]

    assert filter_anomalies(findings) == findings
