import pandas as pd

from src.detect import detect_anomalies
from src.metrics import calculate_metrics


def business_frame(count: int = 12) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=count, freq="D").strftime("%Y-%m-%d"),
        "revenue": [100.0] * count,
        "orders": [10] * count,
        "conversion_rate": [0.05] * count,
        "traffic": [200] * count,
        "cost": [40.0] * count,
        "refunds": [2.0] * count,
    })


def test_calculates_daily_changes_rolling_average_and_prior_baseline() -> None:
    frame = business_frame(9)
    frame.loc[7, "revenue"] = 150.0

    result = calculate_metrics(frame)

    # Date 8's baseline sees the seven preceding values and never includes itself.
    assert result.loc[7, "revenue_historical_baseline"] == 100.0
    assert result.loc[7, "revenue_baseline_pct_change"] == 50.0
    assert result.loc[7, "revenue_daily_change"] == 50.0
    assert result.loc[7, "revenue_daily_pct_change"] == 50.0
    assert result.loc[7, "revenue_rolling_average"] == (6 * 100 + 150) / 7


def test_future_values_do_not_change_an_earlier_baseline() -> None:
    original = business_frame(12)
    changed_future = original.copy()
    changed_future.loc[8:, "revenue"] = [900.0, 20.0, 700.0, 10.0]

    original_metrics = calculate_metrics(original)
    changed_metrics = calculate_metrics(changed_future)

    assert original_metrics.loc[7, "revenue_historical_baseline"] == 100.0
    assert changed_metrics.loc[7, "revenue_historical_baseline"] == 100.0


def test_metric_dates_handle_mixed_timezone_offsets_consistently() -> None:
    frame = business_frame(2)
    frame["date"] = ["2026-01-01T23:30:00-02:00", "2026-01-02T00:15:00+03:00"]

    result = calculate_metrics(frame)

    assert result["normalized_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-01", "2026-01-02"
    ]


def test_reports_positive_and_negative_anomalies() -> None:
    frame = business_frame(10)
    frame.loc[7, "revenue"] = 150.0
    frame.loc[8, "orders"] = 4

    report = detect_anomalies(frame, baseline_window=9, min_history=7)

    by_metric_date = {(item["metric"], item["date"]): item for item in report["anomalies"]}
    positive = by_metric_date[("revenue", "2026-01-08")]
    negative = by_metric_date[("orders", "2026-01-09")]
    assert positive["direction"] == "increase"
    assert positive["baseline_value"] == 100.0
    assert positive["percentage_change"] == 50.0
    assert negative["direction"] == "decrease"
    assert negative["percentage_change"] == -60.0
    assert positive["severity"] in {"medium", "high", "critical"}
    assert "Revenue" in positive["explanation"]
    assert "does not establish the cause" in positive["explanation"]


def test_normal_variation_is_not_flagged_with_configured_threshold() -> None:
    frame = business_frame(10)
    frame.loc[7, "revenue"] = 110.0

    report = detect_anomalies(frame, thresholds_pct={"revenue": 20.0})

    assert not any(item["metric"] == "revenue" for item in report["anomalies"])


def test_insufficient_history_skips_evaluation() -> None:
    report = detect_anomalies(business_frame(6))

    assert report["status"] == "insufficient_history"
    assert report["anomalies"] == []
    assert report["summary"]["evaluated_rows"] == 0
    assert {item["reason"] for item in report["skipped_evaluations"]} == {"insufficient_history"}


def test_zero_baseline_is_skipped_without_false_alarm() -> None:
    frame = business_frame(8)
    frame["refunds"] = [0.0] * 8
    frame.loc[7, "refunds"] = 50.0

    report = detect_anomalies(frame, baseline_window=9, min_history=7)

    assert not any(item["metric"] == "refunds" for item in report["anomalies"])
    skipped = [item for item in report["skipped_evaluations"] if item["metric"] == "refunds"]
    assert skipped[-1]["reason"] == "zero_baseline"


def test_invalid_row_is_reported_and_excluded_from_baselines() -> None:
    frame = business_frame(10)
    frame["revenue"] = frame["revenue"].astype(object)
    frame.loc[2, "revenue"] = "not numeric"
    frame.loc[9, "revenue"] = 150.0

    report = detect_anomalies(frame, baseline_window=9, min_history=7)

    assert report["summary"]["excluded_rows"] == 1
    assert report["excluded_rows"][0]["row_number"] == 4
    anomaly = next(item for item in report["anomalies"] if item["metric"] == "revenue")
    assert anomaly["baseline_count"] == 8
    assert anomaly["baseline_value"] == 100.0


def test_missing_value_is_reported_and_not_used_for_metrics() -> None:
    frame = business_frame(10)
    frame.loc[1, "traffic"] = None
    frame.loc[9, "traffic"] = 400

    report = detect_anomalies(frame, baseline_window=9, min_history=7)

    excluded = next(item for item in report["excluded_rows"] if item["row_number"] == 3)
    assert "missing_values" in excluded["issue_codes"]
    anomaly = next(item for item in report["anomalies"] if item["metric"] == "traffic")
    assert anomaly["baseline_count"] == 8
    assert anomaly["baseline_value"] == 200.0


def test_report_identifies_missing_schema_as_invalid_input() -> None:
    frame = business_frame(10).drop(columns=["refunds"])

    report = detect_anomalies(frame)

    assert report["status"] == "invalid_input"
    assert report["summary"]["excluded_rows"] == 10
    assert report["anomalies"] == []
