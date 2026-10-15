"""Load business data from CSV and Excel files without dropping rows."""

import logging
from pathlib import Path

import pandas as pd


logger = logging.getLogger(__name__)


SUPPORTED_SUFFIXES = {".csv", ".xlsx"}


def load_business_data(file_path: str | Path, *, sheet_name: str | int = 0) -> pd.DataFrame:
    """Load a CSV or Excel worksheet into a DataFrame.

    Excel files use pandas' openpyxl engine. The function returns every row;
    validation is a separate step so malformed records are never discarded.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(f"Unsupported file type '{suffix}'. Supported types: {supported}.")

    if suffix == ".xls":
        raise ValueError("Legacy .xls files are not supported by openpyxl. Save the workbook as .xlsx and try again.")

    try:
        if suffix == ".csv":
            return pd.read_csv(path)
        return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    except pd.errors.EmptyDataError as exc:
        logger.info("Rejected empty CSV input (%s).", type(exc).__name__)
        raise ValueError("The CSV file is empty or has no header row.") from None
    except Exception as exc:
        # Avoid returning parser text: it can include local paths or source data.
        logger.warning("Could not read %s input (%s).", suffix.lstrip("."), type(exc).__name__)
        raise ValueError(
            f"Could not read this {suffix.lstrip('.').upper()} file. Check that it is readable and correctly formatted."
        ) from None
