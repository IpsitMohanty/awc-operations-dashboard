import argparse
from pathlib import Path

import pandas as pd

from awc_pipeline_utils import resolve_folder
from load_awc_warehouse import alerts_frame, anomaly_frame, monthly_snapshot_frame, risk_frame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load AWC curated outputs into SQL Server.")
    parser.add_argument("--folder", default=None, help="Folder containing curated AWC outputs.")
    parser.add_argument("--server", required=True, help="SQL Server host or host\\instance.")
    parser.add_argument("--database", required=True, help="SQL Server database name.")
    parser.add_argument("--user", required=True, help="SQL Server user.")
    parser.add_argument("--password", required=True, help="SQL Server password.")
    parser.add_argument("--schema", default="dbo", help="Target SQL Server schema.")
    parser.add_argument(
        "--driver",
        default="ODBC Driver 17 for SQL Server",
        help="ODBC driver name.",
    )
    parser.add_argument(
        "--create-tables-sql",
        default="warehouse_schema_sqlserver.sql",
        help="Name or path of the SQL Server DDL file.",
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
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("pyodbc is required to load into SQL Server. Install it with `pip install pyodbc`.") from exc

    frames = load_parquet_frames(folder)
    conn_str = (
        f"DRIVER={{{args.driver}}};SERVER={args.server};DATABASE={args.database};"
        f"UID={args.user};PWD={args.password};TrustServerCertificate=yes;"
    )

    with pyodbc.connect(conn_str) as conn:
        cur = conn.cursor()
        if ddl_file.exists():
            ddl_sql = ddl_file.read_text(encoding="utf-8").replace("__SCHEMA__", args.schema)
            for statement in [s.strip() for s in ddl_sql.split(";") if s.strip()]:
                cur.execute(statement)

        for table_name in frames:
            cur.execute(f"DELETE FROM {args.schema}.{table_name}")

        for table_name, df in frames.items():
            columns = list(df.columns)
            placeholders = ",".join(["?"] * len(columns))
            column_list = ",".join(columns)
            insert_sql = f"INSERT INTO {args.schema}.{table_name} ({column_list}) VALUES ({placeholders})"
            cur.fast_executemany = True
            cur.executemany(insert_sql, list(df.itertuples(index=False, name=None)))

        conn.commit()

    print("SQL Server warehouse load completed.")
    for table_name, df in frames.items():
        print(f"{table_name}: {len(df)}")


if __name__ == "__main__":
    main()
