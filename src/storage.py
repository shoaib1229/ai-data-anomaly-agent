"""SQLite persistence for analysis metadata and anomaly findings.

Only source metadata, validation summaries, run configuration, and detected
findings are stored. Uploaded file contents and ordinary metric rows are not.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "anomaly_agent.sqlite3"


class StorageError(RuntimeError):
    """Raised when SQLite could not initialize, save, or retrieve data."""


@contextmanager
def _connect(db_path: str | Path):
    connection = sqlite3.connect(str(db_path), timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Create the Phase 3 tables if they do not already exist."""
    path = Path(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _connect(path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_files (
                    id INTEGER PRIMARY KEY,
                    content_sha256 TEXT NOT NULL UNIQUE,
                    file_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                    row_count INTEGER NOT NULL CHECK (row_count >= 0),
                    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );

                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY,
                    analysis_key TEXT NOT NULL UNIQUE,
                    source_file_id INTEGER NOT NULL REFERENCES source_files(id),
                    analysis_timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    status TEXT NOT NULL,
                    configuration_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    anomaly_count INTEGER NOT NULL CHECK (anomaly_count >= 0),
                    evaluated_rows INTEGER NOT NULL CHECK (evaluated_rows >= 0),
                    excluded_rows INTEGER NOT NULL CHECK (excluded_rows >= 0)
                );

                CREATE TABLE IF NOT EXISTS anomaly_findings (
                    id INTEGER PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    anomaly_date TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    observed_value REAL NOT NULL,
                    baseline_value REAL NOT NULL,
                    change_value REAL NOT NULL,
                    percentage_change REAL NOT NULL,
                    direction TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    threshold_pct REAL NOT NULL,
                    baseline_count INTEGER NOT NULL CHECK (baseline_count >= 0),
                    explanation TEXT NOT NULL,
                    UNIQUE (run_id, anomaly_date, metric)
                );

                CREATE TABLE IF NOT EXISTS alert_preview_items (
                    analysis_run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
                    anomaly_date TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    previewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    PRIMARY KEY (analysis_run_id, anomaly_date, metric)
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_runs_timestamp
                    ON analysis_runs(analysis_timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_anomaly_findings_run
                    ON anomaly_findings(run_id);
                """
            )
    except (OSError, sqlite3.Error) as exc:
        raise StorageError(f"Could not initialize the SQLite database: {exc}") from exc


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validated_source_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    digest = metadata.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("Source metadata must include a 64-character SHA-256 digest.")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError("Source SHA-256 digest must contain hexadecimal characters.") from exc

    file_type = str(metadata.get("file_type", "")).lower().lstrip(".")
    if file_type not in {"csv", "xlsx"}:
        raise ValueError("Source file type must be csv or xlsx.")
    values = {}
    for name in ("size_bytes", "row_count"):
        value = metadata.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Source {name} must be a non-negative integer.")
        values[name] = value
    return {"content_sha256": digest.lower(), "file_type": file_type, **values}


def _validated_analysis(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    status = report.get("status")
    if status not in {"complete", "insufficient_history"}:
        raise ValueError("Only completed analyses with usable input can be saved.")
    validation = report.get("input_validation")
    if not isinstance(validation, dict):
        raise ValueError("Analysis report is missing input validation details.")
    if any(issue.get("code") == "missing_columns" for issue in validation.get("errors", [])):
        raise ValueError("Analysis cannot be saved when required columns are missing.")
    row_count = validation.get("row_count", 0)
    excluded_numbers = {
        row_number
        for issue in validation.get("errors", [])
        for row_number in issue.get("row_numbers", [])
    }
    if not isinstance(row_count, int) or row_count - len(excluded_numbers) < 1:
        raise ValueError("Analysis cannot be saved because it has no valid data rows.")

    configuration = report.get("configuration", {})
    summary = report.get("summary", {})
    anomalies = report.get("anomalies", [])
    if not isinstance(configuration, dict) or not isinstance(summary, dict) or not isinstance(anomalies, list):
        raise ValueError("Analysis report contains invalid configuration, summary, or findings.")
    required_finding_fields = {
        "date", "metric", "observed_value", "baseline_value", "change_value",
        "percentage_change", "direction", "severity", "threshold_pct",
        "baseline_count", "explanation",
    }
    for finding in anomalies:
        if not isinstance(finding, dict) or not required_finding_fields.issubset(finding):
            raise ValueError("Anomaly finding is missing required fields.")
        for field in ("observed_value", "baseline_value", "change_value", "percentage_change", "threshold_pct"):
            value = finding[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Anomaly field '{field}' must be a finite number.")
        if not isinstance(finding["baseline_count"], int) or finding["baseline_count"] < 0:
            raise ValueError("Anomaly baseline_count must be a non-negative integer.")
        for field in ("date", "metric", "direction", "severity", "explanation"):
            if not isinstance(finding[field], str):
                raise ValueError(f"Anomaly field '{field}' must be text.")
    return configuration, validation, anomalies


def save_analysis(
    db_path: str | Path,
    *,
    source_metadata: dict[str, Any],
    analysis_report: dict[str, Any],
) -> dict[str, Any]:
    """Persist one usable report and its anomaly findings transactionally.

    Repeating the same input file and configuration returns the existing run
    instead of inserting duplicate source, run, or finding records.
    """
    source = _validated_source_metadata(source_metadata)
    configuration, validation, anomalies = _validated_analysis(analysis_report)
    config_json = _json(configuration)
    validation_json = _json(validation)
    analysis_key = hashlib.sha256(
        f"{source['content_sha256']}:{config_json}".encode("utf-8")
    ).hexdigest()
    summary = analysis_report["summary"]

    initialize_database(db_path)
    try:
        with _connect(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id FROM analysis_runs WHERE analysis_key = ?",
                (analysis_key,),
            ).fetchone()
            if existing:
                return {"run_id": int(existing["id"]), "created": False}

            connection.execute(
                """INSERT INTO source_files
                   (content_sha256, file_type, size_bytes, row_count)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(content_sha256) DO NOTHING""",
                (source["content_sha256"], source["file_type"], source["size_bytes"], source["row_count"]),
            )
            source_row = connection.execute(
                "SELECT id FROM source_files WHERE content_sha256 = ?",
                (source["content_sha256"],),
            ).fetchone()
            cursor = connection.execute(
                """INSERT INTO analysis_runs
                   (analysis_key, source_file_id, status, configuration_json,
                    validation_json, anomaly_count, evaluated_rows, excluded_rows)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    analysis_key,
                    int(source_row["id"]),
                    analysis_report["status"],
                    config_json,
                    validation_json,
                    int(summary.get("anomaly_count", len(anomalies))),
                    int(summary.get("evaluated_rows", 0)),
                    len({
                        row_number
                        for issue in validation.get("errors", [])
                        for row_number in issue.get("row_numbers", [])
                    }),
                ),
            )
            run_id = int(cursor.lastrowid)
            for finding in anomalies:
                values = (
                    run_id,
                    finding["date"],
                    finding["metric"],
                    float(finding["observed_value"]),
                    float(finding["baseline_value"]),
                    float(finding["change_value"]),
                    float(finding["percentage_change"]),
                    finding["direction"],
                    finding["severity"],
                    float(finding["threshold_pct"]),
                    int(finding["baseline_count"]),
                    finding["explanation"],
                )
                if not all(math.isfinite(value) for value in values[2:7] if isinstance(value, float)):
                    raise ValueError("Anomaly values must be finite numbers.")
                connection.execute(
                    """INSERT INTO anomaly_findings
                       (run_id, anomaly_date, metric, observed_value, baseline_value,
                        change_value, percentage_change, direction, severity,
                        threshold_pct, baseline_count, explanation)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
            connection.commit()
            return {"run_id": run_id, "created": True}
    except ValueError:
        raise
    except (OSError, sqlite3.Error, TypeError) as exc:
        raise StorageError(f"Could not save the analysis: {exc}") from exc


def get_analysis_history(db_path: str | Path = DEFAULT_DB_PATH, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent runs with source metadata; ``limit`` is safely bound."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer from 1 through 500.")
    initialize_database(db_path)
    try:
        with _connect(db_path) as connection:
            rows = connection.execute(
                """SELECT r.id, r.analysis_timestamp, r.status, r.anomaly_count,
                          r.evaluated_rows, r.excluded_rows, r.configuration_json,
                          r.validation_json, s.file_type, s.size_bytes, s.row_count,
                          substr(s.content_sha256, 1, 12) AS source_hash_prefix
                   FROM analysis_runs AS r
                   JOIN source_files AS s ON s.id = r.source_file_id
                   ORDER BY r.analysis_timestamp DESC, r.id DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
    except (OSError, sqlite3.Error) as exc:
        raise StorageError(f"Could not retrieve analysis history: {exc}") from exc


def get_anomaly_findings(db_path: str | Path, run_id: int) -> list[dict[str, Any]]:
    """Return findings for a run ID using a parameterized query."""
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise ValueError("run_id must be a positive integer.")
    initialize_database(db_path)
    try:
        with _connect(db_path) as connection:
            rows = connection.execute(
                """SELECT anomaly_date, metric, observed_value, baseline_value,
                          change_value, percentage_change, direction, severity,
                          threshold_pct, baseline_count, explanation
                   FROM anomaly_findings WHERE run_id = ?
                   ORDER BY anomaly_date DESC, metric""",
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]
    except (OSError, sqlite3.Error) as exc:
        raise StorageError(f"Could not retrieve anomaly findings: {exc}") from exc


def claim_unpreviewed_findings(
    db_path: str | Path,
    run_id: int,
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Record findings included in a preview and return only newly claimed ones.

    The composite primary key makes this operation safe against repeated
    dashboard reruns and concurrent preview requests for the same analysis.
    No email is sent by this function.
    """
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise ValueError("run_id must be a positive integer.")
    if not isinstance(findings, list):
        raise ValueError("findings must be a list.")
    for finding in findings:
        if not isinstance(finding, dict) or not finding.get("date") or not finding.get("metric"):
            raise ValueError("Each finding must include a date and metric for duplicate protection.")

    initialize_database(db_path)
    newly_claimed = []
    seen: set[tuple[str, str]] = set()
    try:
        with _connect(db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_exists = connection.execute(
                "SELECT 1 FROM analysis_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if run_exists is None:
                raise ValueError(f"Analysis run {run_id} does not exist.")
            for finding in findings:
                identity = (str(finding["date"]), str(finding["metric"]).casefold())
                if identity in seen:
                    continue
                seen.add(identity)
                cursor = connection.execute(
                    """INSERT INTO alert_preview_items (analysis_run_id, anomaly_date, metric)
                       VALUES (?, ?, ?)
                       ON CONFLICT(analysis_run_id, anomaly_date, metric) DO NOTHING""",
                    (run_id, identity[0], identity[1]),
                )
                if cursor.rowcount == 1:
                    newly_claimed.append(finding)
            connection.commit()
        return newly_claimed
    except (OSError, sqlite3.Error) as exc:
        raise StorageError(f"Could not record alert preview items: {exc}") from exc


def get_previewed_finding_keys(db_path: str | Path, run_id: int) -> set[tuple[str, str, str]]:
    """Return (run ID, date, metric) identities already included in previews."""
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise ValueError("run_id must be a positive integer.")
    initialize_database(db_path)
    try:
        with _connect(db_path) as connection:
            rows = connection.execute(
                """SELECT analysis_run_id, anomaly_date, metric
                   FROM alert_preview_items WHERE analysis_run_id = ?""",
                (run_id,),
            ).fetchall()
            return {(str(row["analysis_run_id"]), row["anomaly_date"], row["metric"]) for row in rows}
    except (OSError, sqlite3.Error) as exc:
        raise StorageError(f"Could not retrieve preview history: {exc}") from exc
