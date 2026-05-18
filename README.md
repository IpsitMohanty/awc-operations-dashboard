# AWC Operations Dashboard

Local monthly monitoring pipeline and Streamlit dashboard for AWC operational efficiency and nutrition reporting.

## What This Project Does

This workflow takes raw monthly AWC CSV files, normalizes the older percent-based and newer count-based schemas into a single harmonized dataset, loads the harmonized output into a local SQLite warehouse, and serves a Streamlit dashboard over the warehouse.

The dashboard is intentionally aligned to the source reporting structure:

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

Older percent schema includes fields like:

- `SUW %`
- `SAM %`
- `MAM %`

Newer count schema includes fields like:

- `SUW`
- `MUW`
- `SEVERELY STUNTED`
- `MODERATELY STUNTED`
- `SAM`
- `MAM`

The harmonization step normalizes both into a common schema and preserves `SOURCE_FILE`.

## Rolled-up Percentage Logic

Dashboard summary percentages are rolled up from numerators and denominators. They are not simple averages of AWC percentages.

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
- `load_awc_warehouse.py`
  - loads the harmonized Parquet output into `awc_warehouse.sqlite`
- `awc_dashboard_streamlit.py`
  - Streamlit dashboard app
- `refresh_awc_dashboard.ps1`
  - one-command monthly refresh
- `start_awc_dashboard_streamlit.ps1`
  - launches the dashboard
- `requirements.txt`
  - pinned Python dependencies

## Outputs

- `AWC_HARMONIZED_MERGED.csv`
- `AWC_HARMONIZED_MERGED.parquet`
- `awc_warehouse.sqlite`
- `harmonize_run_summary.json`
- `warehouse_load_summary.json`
- `schema_transition_summary.json`

## Known Scope

Current production scope is focused on the source monitoring layer only:

- monthly source harmonization
- SQLite warehouse
- Streamlit dashboard
- source-faithful counts, coverage, and rolled-up percentages

It does not currently include the older anomaly, risk, or alert layers.
