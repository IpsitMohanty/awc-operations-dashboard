import argparse
from pathlib import Path

import pandas as pd

from awc_pipeline_utils import (
    classify_schema,
    find_header_line_index,
    get_source_files,
    parse_period_from_name,
    resolve_folder,
    utc_now_iso,
    validate_periods,
    write_run_summary,
)


def get_headers(path: Path) -> list[str]:
    header_i = find_header_line_index(path)
    df = pd.read_csv(
        path,
        skiprows=header_i,
        nrows=0,
        dtype=str,
        engine="python",
    )
    return [str(col).strip().upper() for col in df.columns]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect schema transitions across monthly AWC files.")
    parser.add_argument("--folder", default=None, help="Folder containing monthly AWC CSV files.")
    parser.add_argument(
        "--summary-file",
        default="schema_transition_summary.json",
        help="Name or path of the JSON summary output.",
    )
    return parser.parse_args()


def resolve_output_path(folder: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


def main() -> None:
    args = parse_args()
    folder = resolve_folder(args.folder)
    summary_file = resolve_output_path(folder, args.summary_file)

    source_files = get_source_files(folder, excluded_files={"AWC_HARMONIZED_MERGED.csv"})
    if not source_files:
        raise FileNotFoundError(f"No monthly AWC operational efficiency CSV files found in {folder}")

    validate_periods(source_files)

    results = []
    for file in source_files:
        headers = get_headers(file)
        period = parse_period_from_name(file.name)
        results.append(
            {
                "period": period.label,
                "file": file.name,
                "type": classify_schema(headers),
                "column_count": len(headers),
            }
        )

    df = pd.DataFrame(results).sort_values(["period", "file"]).reset_index(drop=True)
    df["prev_type"] = df["type"].shift(1)
    df["prev_period"] = df["period"].shift(1)

    transition = df[(df["prev_type"].notna()) & (df["type"] != df["prev_type"])].copy()
    unknown = df[df["type"] == "UNKNOWN"]
    if not unknown.empty:
        raise ValueError(
            "Unknown source schema detected: " + ", ".join(unknown["file"].astype(str).tolist())
        )

    print("\nFULL TIMELINE:")
    print(df[["period", "file", "type", "column_count", "prev_type"]].to_string(index=False))

    print("\nTRANSITION POINTS:")
    if transition.empty:
        print("No schema transitions detected.")
    else:
        print(
            transition[
                ["prev_period", "period", "file", "prev_type", "type"]
            ].to_string(index=False)
        )

    summary = {
        "pipeline": "schema_transition_check",
        "run_timestamp_utc": utc_now_iso(),
        "folder": str(folder),
        "source_file_count": int(len(df)),
        "period_start": df.iloc[0]["period"],
        "period_end": df.iloc[-1]["period"],
        "schema_counts": df["type"].value_counts().sort_index().to_dict(),
        "timeline": df[["period", "file", "type", "column_count"]].to_dict(orient="records"),
        "transitions": transition[
            ["prev_period", "period", "file", "prev_type", "type"]
        ].to_dict(orient="records"),
    }
    write_run_summary(summary_file, summary)
    print(f"\nRun summary saved at: {summary_file}")


if __name__ == "__main__":
    main()
