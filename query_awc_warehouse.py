import argparse
import sqlite3
from pathlib import Path

from awc_pipeline_utils import resolve_folder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a SQL query against the local AWC warehouse.")
    parser.add_argument("--folder", default=None, help="Folder containing the SQLite warehouse.")
    parser.add_argument(
        "--database-file",
        default="awc_warehouse.sqlite",
        help="Name or path of the SQLite warehouse file.",
    )
    parser.add_argument("--sql", required=True, help="SQL statement to execute.")
    parser.add_argument("--limit", type=int, default=20, help="Max rows to print.")
    return parser.parse_args()


def resolve_output_path(folder: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


def main() -> None:
    args = parse_args()
    folder = resolve_folder(args.folder)
    database_file = resolve_output_path(folder, args.database_file)

    with sqlite3.connect(database_file) as conn:
        cur = conn.execute(args.sql)
        cols = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchmany(args.limit) if cols else []

    if cols:
        print(" | ".join(cols))
        for row in rows:
            print(" | ".join("" if value is None else str(value) for value in row))
    else:
        print("Statement executed.")


if __name__ == "__main__":
    main()
