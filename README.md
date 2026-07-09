# AWC Operations Dashboard

Local monthly monitoring pipeline and Streamlit dashboard for **AWC operational efficiency, coverage, and nutrition reporting**.

This project takes raw monthly AWC CSV files, harmonizes schema differences across reporting periods, loads the harmonized data into a local SQLite warehouse, and serves a dashboard for operational review.

## What This Project Does

The workflow turns recurring monthly reporting files into a reusable local monitoring system.

It handles:

- schema harmonization across old and new source formats
- anomaly, risk, and alert scoring against the harmonized data
- local warehouse loading with SQLite
- dashboard exploration through Streamlit
- rolled-up reporting metrics built from numerators and denominators

The result is a structured dashboard workflow over data that would otherwise remain scattered across monthly CSV extracts.

## Why It Exists

Operational reporting files often change schema over time and are difficult to compare consistently month to month.

This project exists to create a stable local reporting layer by:

- standardizing multiple source schemas
- preserving source-faithful metrics
- storing harmonized outputs in a local warehouse
- exposing monitoring views through a dashboard

It is especially useful where the reporting workflow depends on recurring monthly extracts rather than a central transactional database.

## Architecture

Monthly raw CSV files -> harmonization -> anomaly/risk/alert scoring -> SQLite warehouse -> Streamlit dashboard

### Pipeline steps

1. Detect and validate source schema transitions
2. Harmonize old and new monthly file formats into a common structure
3. Score anomaly flags, risk snapshots, and latest alerts against the harmonized data
4. Load the harmonized (and scored) output into SQLite
5. Serve a Streamlit dashboard over the warehouse

## What the Dashboard Covers

The dashboard is aligned to the source reporting structure and supports analysis across:

- geography and identity
  - `STATE NAME`
  - `DISTRICT NAME`
  - `PROJECT NAME`
  - `SECTOR NAME`
  - `AWC CODE`
  - `AWC NAME`

- coverage and measurement
  - `TOTAL ACTIVE CHILDREN (0-6 YEARS)`
  - `TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)`
  - `MEASURING EFFICIENCY (0-6 YEARS) (%)`
  - `TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)`

- nutrition counts
  - `SUW`
  - `MUW`
  - `SAM`
  - `MAM`
  - `SEVERELY STUNTED`
  - `MODERATELY STUNTED`

- reported or normalized percentages
  - `SUW %`
  - `SAM %`
  - `MAM %`
  - derived `stunting_rate_pct`

## File Naming Pattern

Raw monthly files must match one of these patterns:

- `AWC_Operational_Efficiency_*.csv`
- `AWC_OPERATIONAL_EFFICIENCY_*.csv`

Safest convention:

- `AWC_Operational_Efficiency_MM_YYYY_Month.csv`

Example:

- `AWC_Operational_Efficiency_05_2026_May.csv`

## Supported Source Schemas

Older percent-based schema includes fields like:

- `SUW %`
- `SAM %`
- `MAM %`

Newer count-based schema includes fields like:

- `SUW`
- `MUW`
- `SEVERELY STUNTED`
- `MODERATELY STUNTED`
- `SAM`
- `MAM`

The harmonization step normalizes both into a common schema and preserves `SOURCE_FILE`.

## Rolled-up Percentage Logic

Dashboard summary percentages are rolled up from numerators and denominators rather than averaged from center-level percentages.

- Measuring Efficiency `%`
  - `sum(measured 0-6) / sum(active 0-6) * 100`

- SUW `%`
  - `sum(SUW) / sum(measured 0-6) * 100`
  - for older percent files, `SUW` is estimated from `SUW % * measured 0-6`

- SAM `%`
  - `sum(SAM) / sum(measured 0-5) * 100`
  - for older percent files, `SAM` is estimated from `SAM % * measured 0-5`

- MAM `%`
  - `sum(MAM) / sum(measured 0-5) * 100`
  - for older percent files, `MAM` is estimated from `MAM % * measured 0-5`

