"""Small, testable presentation helpers for the Streamlit dashboard."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def filter_anomalies(
    findings: Iterable[Mapping[str, Any]],
    *,
    metrics: set[str] | None = None,
    severities: set[str] | None = None,
) -> list[Mapping[str, Any]]:
    """Select findings matching optional metric and severity filters."""
    selected_metrics = {value.casefold() for value in metrics} if metrics is not None else None
    selected_severities = {value.casefold() for value in severities} if severities is not None else None
    return [
        finding
        for finding in findings
        if (selected_metrics is None or str(finding.get("metric", "")).casefold() in selected_metrics)
        and (
            selected_severities is None
            or str(finding.get("severity", "")).casefold() in selected_severities
        )
    ]
