"""Deterministic validation for daily business metric data."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from src.dates import normalize_daily_dates


REQUIRED_COLUMNS = [
    "date",
    "revenue",
    "orders",
    "conversion_rate",
    "traffic",
    "cost",
    "refunds",
]
NON_NEGATIVE_COLUMNS = ["revenue", "orders", "traffic", "cost", "refunds"]
INTEGER_COLUMNS = ["orders", "traffic"]
NUMERIC_COLUMNS = [
    "revenue",
    "orders",
    "conversion_rate",
    "traffic",
    "cost",
    "refunds",
]


def _row_numbers(mask: Iterable[bool]) -> list[int]:
    """Return spreadsheet-style row numbers (header is row 1)."""
    return [position + 2 for position, matches in enumerate(mask) if bool(matches)]


def validate_data(data: pd.DataFrame) -> dict:
    """Return a JSON-friendly validation report without changing ``data``.

    Errors identify source row numbers, where row 1 is the header and the
    first data record is row 2. Warnings are non-blocking observations.
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    def add_issue(target: list[dict], severity: str, code: str, message: str,
                  rows: list[int], columns: list[str]) -> None:
        target.append({
            "severity": severity,
            "code": code,
            "message": message,
            "row_numbers": rows,
            "columns": columns,
        })

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing_columns:
        add_issue(errors, "error", "missing_columns",
                  "Required columns are missing.", [], missing_columns)

    extra_columns = [column for column in data.columns if column not in REQUIRED_COLUMNS]
    if extra_columns:
        add_issue(warnings, "warning", "unexpected_columns",
                  "Columns outside the expected business schema were found and retained.",
                  [], list(extra_columns))

    # Only validate fields present in the input, while still reporting the
    # missing-column issue above.
    present = [column for column in REQUIRED_COLUMNS if column in data.columns]

    for column in present:
        missing_mask = data[column].isna()
        if missing_mask.any():
            add_issue(errors, "error", "missing_values",
                      f"'{column}' contains missing values.",
                      _row_numbers(missing_mask.tolist()), [column])

    if "date" in data.columns:
        raw_dates = data["date"]
        parsed_dates = normalize_daily_dates(raw_dates)
        invalid_date_mask = raw_dates.notna() & parsed_dates.isna()
        if invalid_date_mask.any():
            add_issue(errors, "error", "invalid_date",
                      "Date values could not be parsed.",
                      _row_numbers(invalid_date_mask.tolist()), ["date"])

        usable_dates = parsed_dates.notna()
        duplicate_mask = usable_dates & parsed_dates.dt.normalize().duplicated(keep=False)
        if duplicate_mask.any():
            add_issue(errors, "error", "duplicate_dates",
                      "Dates must be unique; all rows sharing a duplicate date are listed.",
                      _row_numbers(duplicate_mask.tolist()), ["date"])

    numeric_values: dict[str, pd.Series] = {}
    for column in NUMERIC_COLUMNS:
        if column not in data.columns:
            continue
        raw_values = data[column]
        parsed_values = pd.to_numeric(raw_values, errors="coerce")
        numeric_values[column] = parsed_values
        invalid_mask = raw_values.notna() & (
            parsed_values.isna() | parsed_values.isin([float("inf"), float("-inf")])
        )
        if invalid_mask.any():
            add_issue(errors, "error", "invalid_numeric",
                      f"'{column}' contains values that are not numeric.",
                      _row_numbers(invalid_mask.tolist()), [column])

    for column in NON_NEGATIVE_COLUMNS:
        if column not in numeric_values:
            continue
        negative_mask = numeric_values[column].lt(0).fillna(False)
        if negative_mask.any():
            add_issue(errors, "error", "negative_value",
                      f"'{column}' cannot be negative.",
                      _row_numbers(negative_mask.tolist()), [column])

    for column in INTEGER_COLUMNS:
        if column not in numeric_values:
            continue
        values = numeric_values[column]
        fractional_mask = values.notna() & values.mod(1).ne(0)
        if fractional_mask.any():
            add_issue(errors, "error", "invalid_integer",
                      f"'{column}' must contain whole numbers.",
                      _row_numbers(fractional_mask.tolist()), [column])

    if "conversion_rate" in numeric_values:
        rate = numeric_values["conversion_rate"]
        invalid_rate_mask = rate.notna() & ((rate < 0) | (rate > 1))
        if invalid_rate_mask.any():
            add_issue(errors, "error", "invalid_conversion_rate",
                      "Conversion rate must be between 0 and 1 inclusive (a fraction, not a percent).",
                      _row_numbers(invalid_rate_mask.tolist()), ["conversion_rate"])

    return {
        "is_valid": not errors,
        "row_count": int(len(data)),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
