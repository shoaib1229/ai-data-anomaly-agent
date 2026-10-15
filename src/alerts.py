"""Create plain-text, unsent email previews from deterministic findings."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from src.explain import format_value


SEVERITY_ORDER = {"critical": 3, "high": 2, "medium": 1}
CAUTION = (
    "This is a rule-based signal for review. It does not establish statistical "
    "certainty or identify a business cause."
)


def finding_identity(analysis_run_id: int | str, finding: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return the stable, run-scoped identity used for duplicate protection."""
    return (
        str(analysis_run_id),
        str(finding.get("date") or "unknown-date").strip(),
        str(finding.get("metric") or "unknown-metric").strip().casefold(),
    )


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _display_value(metric: str, value: Any) -> str:
    number = _number(value)
    if number is None:
        return "Not available"
    return format_value(metric, number)


def _metric_label(finding: Mapping[str, Any]) -> str:
    label = finding.get("metric_label") or finding.get("metric") or "Business metric"
    return str(label).replace("_", " ").strip().title()


def _percentage_change(finding: Mapping[str, Any]) -> float | None:
    baseline = _number(finding.get("baseline_value"))
    observed = _number(finding.get("observed_value"))
    if baseline is None or baseline == 0:
        return None
    supplied = _number(finding.get("percentage_change"))
    if supplied is not None:
        return supplied
    if observed is None:
        return None
    return ((observed - baseline) / baseline) * 100


def create_email_preview(
    findings: Iterable[Mapping[str, Any]],
    *,
    analysis_run_id: int | str,
    previously_included: Iterable[tuple[str, str, str]] = (),
) -> dict[str, Any]:
    """Format new, unique findings as a subject and plain-text message.

    Duplicate identity is scoped to the analysis run, date, and metric. The
    caller can pass keys previously recorded by local storage to avoid
    repeating findings in a later preview for that same run.
    """
    prior_keys = {tuple(str(part) for part in key) for key in previously_included}
    seen: set[tuple[str, str, str]] = set()
    selected: list[Mapping[str, Any]] = []
    keys: list[tuple[str, str, str]] = []
    suppressed = 0
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        key = finding_identity(analysis_run_id, finding)
        if key in seen or key in prior_keys:
            suppressed += 1
            continue
        seen.add(key)
        selected.append(finding)
        keys.append(key)

    if not selected:
        if suppressed:
            summary = "No new findings: all supplied anomalies were already included in a preview for this analysis run."
            empty_reason = "All supplied findings were already previewed for this analysis run."
        else:
            summary = "No anomaly findings were detected for this analysis run."
            empty_reason = summary
        return {
            "analysis_run_id": analysis_run_id,
            "subject": "AI Data Anomaly Summary — No new findings",
            "body": f"AI Data Anomaly Summary\nAnalysis run: {analysis_run_id}\n\n{empty_reason}\n\n{CAUTION}",
            "summary": summary,
            "findings": [],
            "finding_keys": [],
            "included_count": 0,
            "suppressed_count": suppressed,
        }

    severity_counts = Counter(
        str(item.get("severity") or "unspecified").strip().lower() for item in selected
    )
    count_summary = ", ".join(
        f"{severity_counts[level]} {level}"
        for level in ("critical", "high", "medium")
        if severity_counts[level]
    )
    other_count = sum(
        count for severity, count in severity_counts.items()
        if severity not in SEVERITY_ORDER
    )
    if other_count:
        count_summary = f"{count_summary}, " if count_summary else ""
        count_summary += f"{other_count} other"

    def priority(finding: Mapping[str, Any]) -> tuple[int, float]:
        severity = str(finding.get("severity") or "").strip().lower()
        change = _percentage_change(finding)
        return SEVERITY_ORDER.get(severity, 0), abs(change) if change is not None else 0.0

    most_important = max(selected, key=priority)
    top_metric = _metric_label(most_important)
    top_severity = str(most_important.get("severity") or "unspecified").strip().lower()
    top_direction = str(most_important.get("direction") or "changed").strip().lower()
    top_change = _percentage_change(most_important)
    change_phrase = f" by {abs(top_change):.1f}%" if top_change is not None else ""
    finding_word = "finding" if len(selected) == 1 else "findings"
    summary = (
        f"{len(selected)} new {finding_word}: {count_summary}. Most important: "
        f"{top_metric} {top_direction}{change_phrase} ({top_severity} severity). "
        "These rule-based signals merit review; they do not confirm a cause."
    )
    subject = f"AI Data Anomaly Alert — {len(selected)} {finding_word}"
    if severity_counts["critical"]:
        subject += f" ({severity_counts['critical']} critical)"

    message_lines = [
        "AI Data Anomaly Alert",
        f"Analysis run: {analysis_run_id}",
        f"New findings: {len(selected)}",
        "",
        f"Overall summary: {summary}",
        "",
    ]
    for index, finding in enumerate(selected, start=1):
        metric = _metric_label(finding)
        metric_key = str(finding.get("metric") or "").strip().casefold()
        date = str(finding.get("date") or "Date not available").strip()
        observed = finding.get("observed_value")
        baseline = finding.get("baseline_value")
        percentage = _percentage_change(finding)
        direction = str(finding.get("direction") or "Not available").strip().title()
        severity = str(finding.get("severity") or "Unspecified").strip().title()
        explanation = str(finding.get("explanation") or "This unusual value may warrant review.").strip()

        message_lines.extend([
            f"{index}. {metric} — {date}",
            f"   Observed value: {_display_value(metric_key, observed)}",
            f"   Historical baseline: {_display_value(metric_key, baseline)}",
        ])
        if percentage is not None:
            message_lines.append(f"   Percentage change: {percentage:+.1f}%")
        message_lines.extend([
            f"   Direction: {direction}",
            f"   Severity: {severity}",
            f"   Explanation: {explanation}",
            f"   Caution: {CAUTION}",
            "",
        ])

    return {
        "analysis_run_id": analysis_run_id,
        "subject": subject,
        "body": "\n".join(message_lines).rstrip(),
        "summary": summary,
        "findings": selected,
        "finding_keys": keys,
        "included_count": len(selected),
        "suppressed_count": suppressed,
    }
