# AI Data Anomaly Agent

A local-first portfolio project for checking daily business metrics, finding unusual movements, and explaining the signals in plain English. It demonstrates practical data engineering patterns with Python, pandas, SQLite, deterministic anomaly rules, and a Streamlit dashboard. It does not claim an anomaly has a particular cause.

## 🚀 Live Demo

**Try the application:** [Launch AI Data Anomaly Agent](https://ai-data-anomaly-agent.streamlit.app/)

## 📊 Datasets

Use the following datasets to test the application:

- [Dataset 1 — Download/View on Google Drive](https://drive.google.com/file/d/1Rf2z4xGFZ7a5oSI3QRf-I6Fd5fDJhvr9/view?usp=sharing)
- [Dataset 2 — Download/View on Google Drive](https://drive.google.com/file/d/1UTUC36G6FBuyGXs60pP-GXd89GxqvJb3/view?usp=sharing)
- [Built-in sample dataset — daily_business_metrics.csv](data/sample/daily_business_metrics.csv)

### How to use the datasets

1. Open the [live application](https://ai-data-anomaly-agent.streamlit.app/).
2. Open a dataset link above and download the file to your computer.
3. Upload the downloaded CSV or Excel file using the dashboard's file uploader.
4. Review the validation report, detected anomalies, severity levels, explanations, and analysis history.

**Note:** The application expects the required business-metric columns described below. If either external dataset uses different column names or formats, adjust it to match the required schema before uploading.

### How to try the demo

1. Open the [live application](https://ai-data-anomaly-agent.streamlit.app/).
2. Download the sample CSV from this repository.
3. Upload the CSV using the dashboard's file uploader.
4. Review the validation report, detected anomalies, severity levels, and explanations.
5. Explore the analysis history and alert preview.

The dataset contains synthetic business metrics for demonstration purposes. Anomaly findings are rule-based review signals, not proof of a business problem or its cause.

## Business problem

Daily revenue, orders, conversion rate, traffic, costs, and refunds can shift unexpectedly. This application helps a reviewer spot data-quality problems and changes that may deserve attention. It keeps ingestion, validation, baseline calculation, anomaly detection, explanation, persistence, and presentation as separate steps so the analysis can be inspected and tested.

## Features

- Load CSV and `.xlsx` workbooks without silently dropping source rows.
- Validate the expected schema, missing values, dates, duplicate dates, numeric values, non-negative metrics, integer counts, and conversion-rate bounds.
- Keep invalid rows and source-row validation details visible; exclude invalid rows from metric calculations.
- Compare each valid day with a baseline made only from earlier valid observations.
- Detect positive and negative movements in six metrics with configurable thresholds and severity.
- Create deterministic business-friendly explanations and unsent plain-text alert previews.
- Store run metadata, validation details, findings, and preview history in local SQLite without storing uploaded file contents or ordinary source rows.
- Explore trends, KPI values, findings, filters, and recent analysis history in Streamlit.

## Technology

Python 3.11 or later, pandas, openpyxl, SQLite (`sqlite3`, included with Python), Streamlit, and pytest. No SQLAlchemy, cloud service, paid API, LLM, or email-delivery package is used.

## Architecture and data flow

```text
CSV / XLSX upload
       |
       v
src/ingest.py -> pandas DataFrame
       |
       v
src/validate.py -> issue report + source row numbers
       |
       v
src/metrics.py -> prior-only baselines + daily/rolling metrics
       |
       v
src/detect.py -> deterministic findings + skipped comparisons
       |
       +--> src/explain.py -> cautious explanations
       +--> src/alerts.py -> plain-text preview (never sends email)
       +--> src/storage.py -> local SQLite analysis and preview history
       |
       v
app.py -> Streamlit dashboard
```

The main logic can be used without the dashboard by importing its Python modules. `src/dashboard.py` contains a small testable helper for filtering dashboard findings.

## Input data

The required columns are `date`, `revenue`, `orders`, `conversion_rate`, `traffic`, `cost`, and `refunds`. Conversion rate is a fraction from `0` to `1` (`0.05` means 5%). Revenue, orders, traffic, cost, and refunds must be non-negative. Orders and traffic must be whole numbers. Dates must be parseable and unique by calendar day. For timestamp values with time-zone offsets, the date as written in the source is retained; numeric date values are rejected rather than interpreted as epoch nanoseconds.

The included `data/sample/daily_business_metrics.csv` is synthetic and has 30 daily rows. With the default detection settings, it validates successfully and currently produces 11 rule-based anomaly findings, including several refund movements. This is an example run, not a measure of accuracy or business impact.

## Install (Windows PowerShell)

Open PowerShell in this project folder and create an isolated environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If environment activation is blocked, use the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run the dashboard

```powershell
python -m streamlit run app.py
```

Upload a CSV or `.xlsx` workbook. Start with the included synthetic file. The dashboard reports validation issues, previews invalid rows, displays latest-day KPIs and revenue/orders trends, and lists detected findings. Use the severity and metric filters to narrow the displayed findings. The alert preview button creates a subject and plain-text draft; it does not send email. Previewed findings are recorded by analysis run, date, and metric so repeating a preview for that run does not repeat them.

The dashboard shows a generic upload error rather than echoing local paths or low-level parser content. It writes a temporary copy to read an upload and removes it afterwards.

## Run individual steps

Print a validation report for the included dataset:

```powershell
python -c "from src.ingest import load_business_data; from src.validate import validate_data; import json; data = load_business_data('data/sample/daily_business_metrics.csv'); print(json.dumps(validate_data(data), indent=2))"
```

Print the deterministic detection report:

```powershell
python -c "from src.ingest import load_business_data; from src.detect import detect_anomalies; import json; data = load_business_data('data/sample/daily_business_metrics.csv'); print(json.dumps(detect_anomalies(data), indent=2))"
```

Excel uses the first worksheet by default. To load another worksheet in Python, pass `sheet_name`, for example `load_business_data('sales.xlsx', sheet_name='Daily')`. Legacy `.xls` files are not supported; save them as `.xlsx` first.

## Detection method and configuration

`src/dates.py` provides shared daily date normalization so validation and metrics agree, including on mixed timezone offsets. For each date and metric, `src/metrics.py` calculates daily change, relative daily percentage change, a trailing rolling average, and a historical baseline. The baseline uses the preceding valid observations only; the current date and future dates are never included. Invalid rows and duplicate-date rows are excluded from baseline calculations but remain available in the validation report.

`src/detect.py` flags absolute relative percentage changes that meet the configured threshold. Defaults are:

| Metric | Threshold |
| --- | ---: |
| Revenue | 30% |
| Orders | 30% |
| Conversion rate | 25% |
| Traffic | 30% |
| Cost | 35% |
| Refunds | 50% |

Both increases and decreases are considered. A change at least 1.5 times its metric threshold is high severity; at least 2 times the threshold is critical; otherwise it is medium. The default requires seven prior valid observations. A zero baseline is skipped because relative change is undefined. Configure thresholds and history in the dashboard sidebar or with `detect_anomalies(data, thresholds_pct={"revenue": 20.0}, min_history=5, baseline_window=7)` in Python. `min_history` must not exceed the baseline window.

These simple rules can produce false positives, especially for seasonal, sparse, or volatile data. They do not quantify statistical confidence, account for holidays, or prove a business cause. Review source quality and business context before acting.

## SQLite and data privacy

The default database is `data/anomaly_agent.sqlite3`, created locally on first dashboard run. To choose another path for the current PowerShell session:

```powershell
$env:AI_ANOMALY_AGENT_DB_PATH = Join-Path $PWD 'data\local-analysis.sqlite3'
python -m streamlit run app.py
```

SQLite stores a source content hash, file type, byte size and row count; run timestamp, configuration and validation details; anomaly findings; and which findings have appeared in local previews. It does **not** store the uploaded file, filename, full path, or ordinary daily metric rows. The source hash is only a short reference in the dashboard. Databases and `.env` are ignored by Git. Do not place credentials or personal data in the repository or sample data.

## Tests

Run all tests from the project folder:

```powershell
python -m pytest -v
```

Tests cover CSV/Excel ingestion, empty and malformed uploads, validation including mixed time-zone dates, metric baselines and future-data leakage, anomaly edge cases, SQLite initialization/persistence/idempotency/errors, alert formatting and run-scoped duplicate protection, dashboard filtering, and Streamlit smoke cases. The local portfolio-polish verification completed with **43 passing tests**; run the command above to verify your checkout.

## Known limitations and roadmap

- The application analyzes daily, single-source tabular data; it does not infer missing business context or seasonal patterns.
- Severity is a deterministic threshold category, not a probability or impact estimate.
- SQLite is intended for local demonstration and a single-user portfolio workflow, not concurrent production workloads.
- Alert messages are previews only; there is no configured email delivery.
- Optional future work: richer synthetic scenarios, exportable reports, and a separately reviewed AWS architecture for object storage, managed SQL, scheduled processing, and alerting. Any future cloud work would require explicit approval of permissions, regional costs, and cleanup steps before resource changes.

## Repository map

```text
app.py                         Streamlit dashboard
src/ingest.py                  CSV/XLSX loading
src/dates.py                   Consistent daily-date normalization
src/validate.py                Schema and row validation
src/metrics.py                 Daily metrics and historical baselines
src/detect.py                  Deterministic anomaly detection
src/explain.py                 Business-friendly explanations
src/storage.py                 Local SQLite persistence
src/alerts.py                  Unsent plain-text alert previews
src/dashboard.py               Testable dashboard presentation helpers
data/sample/                   Synthetic example data
tests/                         Automated tests
requirements.txt               Runtime and test dependencies
```
