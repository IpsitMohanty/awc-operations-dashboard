import argparse
import subprocess
import sys
from pathlib import Path

from awc_pipeline_utils import resolve_folder, utc_now_iso, write_run_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AWC production pipeline end to end.")
    parser.add_argument("--folder", default=None, help="Folder containing the AWC pipeline files.")
    parser.add_argument(
        "--config-file",
        default="awc_pipeline_config.json",
        help="Name or path of the pipeline config JSON.",
    )
    parser.add_argument(
        "--summary-file",
        default="pipeline_run_summary.json",
        help="Name or path of the pipeline JSON run summary.",
    )
    parser.add_argument(
        "--skip-warehouse-load",
        action="store_true",
        help="Skip loading curated outputs into the local SQLite warehouse.",
    )
    return parser.parse_args()


def resolve_output_path(folder: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


def run_step(name: str, command: list[str], workdir: Path) -> dict:
    print(f"\n[{name}] Running: {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"Step '{name}' failed with exit code {completed.returncode}.")
    return {
        "step": name,
        "command": command,
        "return_code": completed.returncode,
    }


def main() -> None:
    args = parse_args()
    folder = resolve_folder(args.folder)
    config_file = resolve_output_path(folder, args.config_file)
    summary_file = resolve_output_path(folder, args.summary_file)

    steps = [
        (
            "schema_transition_check",
            [sys.executable, "schema_transition_check.py", "--folder", str(folder)],
        ),
        (
            "harmonize_merge_awc",
            [sys.executable, "harmonize_merge_awc.py", "--folder", str(folder)],
        ),
        (
            "anomaly_risk_flags",
            [
                sys.executable,
                "anomaly_risk_flags.py",
                "--folder",
                str(folder),
                "--config-file",
                str(config_file),
            ],
        ),
    ]
    if not args.skip_warehouse_load:
        steps.append(
            (
                "load_awc_warehouse",
                [sys.executable, "load_awc_warehouse.py", "--folder", str(folder)],
            )
        )

    results = []
    for name, command in steps:
        results.append(run_step(name, command, folder))

    summary = {
        "pipeline": "run_awc_pipeline",
        "run_timestamp_utc": utc_now_iso(),
        "folder": str(folder),
        "config_file": str(config_file),
        "steps": results,
        "status": "SUCCESS",
    }
    write_run_summary(summary_file, summary)
    print(f"\nPipeline summary saved at: {summary_file}")


if __name__ == "__main__":
    main()
