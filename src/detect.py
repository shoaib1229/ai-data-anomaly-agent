"""Detect rule-based anomalies against prior valid observations."""

from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd

from src.explain import build_explanation
from src.metrics import METRIC_COLUMNS, calculate_metrics
from src.validate import REQUIRED_COLUMNS, validate_data


DEFAULT_THRESHOLDS_PCT = {
    "revenue": 30.0,
    "orders": 30.0,
    "conversion_rate": 25.0,
    "traffic": 30.0,
    "cost": 35.0,
    "refunds": 50.0,
}


def _python_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.date().isoformat() if isinstance(value, pd.Timestamp) else value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _severity(change_pct: float, threshold_pct: float) -> str:
    ratio = abs(change_pct) / threshold_pct
    if ratio >= 2.0:
        return "critical"
    if ratio >= 1.5:
        return "high"
    return "medium"


def detect_anomalies(
    data: pd.DataFrame,
    *,
    thresholds_pct: dict[str, float] | None = None,
    baseline_window: int = 7,
    min_history: int = 7,
    rolling_window: int = 7,
) -> dict:
    """Build a JSON-friendly anomaly report from validated daily data.

    For each date and metric, the comparison baseline contains only earlier,
    valid observations. Thresholds are absolute relative percentage changes.
    A zero baseline and insufficient history produce a skipped evaluation,
    never an anomaly.
    """
    thresholds = DEFAULT_THRESHOLDS_PCT.copy()
    if thresholds_pct is not None:
        unknown = sorted(set(thresholds_pct) - set(METRIC_COLUMNS))
        if unknown:
            raise ValueError(f"Unknown metric threshold(s): {', '.join(unknown)}.")
        thresholds.update(thresholds_pct)
    for metric, threshold in thresholds.items():
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError(f"Threshold for {metric} must be a positive number.")
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError(f"Threshold for {metric} must be a positive finite number.")

    validation = validate_data(data)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing_columns:
        return {
            "status": "invalid_input",
            "configuration": {
                "baseline_window": baseline_window,
                "min_history": min_history,
                "rolling_window": rolling_window,
                "thresholds_pct": thresholds,
            },
            "summary": {"anomaly_count": 0, "evaluated_rows": 0, "excluded_rows": len(data), "skipped_evaluations": 0},
            "anomalies": [],
            "excluded_rows": [],
            "skipped_evaluations": [],
            "input_validation": validation,
        }

    calculated = calculate_metrics(
        data,
        rolling_window=rolling_window,
        baseline_window=baseline_window,
        min_history=min_history,
    )
    issue_by_row: dict[int, list[dict]] = {}
    for issue in validation["errors"]:
        for row_number in issue["row_numbers"]:
            issue_by_row.setdefault(row_number, []).append(issue)

    excluded_rows = []
    if not validation["is_valid"]:
        missing_columns_issue = next(
            (issue for issue in validation["errors"] if issue["code"] == "missing_columns"), None
        )
    else:
        missing_columns_issue = None
    if missing_columns_issue:
        for row_number in range(2, len(data) + 2):
            excluded_rows.append({
                "row_number": row_number,
                "date": _python_value(data.iloc[row_number - 2]["date"]) if "date" in data else None,
                "issue_codes": ["missing_columns"],
                "columns": missing_columns_issue["columns"],
            })
    else:
        for row_number, issues in issue_by_row.items():
            excluded_rows.append({
                "row_number": row_number,
                "date": _python_value(data.iloc[row_number - 2]["date"]),
                "issue_codes": sorted({issue["code"] for issue in issues}),
                "columns": sorted({column for issue in issues for column in issue["columns"]}),
            })

    anomalies: list[dict] = []
    skipped: list[dict] = []
    evaluated_rows = 0
    valid_rows = calculated.loc[calculated["row_valid"]].sort_values("normalized_date", kind="stable")
    for _, row in valid_rows.iterrows():
        row_evaluated = False
        for metric in METRIC_COLUMNS:
            baseline_count = int(row[f"{metric}_baseline_count"])
            context = {
                "row_number": int(row["row_number"]),
                "date": _python_value(row["normalized_date"]),
                "metric": metric,
            }
            if baseline_count < min_history:
                skipped.append({**context, "reason": "insufficient_history", "baseline_count": baseline_count})
                continue

            observed = float(row[metric])
            baseline = float(row[f"{metric}_historical_baseline"])
            if baseline == 0:
                skipped.append({**context, "reason": "zero_baseline", "baseline_count": baseline_count})
                continue

            percentage_change = ((observed - baseline) / baseline) * 100
            row_evaluated = True
            threshold = float(thresholds[metric])
            if abs(percentage_change) < threshold:
                continue

            direction = "increase" if percentage_change > 0 else "decrease"
            severity = _severity(percentage_change, threshold)
            anomaly = {
                **context,
                "metric_label": metric.replace("_", " ").title(),
                "observed_value": observed,
                "baseline_value": baseline,
                "change_value": observed - baseline,
                "percentage_change": percentage_change,
                "direction": direction,
                "severity": severity,
                "threshold_pct": threshold,
                "baseline_count": baseline_count,
                "explanation": build_explanation(
                    metric=metric,
                    observed_value=observed,
                    baseline_value=baseline,
                    percentage_change=percentage_change,
                    direction=direction,
                    severity=severity,
                    baseline_count=baseline_count,
                    threshold_pct=threshold,
                ),
            }
            anomalies.append(anomaly)
        if row_evaluated:
            evaluated_rows += 1

    if anomalies or evaluated_rows:
        status = "complete"
    elif not valid_rows.empty:
        status = "insufficient_history"
    else:
        status = "invalid_input"

    anomalies.sort(key=lambda item: (item["date"], item["metric"]))
    return {
        "status": status,
        "configuration": {
            "baseline_window": baseline_window,
            "min_history": min_history,
            "rolling_window": rolling_window,
            "thresholds_pct": thresholds,
        },
        "summary": {
            "anomaly_count": len(anomalies),
            "evaluated_rows": evaluated_rows,
            "excluded_rows": len(excluded_rows),
            "skipped_evaluations": len(skipped),
        },
        "anomalies": anomalies,
        "excluded_rows": excluded_rows,
        "skipped_evaluations": skipped,
        "input_validation": validation,
    }
