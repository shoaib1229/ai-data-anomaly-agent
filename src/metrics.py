"""Calculate daily changes and strictly historical comparison metrics."""

from __future__ import annotations

import pandas as pd

from src.dates import normalize_daily_dates
from src.validate import REQUIRED_COLUMNS, validate_data


METRIC_COLUMNS = ["revenue", "orders", "conversion_rate", "traffic", "cost", "refunds"]


def calculate_metrics(
    data: pd.DataFrame,
    *,
    rolling_window: int = 7,
    baseline_window: int = 7,
    min_history: int = 7,
) -> pd.DataFrame:
    """Return input rows plus day-over-day, rolling, and prior-only metrics.

    Invalid rows remain in the result with ``row_valid=False`` and missing
    calculated values. They are excluded from later valid rows' baselines.
    A historical baseline for a row uses only earlier valid observations.
    Percentage changes are expressed as relative percentages (e.g. 25.0 means
    a 25% relative change).
    """
    for name, value in {
        "rolling_window": rolling_window,
        "baseline_window": baseline_window,
        "min_history": min_history,
    }.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
    if min_history > baseline_window:
        raise ValueError("min_history cannot be greater than baseline_window.")

    validation = validate_data(data)
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing_columns:
        raise ValueError(f"Input is missing required columns: {', '.join(missing_columns)}.")

    result = data.copy().reset_index(drop=True)
    result["row_number"] = range(2, len(result) + 2)
    result["normalized_date"] = normalize_daily_dates(result["date"])

    invalid_rows: set[int] = set()
    for issue in validation["errors"]:
        invalid_rows.update(issue["row_numbers"])
    result["row_valid"] = [row_number not in invalid_rows for row_number in result["row_number"]]

    for metric in METRIC_COLUMNS:
        for suffix in (
            "daily_change",
            "daily_pct_change",
            "rolling_average",
            "historical_baseline",
            "baseline_pct_change",
        ):
            result[f"{metric}_{suffix}"] = float("nan")
        result[f"{metric}_baseline_count"] = 0

    valid = result.loc[result["row_valid"]].sort_values("normalized_date", kind="stable").copy()
    for metric in METRIC_COLUMNS:
        values = pd.to_numeric(valid[metric], errors="coerce").astype(float)
        previous = values.shift(1)
        baseline = previous.rolling(window=baseline_window, min_periods=min_history).mean()
        daily_pct = ((values - previous) / previous.where(previous.ne(0))) * 100
        baseline_pct = ((values - baseline) / baseline.where(baseline.ne(0))) * 100

        calculated = {
            f"{metric}_daily_change": values.diff(),
            f"{metric}_daily_pct_change": daily_pct,
            f"{metric}_rolling_average": values.rolling(window=rolling_window, min_periods=1).mean(),
            f"{metric}_historical_baseline": baseline,
            f"{metric}_baseline_pct_change": baseline_pct,
            f"{metric}_baseline_count": previous.rolling(window=baseline_window, min_periods=1).count().astype(int),
        }
        for column, series in calculated.items():
            result.loc[valid.index, column] = series

    result["row_valid"] = result["row_valid"].astype(bool)
    return result
