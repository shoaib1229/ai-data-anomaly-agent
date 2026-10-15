"""Consistent daily-date parsing for validation and metric calculations."""

from __future__ import annotations

from numbers import Number

import pandas as pd


def normalize_daily_dates(values: pd.Series) -> pd.Series:
    """Parse values to timezone-naive midnight dates without shifting their day.

    Business input is daily. For timezone-aware timestamps, the calendar day
    written in the source timestamp is retained, so different offsets cannot
    make pandas fail or unexpectedly move a row onto a neighboring day.
    Numeric values are rejected rather than interpreted as nanoseconds since
    the Unix epoch.
    """
    normalized = []
    for value in values:
        try:
            missing = bool(pd.isna(value))
        except (TypeError, ValueError):
            missing = False
        if missing or isinstance(value, (bool, Number)):
            normalized.append(pd.NaT)
            continue
        try:
            parsed = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError):
            normalized.append(pd.NaT)
            continue
        if pd.isna(parsed):
            normalized.append(pd.NaT)
        else:
            normalized.append(pd.Timestamp(parsed.date()))
    return pd.Series(normalized, index=values.index, dtype="datetime64[ns]")
