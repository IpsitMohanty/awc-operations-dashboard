# AWC Operations Dashboard

Local monthly monitoring pipeline and Streamlit dashboard for **AWC operational efficiency, coverage, and nutrition reporting**.

This project takes raw monthly AWC CSV files, harmonizes schema differences across reporting periods, scores anomaly/risk/alert signals against the harmonized data, loads everything into a local SQLite warehouse, and serves a dashboard for operational review.

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

### Anomaly Surveillance (dashboard page)

`awc_dashboard_streamlit.py` has a fourth tab, **Anomaly Surveillance**, alongside Overview / Geography Trends / AWC Detail - a scoped-down implementation of `dashboard_spec.md`'s Page 6, built directly against the tables above (it doesn't require the aspirational `vw_awc_anomaly_pressure` / `vw_awc_risk_overview` / `vw_awc_priority_interventions` views, which aren't implemented):

- **KPI row**: AWCs shown, High Risk, New High Risk, Escalated - counted from the currently filtered `mart_awc_alerts_latest` rows.
- **Latest Alerts table**: `mart_awc_alerts_latest`, filterable by the sidebar's District and a new Alert Scenario dropdown.
- **Risk Level Distribution Over Time**: `fct_awc_risk_snapshot`, a stacked area chart of distinct-AWC counts per `LOW`/`MEDIUM`/`HIGH` per period, respecting the same State/District/Project/Sector/AWC filters as Geography Trends.
- **Per-Centre Anomaly History**: `fct_awc_anomaly_flags` filtered to the sidebar's AWC Code, showing `period`, `metric_name`, `current_value`, `previous_value`, `delta_value`, `baseline_gap_value`, `threshold_value`, and `flag_reason` - the same column set as `dashboard_spec.md`'s Page 4 anomaly history, plus `threshold_value` for context.

If `anomaly_risk_flags.py` has never been run against the current warehouse, this tab shows an explanatory message instead of erroring - the other three tabs are unaffected either way.

### Validated against a known-anomaly synthetic dataset

`scripts/validate_anomaly_detection.py` cross-checks `fct_awc_anomaly_flags` against the synthetic generator's ground-truth injection log (`synthetic_anomaly_log.csv`) and writes a recall report. Run against the seed-42 synthetic dataset:

```powershell
python .\scripts\validate_anomaly_detection.py --folder .\synthetic_data
```

See `synthetic_data\ANOMALY_DETECTION_VALIDATION.md` for the full breakdown. Headline result: 100% recall on the three anomalies with a dedicated data-quality check (measured > active, efficiency out of range, negative counts); ~89% recall on injected rate spikes via the threshold/drift flags; and an honestly-reported miss on pure population-count spikes, which the current metric set doesn't track (documented in the report, not hidden). The report also separates flags that trace back to an injected anomaly from flags that are ordinary threshold-crossings on non-corrupted synthetic data - the latter are expected detector output, not false positives.

The same report also cross-checks the distressed-centre cluster against the latest-period alerts mart: `NEW_HIGH_RISK` and `PERSISTENT_HIGH_RISK` trace almost entirely back to it (92% and 100% respectively, on seed 42), confirming the organic `HIGH`-risk signal is coming from the intended decline model and not from incidental population noise. It also flags a real, separate interaction worth knowing about: `RISK_ESCALATED` is dominated by an unrelated effect of the November schema-drift month (its silently-zeroed `moderately_stunted_count` deflates that month's risk levels for the *whole* population, not just distressed centres, so December's reversion reads as a mass escalation) - the report explains and quantifies this rather than letting the number look unexplained.

### Tests

```powershell
python -m pytest tests/
```

`tests/` covers flag-rule boundary values (e.g. 79.9 vs 80.0 measuring efficiency), risk-level aggregation (0/1/3 flags), `alert_scenario` transitions, and one end-to-end test running a tiny in-memory fixture through `compute_anomaly_flags` / `compute_risk_snapshot` / `compute_alerts_latest`. No real or synthetic data files are required to run it.

## Dashboard Backend

`awc_dashboard_streamlit.py` picks its backend at startup: if the `DATABASE_URL` environment variable is set, it queries Postgres (e.g. a Neon database) via `psycopg2`; otherwise it falls back to the local `awc_warehouse.sqlite`. Every page - including Anomaly Surveillance - works identically on both; SQL is written portably (no SQLite-only `strftime`/`substr`, dialect differences like `LIKE` vs `ILIKE` are chosen automatically) rather than branching per page.

The database connection is cached with `st.cache_resource` (a 15-minute TTL) and query results with `st.cache_data` (5 minutes), so a Neon compute that's scaled to zero only pays its cold-start cost once per cache window, not on every filter click - Streamlit reruns the whole script on every widget interaction. A dropped/expired connection triggers one automatic reconnect-and-retry.

To load the synthetic dataset into Postgres yourself: apply `warehouse_schema_postgres.sql` and `analytics_views_postgres.sql` (the latter uses `CREATE OR REPLACE VIEW`, since Postgres doesn't support SQLite's `CREATE VIEW IF NOT EXISTS`), then run `load_awc_postgres.py --folder synthetic_data` with `DATABASE_URL` set - it applies both files and loads all four tables via `COPY`.

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

- `schema_transition_check.py`
  - detects and reports PERCENT/COUNT schema transitions across monthly files
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
- `load_awc_postgres.py`
  - loads the curated Parquet output into Postgres (e.g. Neon); reads `DATABASE_URL` from the environment
- `analytics_views_postgres.sql`
  - Postgres-compatible `vw_awc_monthly_trends` (mirrors `analytics_views.sql`, which is SQLite-only syntax)
- `tests/`
  - pytest suite for the anomaly/risk/alert scoring logic and dashboard transform functions
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

~2.5% of centres are also assigned to a **distressed-centre cluster**: instead
of jittering around a flat baseline all year, these centres decline over the
12 months toward chronically low measuring efficiency and elevated SUW/SAM/
stunting rates, so `anomaly_risk_flags.py` finds organic `HIGH`-risk centres
(seed 42: 30 in the latest period) and a realistic spread of `NEW_HIGH_RISK`,
`RISK_ESCALATED`, and `PERSISTENT_HIGH_RISK` alert scenarios, instead of
relying on the independently-random baseline population to cross 3+ risk
thresholds by chance (see `synthetic_data/README.md` for the onset/severity
model, and `synthetic_data/synthetic_distressed_centres.csv` for which
centres).

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
- SQLite or Postgres (e.g. Neon) warehouse loading, selected automatically at dashboard startup via `DATABASE_URL`
- dashboard reporting over recurring monthly extracts, including an Anomaly Surveillance page over the anomaly/risk/alerts tables
- source-faithful counts, coverage, and rolled-up percentages

Not yet in scope:

- the Geography Drilldown, Priority Intervention Queue, and Trend Monitoring pages from `dashboard_spec.md` (`vw_awc_risk_overview`, `vw_awc_priority_interventions`, `vw_awc_anomaly_pressure` are not implemented as views); Anomaly Surveillance is built directly against the underlying tables instead
- the SQL Server loader (`load_awc_sqlserver.py`) is wired to the restored `anomaly_frame` / `risk_frame` / `alerts_frame` functions but is untested against a live server in this environment (the Postgres loader has been - see Dashboard Backend, above)
