import argparse
from pathlib import Path

import pandas as pd

from awc_pipeline_utils import (
    STANDARD_COLUMNS,
    classify_schema,
    find_header_line_index,
    get_source_files,
    parse_period_from_name,
    resolve_folder,
    safe_float,
    utc_now_iso,
    validate_periods,
    write_run_summary,
)


def read_and_normalize(path: Path) -> pd.DataFrame:
    header_i = find_header_line_index(path)

    df = pd.read_csv(
        path,
        skiprows=header_i,
        dtype=str,
        engine="python",
        keep_default_na=False,
    )

    df.columns = [col.strip().upper() for col in df.columns]

    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    try:
        df["SUW"] = df["SUW"].replace("", None)
        df["SUW"] = df.apply(
            lambda x: (
                str(
                    round(
                        safe_float(x["SUW %"]) / 100
                        * safe_float(x["TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)"])
                    )
                )
                if x["SUW"] in ["", None]
                and safe_float(x["SUW %"]) is not None
                and safe_float(x["TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)"]) is not None
                else x["SUW"]
            ),
            axis=1,
        )
    except Exception:
        pass

    df["SOURCE_FILE"] = path.name
    return df[STANDARD_COLUMNS]


def build_file_summary(path: Path) -> dict:
    header_i = find_header_line_index(path)
    header_df = pd.read_csv(
        path,
        skiprows=header_i,
        nrows=0,
        dtype=str,
        engine="python",
    )
    headers = [str(col).strip().upper() for col in header_df.columns]
    data_df = pd.read_csv(
        path,
        skiprows=header_i,
        dtype=str,
        engine="python",
        keep_default_na=False,
    )
    period = parse_period_from_name(path.name)
    return {
        "file": path.name,
        "period": period.label,
        "schema_type": classify_schema(headers),
        "column_count": len(headers),
        "row_count": len(data_df),
    }


def validate_file_summaries(file_summaries: list[dict]) -> None:
    unknown = [row["file"] for row in file_summaries if row["schema_type"] == "UNKNOWN"]
    if unknown:
        raise ValueError(f"Unknown source schema detected: {', '.join(unknown)}")

    row_counts = pd.Series([row["row_count"] for row in file_summaries], dtype="int64")
    if row_counts.empty:
        raise ValueError("No source rows found.")

    median_count = float(row_counts.median())
    tolerance = max(5, int(median_count * 0.01))
    outliers = [
        row
        for row in file_summaries
        if abs(row["row_count"] - median_count) > tolerance
    ]
    if outliers:
        details = ", ".join(f"{row['file']} ({row['row_count']} rows)" for row in outliers)
        raise ValueError(f"Abnormal row-count drift detected: {details}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize and merge monthly AWC files.")
    parser.add_argument("--folder", default=None, help="Folder containing monthly AWC CSV files.")
    parser.add_argument(
        "--output-file",
        default="AWC_HARMONIZED_MERGED.csv",
        help="Name or path of the merged output CSV.",
    )
    parser.add_argument(
        "--summary-file",
        default="harmonize_run_summary.json",
        help="Name or path of the JSON run summary.",
    )
    parser.add_argument(
        "--parquet-output-file",
        default="AWC_HARMONIZED_MERGED.parquet",
        help="Name or path of the merged Parquet output.",
    )
    return parser.parse_args()


def resolve_output_path(folder: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


def main() -> None:
    args = parse_args()
    folder = resolve_folder(args.folder)
    output_file = resolve_output_path(folder, args.output_file)
    summary_file = resolve_output_path(folder, args.summary_file)
    parquet_output_file = resolve_output_path(folder, args.parquet_output_file)

    source_files = get_source_files(folder, excluded_files={output_file.name})
    if not source_files:
        raise FileNotFoundError(f"No monthly AWC operational efficiency CSV files found in {folder}")

    validate_periods(source_files)
    file_summaries = [build_file_summary(path) for path in source_files]
    validate_file_summaries(file_summaries)

    all_dfs = []
    for file in source_files:
        print(f"Processing: {file.name}")
        all_dfs.append(read_and_normalize(file))

    merged_df = pd.concat(all_dfs, ignore_index=True)
    merged_df.to_csv(output_file, index=False)
    merged_df.to_parquet(parquet_output_file, index=False)

    schema_counts = (
        pd.Series([row["schema_type"] for row in file_summaries]).value_counts().sort_index().to_dict()
    )
    summary = {
        "pipeline": "harmonize_merge_awc",
        "run_timestamp_utc": utc_now_iso(),
        "folder": str(folder),
        "output_file": str(output_file),
        "parquet_output_file": str(parquet_output_file),
        "source_file_count": len(source_files),
        "source_rows_total": int(sum(row["row_count"] for row in file_summaries)),
        "merged_rows_total": int(len(merged_df)),
        "period_start": file_summaries[0]["period"],
        "period_end": file_summaries[-1]["period"],
        "schema_counts": schema_counts,
        "files": file_summaries,
    }
    write_run_summary(summary_file, summary)

    print(f"\nHarmonized file saved at: {output_file}")
    print(f"Harmonized parquet saved at: {parquet_output_file}")
    print(f"Total rows: {len(merged_df)}")
    print(f"Run summary saved at: {summary_file}")


if __name__ == "__main__":
    main()
