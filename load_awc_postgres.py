import argparse
import io
import os
from pathlib import Path

import pandas as pd

from awc_pipeline_utils import resolve_folder
from load_awc_warehouse import alerts_frame, anomaly_frame, monthly_snapshot_frame, risk_frame

# Columns declared DATE in warehouse_schema_postgres.sql - pandas Timestamps are
# formatted explicitly rather than left to COPY's date parser to guess at.
DATE_COLUMNS = {
    "fct_awc_monthly_snapshot": ["period"],
    "fct_awc_anomaly_flags": ["period"],
    "fct_awc_risk_snapshot": ["period"],
}

# Columns declared INTEGER (some nullable) in warehouse_schema_postgres.sql. Any
# column that is None for at least one row (e.g. a centre's first-ever period
# has no previous_risk_flag_count) gets upcast to float64 by pandas, so it
# would otherwise serialize as "3.0" - invalid input for an INTEGER column.
# Int64 (pandas' nullable integer dtype) keeps whole numbers whole and NaN as
# a genuinely empty field.
INTEGER_COLUMNS = {
    "fct_awc_risk_snapshot": ["risk_flag_count"],
    "mart_awc_alerts_latest": ["risk_flag_count", "previous_risk_flag_count", "recent_anomaly_count"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load AWC curated outputs into PostgreSQL.")
    parser.add_argument("--folder", default=None, help="Folder containing curated AWC outputs.")
    parser.add_argument("--host", default=None, help="PostgreSQL host. Overrides DATABASE_URL if set together with --database/--user/--password.")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port.")
    parser.add_argument("--database", default=None, help="PostgreSQL database name.")
    parser.add_argument("--user", default=None, help="PostgreSQL user.")
    parser.add_argument("--password", default=None, help="PostgreSQL password.")
    parser.add_argument("--schema", default="public", help="Target PostgreSQL schema.")
    parser.add_argument(
        "--create-tables-sql",
        default="warehouse_schema_postgres.sql",
        help="Name or path of the PostgreSQL DDL file.",
    )
    parser.add_argument(
        "--views-file",
        default="analytics_views_postgres.sql",
        help="Name or path of the SQL views file to apply after table load.",
    )
    return parser.parse_args()


def resolve_connection_string(args: argparse.Namespace) -> str:
    """CLI connection args, if all four are supplied, override the environment.
    Otherwise fall back to DATABASE_URL (e.g. a Neon connection string)."""
    if args.host and args.database and args.user and args.password:
        return f"host={args.host} port={args.port} dbname={args.database} user={args.user} password={args.password}"

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "No PostgreSQL connection info available. Either pass "
            "--host/--database/--user/--password together, or set the "
            "DATABASE_URL environment variable."
        )
    return database_url


def resolve_output_path(folder: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


def resolve_script_relative_path(value: str) -> Path:
    """DDL/view SQL files ship next to the scripts, not per-run curated data,
    so their defaults resolve relative to this file's directory rather than
    --folder (which may point at a data-only folder like synthetic_data/)."""
    path = Path(value)
    return path if path.is_absolute() else Path(__file__).resolve().parent / path


def load_parquet_frames(folder: Path) -> dict[str, pd.DataFrame]:
    files = {
        "snapshot": folder / "AWC_HARMONIZED_MERGED.parquet",
        "anomaly": folder / "AWC_ANOMALY_FLAGS.parquet",
        "risk": folder / "AWC_RISK_FLAGS_LATEST.parquet",
        "alerts": folder / "AWC_ALERTS_LATEST.parquet",
    }
    missing = [str(path) for path in files.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Required curated Parquet files are missing: " + ", ".join(missing))

    return {
        "fct_awc_monthly_snapshot": monthly_snapshot_frame(pd.read_parquet(files["snapshot"])),
        "fct_awc_anomaly_flags": anomaly_frame(pd.read_parquet(files["anomaly"])),
        "fct_awc_risk_snapshot": risk_frame(pd.read_parquet(files["risk"])),
        "mart_awc_alerts_latest": alerts_frame(pd.read_parquet(files["alerts"])),
    }


def prepare_for_copy(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Coerce dtypes that pandas' default to_csv output would round-trip
    incorrectly through Postgres COPY (dates left as datetime, nullable
    integers upcast to float64)."""
    df = df.copy()
    for col in DATE_COLUMNS.get(table_name, []):
        df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")
    for col in INTEGER_COLUMNS.get(table_name, []):
        df[col] = df[col].astype("Int64")
    return df


def copy_dataframe(cur, schema: str, table_name: str, df: pd.DataFrame) -> None:
    df = prepare_for_copy(table_name, df)
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False)
    buffer.seek(0)
    columns = ", ".join(df.columns)
    cur.copy_expert(
        f"COPY {schema}.{table_name} ({columns}) FROM STDIN WITH (FORMAT CSV)",
        buffer,
    )


def main() -> None:
    args = parse_args()
    folder = resolve_folder(args.folder)
    ddl_file = resolve_script_relative_path(args.create_tables_sql)
    views_file = resolve_script_relative_path(args.views_file)

    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2 is required to load into PostgreSQL. Install it with `pip install psycopg2-binary`.") from exc

    frames = load_parquet_frames(folder)
    dsn = resolve_connection_string(args)

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            if ddl_file.exists():
                ddl_sql = ddl_file.read_text(encoding="utf-8").replace("__SCHEMA__", args.schema)
                cur.execute(ddl_sql)

            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {args.schema};")
            for table_name in frames:
                cur.execute(f"TRUNCATE TABLE {args.schema}.{table_name};")

            for table_name, df in frames.items():
                copy_dataframe(cur, args.schema, table_name, df)

            if views_file.exists():
                cur.execute(views_file.read_text(encoding="utf-8"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("PostgreSQL warehouse load completed.")
    for table_name, df in frames.items():
        print(f"{table_name}: {len(df)}")


if __name__ == "__main__":
    main()