- Stunting Rate `%`
  - `sum(SEVERELY STUNTED + MODERATELY STUNTED) / sum(measured 0-6) * 100`

## Anomaly, Risk, and Alerts

`anomaly_risk_flags.py` scores the harmonized dataset (`AWC_HARMONIZED_MERGED.parquet`) into three tables, using the thresholds in `awc_pipeline_config.json`. It runs after `harmonize_merge_awc.py` and before `load_awc_warehouse.py`.

There are two independent scoring layers:

- **Risk** is an absolute, single-period read: does this period's value cross a static level (`risk_thresholds`)? A centre is flagged `CRITICAL_MEASUREMENT_GAP` / `HIGH_MEASUREMENT_GAP` on measuring efficiency, and `HIGH_SUW_RATE` / `HIGH_SAM_RATE` / `HIGH_MAM_RATE` / `HIGH_STUNTING_RATE` on the four rate metrics. `risk_level` is `HIGH` at 3+ flags, `MEDIUM` at 1-2, else `LOW` (`risk_level_rules`). Feeds `fct_awc_risk_snapshot`.
- **Anomaly** is a relative, movement read: did this period's value move too far from the previous period, or from its own recent rolling baseline (`anomaly_thresholds`)? Flags like `PERIOD_OVER_PERIOD_DROP` and `BASELINE_DEVIATION_RISE` can combine on the same row. Separately, hard data-quality invariants are checked every period regardless of history: measured children exceeding active children, measuring efficiency outside 0-100%, and negative nutrition counts. Feeds `fct_awc_anomaly_flags`.

`mart_awc_alerts_latest` combines both, one row per AWC for the latest period only, comparing current vs. previous period. `alert_scenario` is decided in priority order:

