import argparse
from pathlib import Path

import pandas as pd

from awc_pipeline_utils import resolve_folder
from load_awc_warehouse import alerts_frame, anomaly_frame, monthly_snapshot_frame, risk_frame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load AWC curated outputs into PostgreSQL.")
    parser.add_argument("--folder", default=None, help="Folder containing curated AWC outputs.")
    parser.add_argument("--host", required=True, help="PostgreSQL host.")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port.")
    parser.add_argument("--database", required=True, help="PostgreSQL database name.")
    parser.add_argument("--user", required=True, help="PostgreSQL user.")
    parser.add_argument("--password", required=True, help="PostgreSQL password.")
    parser.add_argument("--schema", default="public", help="Target PostgreSQL schema.")
    parser.add_argument(
        "--create-tables-sql",
        default="warehouse_schema_postgres.sql",
        help="Name or path of the PostgreSQL DDL file.",
    )
    return parser.parse_args()


def resolve_output_path(folder: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


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


def main() -> None:
    args = parse_args()
    folder = resolve_folder(args.folder)
    ddl_file = resolve_output_path(folder, args.create_tables_sql)

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required to load into PostgreSQL. Install it with `pip install psycopg[binary]`.") from exc

    frames = load_parquet_frames(folder)
    conn_str = (
        f"host={args.host} port={args.port} dbname={args.database} "
        f"user={args.user} password={args.password}"
    )

    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            if ddl_file.exists():
                ddl_sql = ddl_file.read_text(encoding="utf-8").replace("__SCHEMA__", args.schema)
                cur.execute(ddl_sql)

            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {args.schema};")
            for table_name in frames:
                cur.execute(f"TRUNCATE TABLE {args.schema}.{table_name};")

            for table_name, df in frames.items():
                columns = list(df.columns)
                quoted_cols = ", ".join(columns)
                with cur.copy(
                    f"COPY {args.schema}.{table_name} ({quoted_cols}) FROM STDIN WITH (FORMAT CSV)"
                ) as copy:
                    for row in df.itertuples(index=False, name=None):
                        copy.write_row(row)
        conn.commit()

    print("PostgreSQL warehouse load completed.")
    for table_name, df in frames.items():
        print(f"{table_name}: {len(df)}")


if __name__ == "__main__":
    main()
