"""Deterministic, business-friendly anomaly explanations."""

from __future__ import annotations


METRIC_LABELS = {
    "revenue": "Revenue",
    "orders": "Orders",
    "conversion_rate": "Conversion rate",
    "traffic": "Traffic",
    "cost": "Cost",
    "refunds": "Refunds",
}


def format_value(metric: str, value: float) -> str:
    """Format a value without assuming a currency or locale."""
    if metric == "conversion_rate":
        return f"{value * 100:.2f}%"
    return f"{value:,.2f}"


def build_explanation(
    *,
    metric: str,
    observed_value: float,
    baseline_value: float,
    percentage_change: float,
    direction: str,
    severity: str,
    baseline_count: int,
    threshold_pct: float,
) -> str:
    """Explain an unusual comparison without claiming a cause or certainty."""
    label = METRIC_LABELS.get(metric, metric.replace("_", " ").title())
    direction_text = "above" if direction == "increase" else "below"
    return (
        f"{label} was {format_value(metric, observed_value)}, "
        f"{abs(percentage_change):.1f}% {direction_text} the prior {baseline_count}-day "
        f"baseline of {format_value(metric, baseline_value)}. This is a {severity} "
        f"anomaly under the configured {threshold_pct:.1f}% threshold. "
        "This flags an unusual value; it does not establish the cause or statistical certainty."
    )