| scenario | condition |
|---|---|
| `NEW_HIGH_RISK` | current period is `HIGH` and the previous period wasn't (including a centre's first-ever period) |
| `NEW_MONITORING` | a centre's first-ever period, and it isn't `HIGH` |
| `RISK_ESCALATED` | risk level moved up a tier (but didn't newly become `HIGH`) |
| `RISK_IMPROVED` | risk level moved down a tier |
| `PERSISTENT_HIGH_RISK` | stayed `HIGH` both periods |
| `ANOMALY_PRESSURE` | risk level unchanged, but recent anomaly-flag count meets `alerts.high_recent_anomaly_count` within the last `alerts.recent_period_window` periods |
| `STABLE` | none of the above |

This decision table extends `dashboard_spec.md`'s two named examples (`NEW_HIGH_RISK`, `RISK_ESCALATED`) into a fully-specified enumeration; see `evaluate_risk_flags`, `compute_risk_level`, `evaluate_anomaly_flag`, and `compute_alert_scenario` in `awc_pipeline_utils.py` for the exact rules.

### Validated against a known-anomaly synthetic dataset

`scripts/validate_anomaly_detection.py` cross-checks `fct_awc_anomaly_flags` against the synthetic generator's ground-truth injection log (`synthetic_anomaly_log.csv`) and writes a recall report. Run against the seed-42 synthetic dataset:

```powershell
python .\scripts\validate_anomaly_detection.py --folder .\synthetic_data
```

See `synthetic_data\ANOMALY_DETECTION_VALIDATION.md` for the full breakdown. Headline result: 100% recall on the three anomalies with a dedicated data-quality check (measured > active, efficiency out of range, negative counts); ~93% recall on injected rate spikes via the threshold/drift flags; and an honestly-reported miss on pure population-count spikes, which the current metric set doesn't track (documented in the report, not hidden). The report also separates flags that trace back to an injected anomaly from flags that are ordinary threshold-crossings on non-corrupted synthetic data - the latter are expected detector output, not false positives.

### Tests

```powershell
python -m pytest tests/
```

`tests/` covers flag-rule boundary values (e.g. 79.9 vs 80.0 measuring efficiency), risk-level aggregation (0/1/3 flags), `alert_scenario` transitions, and one end-to-end test running a tiny in-memory fixture through `compute_anomaly_flags` / `compute_risk_snapshot` / `compute_alerts_latest`. No real or synthetic data files are required to run it.

## Setup

Install dependencies:

```powershell
C:\Python314\python.exe -m pip install -r .\requirements.txt
```

## Monthly Refresh Workflow

1. Add the new raw monthly CSV file into the project folder.
2. Run the refresh script:

```powershell
.\refresh_awc_dashboard.ps1
```

This runs:

- `schema_transition_check.py`
- `harmonize_merge_awc.py`
- `anomaly_risk_flags.py`
- `load_awc_warehouse.py`

3. Start the Streamlit dashboard:

```powershell
.\start_awc_dashboard_streamlit.ps1
```

The dashboard runs at:

- `http://127.0.0.1:8501`

## Main Files

- `harmonize_merge_awc.py`
  - normalizes monthly CSV files into a harmonized merged dataset
- `anomaly_risk_flags.py`
  - scores the harmonized dataset into anomaly flags, risk snapshots, and latest alerts
- `load_awc_warehouse.py`
  - loads the harmonized Parquet output (and anomaly/risk/alerts output, if present) into `awc_warehouse.sqlite`
- `awc_dashboard_streamlit.py`
  - Streamlit dashboard app
- `refresh_awc_dashboard.ps1`
  - one-command monthly refresh
- `start_awc_dashboard_streamlit.ps1`
  - launches the dashboard
- `scripts/generate_synthetic_data.py`
  - fictional demo dataset generator
- `scripts/validate_anomaly_detection.py`
  - validates anomaly flags against the synthetic ground-truth log
- `tests/`
  - pytest suite for the anomaly/risk/alert scoring logic
- `requirements.txt`
  - pinned Python dependencies

## Outputs

- `AWC_HARMONIZED_MERGED.csv` / `.parquet`
- `AWC_ANOMALY_FLAGS.csv` / `.parquet`
- `AWC_RISK_FLAGS_LATEST.csv` / `.parquet`
- `AWC_ALERTS_LATEST.csv` / `.parquet`
- `awc_warehouse.sqlite`
- `harmonize_run_summary.json`
- `anomaly_risk_flags_run_summary.json`
- `warehouse_load_summary.json`
- `schema_transition_summary.json`

## Synthetic Demo Dataset

`scripts/generate_synthetic_data.py` generates a fully fictional ~2,000-centre,
12-month monthly dataset matching this repo's real export schema exactly (same
columns, same PERCENT/COUNT schema transition, same filename quirks), with
deliberate anomalies injected (a row-count drop, a renamed-column schema
drift, and out-of-range row values) so the harmonizer's drift checks and the
dashboard's trend charts have something to visibly catch.

```powershell
python .\scripts\generate_synthetic_data.py
```

Output is written to `synthetic_data/` by default and includes its own
`README.md` documenting exactly what's synthetic and where each injected
anomaly lives. **All data in that folder is fictional** - no real AWC
centres, districts, or children are represented.

## Project Scope

Current scope:

- monthly source harmonization
- anomaly flags, risk snapshots, and latest alerts (`anomaly_risk_flags.py`, validated against a synthetic ground-truth log - see above)
- SQLite warehouse loading
- dashboard reporting over recurring monthly extracts
- source-faithful counts, coverage, and rolled-up percentages

Not yet in scope:

- the anomaly/risk/alerts layer is not surfaced in `awc_dashboard_streamlit.py` itself (the dashboard still reads only `fct_awc_monthly_snapshot`); the tables are populated in the warehouse and ready for a dashboard page, per `dashboard_spec.md`
- PostgreSQL and SQL Server loaders (`load_awc_postgres.py`, `load_awc_sqlserver.py`) are wired to the restored `anomaly_frame` / `risk_frame` / `alerts_frame` functions but are untested against a live server in this environment
