import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from awc_pipeline_utils import resolve_folder, utc_now_iso, write_run_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load AWC curated outputs into a local SQLite warehouse.")
    parser.add_argument("--folder", default=None, help="Folder containing curated AWC outputs.")
    parser.add_argument(
        "--database-file",
        default="awc_warehouse.sqlite",
        help="Name or path of the SQLite warehouse file.",
    )
    parser.add_argument(
        "--summary-file",
        default="warehouse_load_summary.json",
        help="Name or path of the warehouse load summary JSON.",
    )
    parser.add_argument(
        "--views-file",
        default="analytics_views.sql",
        help="Name or path of the SQL views file to apply after table load.",
    )
    return parser.parse_args()


def resolve_output_path(folder: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


def resolve_script_relative_path(value: str) -> Path:
    """The views SQL file ships next to the scripts, not per-run curated
    data, so its default resolves relative to this file's directory rather
    than --folder (which may point at a data-only folder like synthetic_data/)."""
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parent / path


def monthly_snapshot_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["period"] = pd.to_datetime(out["SOURCE_FILE"].map(_source_file_to_period))
    for col in [
        "TOTAL ACTIVE CHILDREN (0-6 YEARS)",
        "TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)",
        "MEASURING EFFICIENCY (0-6 YEARS) (%)",
        "TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)",
        "SUW",
        "MUW",
        "SEVERELY STUNTED",
        "MODERATELY STUNTED",
        "SAM",
        "MAM",
        "SUW %",
        "SAM %",
        "MAM %",
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    measured_06 = out["TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)"]
    measured_05 = out["TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)"]
    out["suw_rate_pct"] = out["SUW %"].where(out["SUW %"].notna(), (out["SUW"] / measured_06) * 100)
    out["sam_rate_pct"] = out["SAM %"].where(out["SAM %"].notna(), (out["SAM"] / measured_05) * 100)
    out["mam_rate_pct"] = out["MAM %"].where(out["MAM %"].notna(), (out["MAM"] / measured_05) * 100)
    out["stunting_rate_pct"] = (
        (out["SEVERELY STUNTED"].fillna(0) + out["MODERATELY STUNTED"].fillna(0)) / measured_06
    ) * 100
    return out.rename(
        columns={
            "STATE NAME": "state_name",
            "DISTRICT NAME": "district_name",
            "PROJECT NAME": "project_name",
            "SECTOR NAME": "sector_name",
            "AWC CODE": "awc_code",
            "AWC NAME": "awc_name",
            "SOURCE_FILE": "source_file",
            "TOTAL ACTIVE CHILDREN (0-6 YEARS)": "total_active_children_0_6_years",
            "TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)": "total_active_children_measured_0_6_years",
            "MEASURING EFFICIENCY (0-6 YEARS) (%)": "measuring_efficiency_0_6_years_pct",
            "TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)": "total_active_children_measured_0_5_years",
            "SUW": "suw_count",
            "MUW": "muw_count",
            "SEVERELY STUNTED": "severely_stunted_count",
            "MODERATELY STUNTED": "moderately_stunted_count",
            "SAM": "sam_count",
            "MAM": "mam_count",
        }
    )[
        [
            "awc_code",
            "period",
            "state_name",
            "district_name",
            "project_name",
            "sector_name",
            "awc_name",
            "source_file",
            "total_active_children_0_6_years",
            "total_active_children_measured_0_6_years",
            "measuring_efficiency_0_6_years_pct",
            "total_active_children_measured_0_5_years",
            "suw_count",
            "muw_count",
            "severely_stunted_count",
            "moderately_stunted_count",
            "sam_count",
            "mam_count",
            "suw_rate_pct",
            "sam_rate_pct",
            "mam_rate_pct",
            "stunting_rate_pct",
        ]
    ]


def _source_file_to_period(source_file: str) -> pd.Timestamp:
    from awc_pipeline_utils import parse_period_from_name

    period = parse_period_from_name(str(source_file))
    return pd.Timestamp(year=period.year, month=period.month, day=1)


ANOMALY_FLAG_COLUMNS = [
    "awc_code", "period", "metric_name", "state_name", "district_name", "project_name", "sector_name",
    "awc_name", "source_file", "current_value", "previous_value", "delta_value", "absolute_delta_value",
    "rolling_baseline_value", "baseline_gap_value", "threshold_value", "flag_reason",
]

RISK_SNAPSHOT_COLUMNS = [
    "awc_code", "period", "state_name", "district_name", "project_name", "sector_name", "awc_name",
    "source_file", "measuring_efficiency_0_6_years_pct", "suw_rate_pct", "sam_rate_pct", "mam_rate_pct",
    "stunting_rate_pct", "risk_flags", "risk_flag_count", "risk_level",
]

_ALERTS_METRIC_DELTA_FIELDS = [
    "total_active_children_0_6_years", "total_active_children_measured_0_6_years",
    "measuring_efficiency_0_6_years_pct", "total_active_children_measured_0_5_years",
    "suw_count", "muw_count", "severely_stunted_count", "moderately_stunted_count",
    "sam_count", "mam_count", "suw_rate_pct", "sam_rate_pct", "mam_rate_pct", "stunting_rate_pct",
]

ALERTS_LATEST_COLUMNS = (
    ["awc_code", "current_period", "previous_period", "state_name", "district_name", "project_name",
     "sector_name", "awc_name", "source_file"]
    + [
        column
        for field in _ALERTS_METRIC_DELTA_FIELDS
        for column in (field, f"previous_{field}", f"delta_{field}")
    ]
    + [
        "risk_level", "risk_flags", "risk_flag_count",
        "previous_risk_period", "previous_risk_level", "previous_risk_flags", "previous_risk_flag_count",
        "risk_direction", "recent_anomaly_count", "latest_anomaly_period", "recent_anomaly_metrics",
        "recent_flag_reasons", "alert_scenario",
    ]
)


def anomaly_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize an already-computed anomaly-flags frame (as written by
    anomaly_risk_flags.py) to the exact fct_awc_anomaly_flags column order/dtypes."""
    out = df.copy()
    out["period"] = pd.to_datetime(out["period"])
    return out[ANOMALY_FLAG_COLUMNS]


def risk_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize an already-computed risk-snapshot frame to the exact
    fct_awc_risk_snapshot column order/dtypes."""
    out = df.copy()
    out["period"] = pd.to_datetime(out["period"])
    return out[RISK_SNAPSHOT_COLUMNS]


def alerts_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize an already-computed latest-alerts frame to the exact
    mart_awc_alerts_latest column order (current_period/previous_period stay
    as YYYY-MM text labels, matching the VARCHAR(7) DDL)."""
    return df[ALERTS_LATEST_COLUMNS]


def load_table(conn: sqlite3.Connection, table_name: str, df: pd.DataFrame) -> int:
    df.to_sql(table_name, conn, if_exists="replace", index=False)
    return int(len(df))


def main() -> None:
    args = parse_args()
    folder = resolve_folder(args.folder)
    database_file = resolve_output_path(folder, args.database_file)
    summary_file = resolve_output_path(folder, args.summary_file)
    views_file = resolve_script_relative_path(args.views_file)

    snapshot_file = folder / "AWC_HARMONIZED_MERGED.parquet"
    if not snapshot_file.exists():
        raise FileNotFoundError(f"Required harmonized Parquet file is missing: {snapshot_file}")

    snapshot_df = monthly_snapshot_frame(pd.read_parquet(snapshot_file))

    optional_tables = {
        "fct_awc_anomaly_flags": (folder / "AWC_ANOMALY_FLAGS.parquet", anomaly_frame),
        "fct_awc_risk_snapshot": (folder / "AWC_RISK_FLAGS_LATEST.parquet", risk_frame),
        "mart_awc_alerts_latest": (folder / "AWC_ALERTS_LATEST.parquet", alerts_frame),
    }

    with sqlite3.connect(database_file) as conn:
        row_counts = {
            "fct_awc_monthly_snapshot": load_table(conn, "fct_awc_monthly_snapshot", snapshot_df),
        }
        for table_name, (parquet_file, shaper) in optional_tables.items():
            if parquet_file.exists():
                row_counts[table_name] = load_table(conn, table_name, shaper(pd.read_parquet(parquet_file)))
            else:
                print(f"Skipping {table_name}: {parquet_file.name} not found (run anomaly_risk_flags.py first).")
        if views_file.exists():
            conn.executescript(views_file.read_text(encoding="utf-8"))

    summary = {
        "pipeline": "load_awc_warehouse",
        "run_timestamp_utc": utc_now_iso(),
        "folder": str(folder),
        "database_file": str(database_file),
        "views_file": str(views_file),
        "snapshot_file": str(snapshot_file),
        "row_counts": row_counts,
    }
    write_run_summary(summary_file, summary)

    print(f"Warehouse loaded into: {database_file}")
    for table_name, row_count in row_counts.items():
        print(f"{table_name}: {row_count}")
    print(f"Warehouse load summary saved at: {summary_file}")


if __name__ == "__main__":
    main()
