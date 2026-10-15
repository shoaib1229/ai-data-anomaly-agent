"""Streamlit dashboard for local analysis and anomaly history."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from src.alerts import create_email_preview
from src.dashboard import filter_anomalies
from src.detect import DEFAULT_THRESHOLDS_PCT, detect_anomalies
from src.ingest import load_business_data
from src.metrics import METRIC_COLUMNS, calculate_metrics
from src.storage import (
    DEFAULT_DB_PATH,
    StorageError,
    claim_unpreviewed_findings,
    get_analysis_history,
    get_previewed_finding_keys,
    initialize_database,
    save_analysis,
)
from src.validate import REQUIRED_COLUMNS, validate_data


DB_PATH = Path(os.environ.get("AI_ANOMALY_AGENT_DB_PATH", str(DEFAULT_DB_PATH)))
logger = logging.getLogger(__name__)

st.set_page_config(page_title="AI Data Anomaly Agent", page_icon="📈", layout="wide")
st.title("AI Data Anomaly Agent")
st.caption(
    "A local portfolio project that checks daily business data, compares each day "
    "with its past, and explains unusual changes. It flags signals for review; it "
    "does not prove a cause."
)

try:
    initialize_database(DB_PATH)
except StorageError as exc:
    logger.error("Local SQLite initialization failed (%s).", type(exc).__name__)
    st.error("The local SQLite database could not be opened. Check its configured path and permissions.")
    st.stop()

with st.sidebar:
    st.header("Detection settings")
    baseline_window = st.number_input("Historical baseline window (valid days)", min_value=1, value=7, step=1)
    min_history = st.number_input(
        "Minimum prior observations",
        min_value=1,
        max_value=int(baseline_window),
        value=min(7, int(baseline_window)),
        step=1,
    )
    rolling_window = st.number_input("Rolling average window", min_value=1, value=7, step=1)
    with st.expander("Metric thresholds (%)"):
        thresholds_pct = {
            metric: st.number_input(
                metric.replace("_", " ").title(),
                min_value=0.1,
                max_value=500.0,
                value=float(DEFAULT_THRESHOLDS_PCT[metric]),
                step=1.0,
            )
            for metric in METRIC_COLUMNS
        }
    st.caption(f"SQLite file: `{DB_PATH}`")

uploaded_file = st.file_uploader("Choose a CSV or Excel (.xlsx) file", type=["csv", "xlsx"])

if uploaded_file is not None:
    upload_bytes = uploaded_file.getvalue()
    suffix = Path(uploaded_file.name).suffix.lower()
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="anomaly-agent-", suffix=suffix, delete=False) as temporary_file:
            temporary_file.write(upload_bytes)
            temporary_path = Path(temporary_file.name)
        frame = load_business_data(temporary_path)
    except (OSError, ValueError, UnicodeError, ImportError) as exc:
        # Ingestion logs the exception class locally; do not echo paths or parser
        # details from an uploaded file back into the dashboard.
        logger.info("Upload could not be processed (%s).", type(exc).__name__)
        st.error("Could not read this file. Upload a readable CSV or .xlsx workbook with a header row.")
        frame = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                st.warning("The temporary upload file could not be removed automatically.")

    if frame is not None:
        validation = validate_data(frame)
        summary_columns = st.columns(4)
        summary_columns[0].metric("Rows", validation["row_count"])
        summary_columns[1].metric("Validation issues", validation["error_count"])
        summary_columns[2].metric("Warnings", validation["warning_count"])
        has_required_columns = all(column in frame.columns for column in REQUIRED_COLUMNS)

        if validation["is_valid"]:
            st.success("All rows passed validation.")
        elif has_required_columns:
            st.warning("Some rows have validation errors. They remain visible and are excluded from calculations.")
        else:
            st.error("Required columns are missing. No metrics or anomalies can be calculated for this file.")

        if validation["errors"]:
            with st.expander("Validation errors", expanded=True):
                st.dataframe(pd.DataFrame(validation["errors"]), hide_index=True, width="stretch")
        if validation["warnings"]:
            with st.expander("Validation warnings"):
                st.dataframe(pd.DataFrame(validation["warnings"]), hide_index=True, width="stretch")

        if not has_required_columns:
            st.subheader("Uploaded data preview")
            st.dataframe(frame, hide_index=True, width="stretch")
        else:
            try:
                metrics_frame = calculate_metrics(
                    frame,
                    rolling_window=int(rolling_window),
                    baseline_window=int(baseline_window),
                    min_history=int(min_history),
                )
                valid_rows = metrics_frame.loc[metrics_frame["row_valid"]].sort_values("normalized_date")
                invalid_rows = metrics_frame.loc[~metrics_frame["row_valid"]]
                if not invalid_rows.empty:
                    st.subheader("Rows excluded from calculations")
                    st.dataframe(
                        invalid_rows[["row_number", "date", *METRIC_COLUMNS]],
                        hide_index=True,
                        width="stretch",
                    )

                if valid_rows.empty:
                    st.info("There are no valid rows to analyze. Correct the validation errors and upload the file again.")
                else:
                    latest = valid_rows.iloc[-1]
                    st.subheader(f"Latest valid day: {latest['normalized_date'].date().isoformat()}")
                    kpis = st.columns(6)
                    kpi_values = [
                        ("Revenue (latest day)", f"{float(latest['revenue']):,.2f}"),
                        ("Orders (latest day)", f"{float(latest['orders']):,.0f}"),
                        ("Conversion rate (latest day)", f"{float(latest['conversion_rate']) * 100:.2f}%"),
                        ("Traffic (latest day)", f"{float(latest['traffic']):,.0f}"),
                        ("Cost (latest day)", f"{float(latest['cost']):,.2f}"),
                        ("Refunds (latest day)", f"{float(latest['refunds']):,.2f}"),
                    ]
                    for column, (label, value) in zip(kpis, kpi_values):
                        column.metric(label, value)

                    chart_columns = st.columns(2)
                    chart_data = valid_rows[["normalized_date", "revenue", "orders"]].copy()
                    chart_data["revenue"] = pd.to_numeric(chart_data["revenue"], errors="coerce")
                    chart_data["orders"] = pd.to_numeric(chart_data["orders"], errors="coerce")
                    chart_data = chart_data.set_index("normalized_date")
                    chart_columns[0].subheader("Revenue trend")
                    chart_columns[0].line_chart(chart_data[["revenue"]])
                    chart_columns[1].subheader("Orders trend")
                    chart_columns[1].line_chart(chart_data[["orders"]])

                    report = detect_anomalies(
                        frame,
                        thresholds_pct=thresholds_pct,
                        baseline_window=int(baseline_window),
                        min_history=int(min_history),
                        rolling_window=int(rolling_window),
                    )
                    st.subheader("Anomaly summary")
                    severity_counts = {level: 0 for level in ("medium", "high", "critical")}
                    for finding in report["anomalies"]:
                        severity_counts[finding["severity"]] = severity_counts.get(finding["severity"], 0) + 1
                    anomaly_cards = st.columns(4)
                    anomaly_cards[0].metric("Anomalies", report["summary"]["anomaly_count"])
                    anomaly_cards[1].metric("Medium", severity_counts["medium"])
                    anomaly_cards[2].metric("High", severity_counts["high"])
                    anomaly_cards[3].metric("Critical", severity_counts["critical"])

                    if report["anomalies"]:
                        st.caption("Filter the findings shown below. The alert preview still includes all unpreviewed findings for this run.")
                        filter_columns = st.columns(2)
                        severity_options = sorted({item["severity"].title() for item in report["anomalies"]})
                        metric_options = sorted({item["metric"] for item in report["anomalies"]})
                        selected_severities = filter_columns[0].multiselect(
                            "Severity", severity_options, default=severity_options
                        )
                        selected_metrics = filter_columns[1].multiselect(
                            "Metric", metric_options,
                            format_func=lambda value: value.replace("_", " ").title(),
                            default=metric_options,
                        )
                        visible_findings = filter_anomalies(
                            report["anomalies"],
                            metrics=set(selected_metrics),
                            severities=set(selected_severities),
                        )
                        st.caption(f"Showing {len(visible_findings)} of {len(report['anomalies'])} findings.")
                        if visible_findings:
                            findings_frame = pd.DataFrame(visible_findings).rename(columns={
                                "date": "Date",
                                "metric_label": "Metric",
                                "observed_value": "Observed value",
                                "baseline_value": "Historical baseline",
                                "percentage_change": "Change (%)",
                                "direction": "Direction",
                                "severity": "Severity",
                                "explanation": "Explanation",
                            })
                            findings_frame["Severity"] = findings_frame["Severity"].str.title()
                            findings_frame["Direction"] = findings_frame["Direction"].str.title()
                            st.dataframe(
                                findings_frame[[
                                    "Date", "Metric", "Observed value", "Historical baseline",
                                    "Change (%)", "Direction", "Severity", "Explanation",
                                ]],
                                hide_index=True,
                                width="stretch",
                            )
                        else:
                            st.info("No findings match these filters. Select another severity or metric to see more.")
                    else:
                        skipped_reasons: dict[str, int] = {}
                        for skipped_item in report["skipped_evaluations"]:
                            reason = skipped_item["reason"]
                            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                        if skipped_reasons:
                            skipped_text = ", ".join(
                                f"{count} {reason.replace('_', ' ')}"
                                for reason, count in sorted(skipped_reasons.items())
                            )
                            st.info(f"No anomalies crossed the configured thresholds. Skipped comparisons: {skipped_text}.")
                        else:
                            st.info("No anomalies crossed the configured thresholds.")

                    usable_status = report["status"] in {"complete", "insufficient_history"}
                    if usable_status:
                        metadata = {
                            "content_sha256": hashlib.sha256(upload_bytes).hexdigest(),
                            "file_type": suffix.lstrip("."),
                            "size_bytes": len(upload_bytes),
                            "row_count": len(frame),
                        }
                        saved_run_id = None
                        try:
                            saved = save_analysis(
                                DB_PATH,
                                source_metadata=metadata,
                                analysis_report=report,
                            )
                            saved_run_id = saved["run_id"]
                            if saved["created"]:
                                st.success(f"Analysis saved to local history (run {saved['run_id']}).")
                            else:
                                st.info(f"This file and configuration are already saved as run {saved['run_id']}.")
                        except ValueError as exc:
                            st.info(f"This analysis was not saved: {exc}")
                        except StorageError as exc:
                            logger.error("SQLite analysis save failed (%s).", type(exc).__name__)
                            st.error("Could not save this analysis to the local SQLite database.")

                        if saved_run_id is not None and report["anomalies"]:
                            st.subheader("Unsent email preview")
                            st.caption("Generate a plain-text draft. No email is sent.")
                            if st.button("Generate new email preview", key=f"preview-alert-{saved_run_id}"):
                                try:
                                    new_findings = claim_unpreviewed_findings(
                                        DB_PATH, saved_run_id, report["anomalies"]
                                    )
                                    if new_findings:
                                        preview = create_email_preview(
                                            new_findings, analysis_run_id=saved_run_id
                                        )
                                    else:
                                        preview = create_email_preview(
                                            report["anomalies"],
                                            analysis_run_id=saved_run_id,
                                            previously_included=get_previewed_finding_keys(
                                                DB_PATH, saved_run_id
                                            ),
                                        )
                                    st.session_state[f"alert-preview-{saved_run_id}"] = preview
                                except StorageError as exc:
                                    logger.error("Alert preview persistence failed (%s).", type(exc).__name__)
                                    st.error("Could not prepare the local alert preview. Check database access.")

                            preview = st.session_state.get(f"alert-preview-{saved_run_id}")
                            if preview:
                                st.markdown(f"**Subject:** {preview['subject']}")
                                st.code(preview["body"], language=None)
                                st.caption("This is a local preview only; it has not been emailed.")
            except (ValueError, TypeError) as exc:
                st.error(f"Could not calculate metrics for this file: {exc}")

st.divider()
st.subheader("Analysis history")
try:
    history = get_analysis_history(DB_PATH, limit=50)
    if history:
        history_frame = pd.DataFrame(history).rename(columns={
            "analysis_timestamp": "Analyzed at (UTC)",
            "id": "Run",
            "file_type": "Source type",
            "row_count": "Source rows",
            "status": "Status",
            "anomaly_count": "Anomalies",
            "evaluated_rows": "Rows evaluated",
            "excluded_rows": "Rows excluded",
            "size_bytes": "File size (bytes)",
            "source_hash_prefix": "Source ID (short hash)",
        })
        st.dataframe(
            history_frame[[
                "Run", "Analyzed at (UTC)", "Status", "Anomalies", "Rows evaluated",
                "Rows excluded", "Source type", "Source rows", "File size (bytes)",
                "Source ID (short hash)",
            ]],
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No saved analyses yet. Upload valid data to create the first history entry.")
except StorageError as exc:
    logger.error("SQLite history retrieval failed (%s).", type(exc).__name__)
    st.error("Could not retrieve local analysis history. Check database access.")
