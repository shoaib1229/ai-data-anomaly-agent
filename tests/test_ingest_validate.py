from pathlib import Path

import pandas as pd

from src.ingest import load_business_data
from src.validate import validate_data


def valid_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02"],
        "revenue": [1200.50, 980.0],
        "orders": [12, 10],
        "conversion_rate": [0.04, 0.035],
        "traffic": [300, 286],
        "cost": [400.0, 390.0],
        "refunds": [25.0, 0.0],
    })


def issue_codes(report: dict) -> set[str]:
    return {issue["code"] for issue in report["errors"]}


def test_valid_csv_loads_and_validates(tmp_path: Path) -> None:
    path = tmp_path / "valid.csv"
    valid_frame().to_csv(path, index=False)

    loaded = load_business_data(path)
    report = validate_data(loaded)

    assert len(loaded) == 2
    assert report["is_valid"] is True
    assert report["errors"] == []


def test_valid_excel_loads_and_validates(tmp_path: Path) -> None:
    path = tmp_path / "valid.xlsx"
    valid_frame().to_excel(path, index=False)

    report = validate_data(load_business_data(path))

    assert report["is_valid"] is True


def test_missing_columns_are_reported() -> None:
    frame = valid_frame().drop(columns=["refunds"])

    report = validate_data(frame)

    assert report["is_valid"] is False
    issue = next(item for item in report["errors"] if item["code"] == "missing_columns")
    assert issue["columns"] == ["refunds"]
    assert issue["row_numbers"] == []


def test_invalid_date_reports_source_row() -> None:
    frame = valid_frame()
    frame.loc[1, "date"] = "not-a-date"

    report = validate_data(frame)

    issue = next(item for item in report["errors"] if item["code"] == "invalid_date")
    assert issue["row_numbers"] == [3]
    assert issue["columns"] == ["date"]


def test_duplicate_dates_report_all_source_rows() -> None:
    frame = valid_frame()
    frame.loc[1, "date"] = frame.loc[0, "date"]

    report = validate_data(frame)

    issue = next(item for item in report["errors"] if item["code"] == "duplicate_dates")
    assert issue["row_numbers"] == [2, 3]


def test_missing_values_are_reported_without_dropping_rows() -> None:
    frame = valid_frame()
    frame.loc[0, "revenue"] = None

    report = validate_data(frame)

    issue = next(item for item in report["errors"] if item["code"] == "missing_values")
    assert issue["columns"] == ["revenue"]
    assert issue["row_numbers"] == [2]
    assert report["row_count"] == 2


def test_invalid_numeric_value_is_reported() -> None:
    frame = valid_frame()
    frame["cost"] = frame["cost"].astype("object")
    frame.loc[0, "cost"] = "unknown"

    report = validate_data(frame)

    issue = next(item for item in report["errors"] if item["code"] == "invalid_numeric")
    assert issue["columns"] == ["cost"]
    assert issue["row_numbers"] == [2]


def test_negative_and_out_of_range_values_are_reported() -> None:
    frame = valid_frame()
    frame.loc[0, "revenue"] = -5
    frame.loc[1, "conversion_rate"] = 1.2

    report = validate_data(frame)

    assert {"negative_value", "invalid_conversion_rate"}.issubset(issue_codes(report))


def test_unsupported_file_type_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.write_text("{}", encoding="utf-8")

    try:
        load_business_data(path)
    except ValueError as error:
        assert "Unsupported file type" in str(error)
    else:
        raise AssertionError("Expected an unsupported-file ValueError")


def test_empty_csv_fails_with_safe_actionable_message(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    try:
        load_business_data(path)
    except ValueError as error:
        assert "empty" in str(error).lower()
        assert str(tmp_path) not in str(error)
    else:
        raise AssertionError("Expected an empty-file ValueError")


def test_malformed_excel_fails_without_echoing_parser_details(tmp_path: Path) -> None:
    path = tmp_path / "not-a-workbook.xlsx"
    path.write_text("not an Excel workbook", encoding="utf-8")

    try:
        load_business_data(path)
    except ValueError as error:
        assert "correctly formatted" in str(error)
        assert str(tmp_path) not in str(error)
    else:
        raise AssertionError("Expected a malformed-workbook ValueError")


def test_mixed_timezone_dates_validate_by_source_calendar_day() -> None:
    frame = valid_frame()
    frame["date"] = ["2026-01-01T23:30:00-02:00", "2026-01-02T00:15:00+03:00"]

    report = validate_data(frame)

    assert report["is_valid"] is True


def test_numeric_dates_are_not_silently_treated_as_epoch_values() -> None:
    frame = valid_frame()
    frame["date"] = frame["date"].astype(object)
    frame.loc[0, "date"] = 12345

    report = validate_data(frame)

    issue = next(item for item in report["errors"] if item["code"] == "invalid_date")
    assert issue["row_numbers"] == [2]
