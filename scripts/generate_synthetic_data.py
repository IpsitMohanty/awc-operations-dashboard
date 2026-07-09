"""Synthetic AWC monthly report generator.

Produces fictional monthly AWC_Operational_Efficiency_*.csv files that match the
real export schema handled by harmonize_merge_awc.py / awc_pipeline_utils.py:
same columns, same PERCENT -> COUNT schema transition, same filename quirks,
same header/BOM quirks. It also injects deliberate anomalies so the pipeline's
existing drift/validation checks (and the dashboard's trend charts) have
something visible to catch.

ALL DATA PRODUCED BY THIS SCRIPT IS FICTIONAL. No real AWC centres, districts,
blocks, sectors, or children are represented. See the generated
synthetic_data/README.md for details.
"""

import argparse
import random
import string
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from awc_pipeline_utils import utc_now_iso, write_run_summary  # noqa: E402

STATE_NAME = "Sundarvana"
STATE_CODE = "77"

# Fictional districts. Deliberately distinct from every real Odisha district
# name that appears in this repo's real sample CSVs (Angul, Balangir,
# Balasore, Bargarh, Bhadrak, Boudh, Cuttack, Deogarh, Dhenkanal, Gajapati,
# Ganjam, Jagatsinghpur, Jajapur, Jharsuguda, Kalahandi, Kandhamal,
# Kendrapara, Keonjhar, Khordha, Koraput, Malkangiri, Mayurbhanj,
# Nabarangpur, Nayagarh, Nuapada, Puri, Rayagada, Sambalpur, Subarnapur,
# Sundergarh).
DISTRICT_NAMES = [
    "Kirtipur", "Devbhumi", "Ranital", "Meghpur", "Shantigarh",
    "Amarkot", "Bijaynagar", "Chandragiri", "Suryagarh", "Vishwanathpur",
]

PROJECTS_PER_DISTRICT = 4
SECTORS_PER_PROJECT = 5
AWCS_PER_SECTOR = 10
# 10 * 4 * 5 * 10 = 2,000 centres

NAME_SYLLABLES = [
    "ka", "ma", "su", "va", "me", "ru", "sha", "am", "na", "ra",
    "ni", "de", "ja", "vi", "ha", "bi", "ta", "sa", "pra", "lo",
    "ki", "go", "bu", "chi", "pa", "tri", "dha", "la", "gan", "mo",
]
PROJECT_SUFFIXES = ["pur", "garh", "nagar", "kot", "giri", "ganj", "khand", "pada"]
SECTOR_SUFFIXES = ["pada", "sahi", "basti", "tola", "bandha", "gram", "vihar", "dihi", "palli"]

PERCENT_COLUMNS = [
    "STATE NAME", "DISTRICT NAME", "PROJECT NAME", "SECTOR NAME", "AWC CODE", "AWC NAME",
    "TOTAL ACTIVE CHILDREN (0-6 YEARS)", "TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)",
    "MEASURING EFFICIENCY (0-6 YEARS) (%)", "SUW %", "TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)",
    "SAM %", "MAM %",
]

# (year, month, filename, schema, use_bom)
PERIOD_SPECS = [
    (2024, 1, "AWC_Operational_Efficiency_01_2024_January.csv", "PERCENT", False),
    (2024, 2, "AWC_Operational_Efficiency_02_2024_February.csv", "PERCENT", False),
    (2024, 3, "AWC_Operational_Efficiency_March_2024.csv", "PERCENT", False),
    (2024, 4, "AWC_Operational_Efficiency_04_2024_April.csv", "PERCENT", False),
    (2024, 5, "AWC_Operational_Efficiency_05_2024_May.csv", "PERCENT", False),
    (2024, 6, "AWC_OPERATIONAL_EFFICIENCY_JUNE_2024.csv", "PERCENT", False),
    (2024, 7, "AWC_Operational_Efficiency_July_07_2024.csv", "COUNT", False),
    (2024, 8, "AWC_Operational_Efficiency_08_2024_Sundarvana.csv", "COUNT", True),
    (2024, 9, "AWC_Operational_Efficiency_09_2024_September.csv", "COUNT", False),
    (2024, 10, "AWC_Operational_Efficiency_10_2024_October.csv", "COUNT", False),
    (2024, 11, "AWC_Operational_Efficiency_11_2024_November.csv", "COUNT", False),
    (2024, 12, "AWC_Operational_Efficiency_12_2024_December.csv", "COUNT", True),
]

ROW_COUNT_DROP_PERIOD = (2024, 9)
ROW_COUNT_DROP_FRACTION = 0.10
COLUMN_RENAME_PERIOD = (2024, 11)
ROW_ANOMALY_RATE = 0.02
ANOMALY_KINDS = [
    "measured_exceeds_active",
    "efficiency_out_of_range",
    "negative_count",
    "extreme_rate_spike",
    "population_spike",
]


@dataclass
class Centre:
    awc_code: str
    state_name: str
    district_name: str
    project_name: str
    sector_name: str
    awc_name: str
    base_population: float
    suw_rate: float
    muw_rate: float
    severe_stunt_rate: float
    moderate_stunt_rate: float
    sam_rate: float
    mam_rate: float
    full_measurement_prob: float


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def jitter(rng: random.Random, rate: float, spread: float = 0.3, cap: float = 0.9) -> float:
    factor = 1 + rng.uniform(-spread, spread)
    return clamp(rate * factor, 0.0, cap)


def unique_name(rng: random.Random, suffixes: list, used: set, max_tries: int = 50) -> str:
    candidate = None
    for _ in range(max_tries):
        stem = "".join(rng.sample(NAME_SYLLABLES, k=2))
        candidate = f"{stem}{rng.choice(suffixes)}".capitalize()
        if candidate not in used:
            return candidate
    return f"{candidate}{len(used)}"


def count_columns_for(moderate_key: str) -> list:
    return [
        "STATE NAME", "DISTRICT NAME", "PROJECT NAME", "SECTOR NAME", "AWC CODE", "AWC NAME",
        "TOTAL ACTIVE CHILDREN (0-6 YEARS)", "TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)",
        "MEASURING EFFICIENCY (0-6 YEARS) (%)", "SUW", "MUW", "SEVERELY STUNTED", moderate_key,
        "TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)", "SAM", "MAM",
    ]


def build_centres(rng: random.Random) -> list:
    centres = []
    for d_idx, district in enumerate(DISTRICT_NAMES, start=1):
        used_projects = set()
        for p_idx in range(1, PROJECTS_PER_DISTRICT + 1):
            project_name = district if p_idx == 1 else unique_name(rng, PROJECT_SUFFIXES, used_projects)
            used_projects.add(project_name)

            used_sectors = set()
            for s_idx in range(1, SECTORS_PER_PROJECT + 1):
                sector_name = unique_name(rng, SECTOR_SUFFIXES, used_sectors)
                used_sectors.add(sector_name)

                for a_idx in range(1, AWCS_PER_SECTOR + 1):
                    awc_code = f"{STATE_CODE}{d_idx:03d}{p_idx:02d}{s_idx:02d}{a_idx:02d}"
                    letter = string.ascii_uppercase[(a_idx - 1) % 26]
                    centres.append(Centre(
                        awc_code=awc_code,
                        state_name=STATE_NAME,
                        district_name=district,
                        project_name=project_name,
                        sector_name=sector_name,
                        awc_name=f"{sector_name}-{letter}",
                        base_population=clamp(rng.gauss(41, 20), 6, 200),
                        suw_rate=rng.uniform(0.0, 0.06),
                        muw_rate=rng.uniform(0.03, 0.18),
                        severe_stunt_rate=rng.uniform(0.0, 0.15),
                        moderate_stunt_rate=rng.uniform(0.02, 0.25),
                        sam_rate=rng.uniform(0.0, 0.02),
                        mam_rate=rng.uniform(0.0, 0.06),
                        full_measurement_prob=rng.uniform(0.9, 0.995),
                    ))
    return centres


def generate_row_values(centre: Centre, rng: random.Random) -> dict:
    active = clamp(round(rng.gauss(centre.base_population, max(2.0, centre.base_population * 0.08))), 3, 300)
    if rng.random() < centre.full_measurement_prob:
        measured_06 = active
    else:
        drop = rng.randint(1, max(1, round(active * 0.3)))
        measured_06 = max(0, active - drop)
    efficiency = round((measured_06 / active) * 100, 1) if active else 0.0
    measured_05 = max(0, round(measured_06 * rng.uniform(0.72, 0.95)))

    suw_rate = jitter(rng, centre.suw_rate)
    muw_rate = jitter(rng, centre.muw_rate)
    severe_rate = jitter(rng, centre.severe_stunt_rate)
    moderate_rate = jitter(rng, centre.moderate_stunt_rate)
    sam_rate = jitter(rng, centre.sam_rate)
    mam_rate = jitter(rng, centre.mam_rate)

    return {
        "active_06": active,
        "measured_06": measured_06,
        "efficiency": efficiency,
        "measured_05": measured_05,
        "suw_count": max(0, round(measured_06 * suw_rate)),
        "muw_count": max(0, round(measured_06 * muw_rate)),
        "severe_count": max(0, round(measured_06 * severe_rate)),
        "moderate_count": max(0, round(measured_06 * moderate_rate)),
        "sam_count": max(0, round(measured_05 * sam_rate)),
        "mam_count": max(0, round(measured_05 * mam_rate)),
        "suw_pct": round(suw_rate * 100, 2),
        "sam_pct": round(sam_rate * 100, 2),
        "mam_pct": round(mam_rate * 100, 2),
    }


def maybe_inject_row_anomaly(values: dict, schema: str, rng: random.Random) -> str:
    if rng.random() >= ROW_ANOMALY_RATE:
        return None
    kind = rng.choice(ANOMALY_KINDS)

    if kind == "measured_exceeds_active":
        delta = rng.randint(5, 40)
        values["measured_06"] = values["active_06"] + delta
        values["efficiency"] = round((values["measured_06"] / values["active_06"]) * 100, 1)
    elif kind == "efficiency_out_of_range":
        values["efficiency"] = rng.choice([
            round(rng.uniform(101, 148), 1),
            round(rng.uniform(-35, -1), 1),
        ])
    elif kind == "negative_count":
        if schema == "COUNT":
            field = rng.choice(["suw_count", "muw_count", "severe_count", "moderate_count", "sam_count", "mam_count"])
            values[field] = -rng.randint(1, 8)
        else:
            field = rng.choice(["suw_pct", "sam_pct", "mam_pct"])
            values[field] = -round(rng.uniform(1, 8), 2)
    elif kind == "extreme_rate_spike":
        if schema == "COUNT":
            field = rng.choice(["suw_count", "sam_count", "mam_count"])
            denom = values["measured_05"] if field in ("sam_count", "mam_count") else values["measured_06"]
            values[field] = denom if denom else rng.randint(10, 40)
        else:
            field = rng.choice(["suw_pct", "sam_pct", "mam_pct"])
            values[field] = round(rng.uniform(55, 98), 2)
    elif kind == "population_spike":
        values["active_06"] = rng.randint(450, 999)
        values["measured_06"] = min(values["measured_06"], values["active_06"])

    return kind


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    fval = float(value)
    if fval.is_integer():
        return str(int(fval))
    text = f"{fval:.2f}".rstrip("0").rstrip(".")
    return text


def build_row(centre: Centre, values: dict, schema: str, moderate_key: str) -> dict:
    row = {
        "STATE NAME": centre.state_name,
        "DISTRICT NAME": centre.district_name,
        "PROJECT NAME": centre.project_name,
        "SECTOR NAME": centre.sector_name,
        "AWC CODE": centre.awc_code,
        "AWC NAME": centre.awc_name,
        "TOTAL ACTIVE CHILDREN (0-6 YEARS)": fmt(values["active_06"]),
        "TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)": fmt(values["measured_06"]),
        "MEASURING EFFICIENCY (0-6 YEARS) (%)": fmt(values["efficiency"]),
    }
    if schema == "PERCENT":
        row["SUW %"] = fmt(values["suw_pct"])
        row["TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)"] = fmt(values["measured_05"])
        row["SAM %"] = fmt(values["sam_pct"])
        row["MAM %"] = fmt(values["mam_pct"])
    else:
        row["SUW"] = fmt(values["suw_count"])
        row["MUW"] = fmt(values["muw_count"])
        row["SEVERELY STUNTED"] = fmt(values["severe_count"])
        row[moderate_key] = fmt(values["moderate_count"])
        row["TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)"] = fmt(values["measured_05"])
        row["SAM"] = fmt(values["sam_count"])
        row["MAM"] = fmt(values["mam_count"])
    return row


def build_period_file(centres: list, spec: tuple, rng: random.Random, anomaly_log: list) -> tuple:
    year, month, filename, schema, use_bom = spec
    is_drop = (year, month) == ROW_COUNT_DROP_PERIOD
    is_rename = (year, month) == COLUMN_RENAME_PERIOD
    moderate_key = "MODERATE STUNTED" if is_rename else "MODERATELY STUNTED"

    working_centres = centres
    dropped_count = 0
    if is_drop:
        drop_n = round(len(centres) * ROW_COUNT_DROP_FRACTION)
        dropped_codes = {c.awc_code for c in rng.sample(centres, drop_n)}
        working_centres = [c for c in centres if c.awc_code not in dropped_codes]
        dropped_count = drop_n

    rows = []
    for centre in working_centres:
        values = generate_row_values(centre, rng)
        kind = maybe_inject_row_anomaly(values, schema, rng)
        if kind:
            anomaly_log.append({
                "period": f"{year:04d}-{month:02d}",
                "source_file": filename,
                "awc_code": centre.awc_code,
                "anomaly_kind": kind,
            })
        rows.append(build_row(centre, values, schema, moderate_key))

    columns = PERCENT_COLUMNS if schema == "PERCENT" else count_columns_for(moderate_key)
    df = pd.DataFrame(rows, columns=columns)
    return df, dropped_count, is_rename


def write_readme_note(output_dir: Path, summary: dict) -> None:
    drop_file = next(f["file"] for f in summary["files"] if f["period"] == summary["row_count_drop_period"])
    rename_file = next(f["file"] for f in summary["files"] if f["period"] == summary["column_rename_period"])
    lines = [
        "# Synthetic AWC Demo Dataset",
        "",
        "**All data in this folder is synthetic and fictional.** Centre codes, district/",
        "block/sector names, population counts, and nutrition figures are randomly",
        f"generated and do not represent any real Anganwadi Centre, child, or the real",
        f"Odisha administrative geography. The state name `{STATE_NAME}` and every",
        "district/project/sector name are invented for this demo dataset.",
        "",
        f"Generated by `scripts/generate_synthetic_data.py --seed {summary['seed']}`.",
        "Regenerating with the same seed reproduces this dataset byte-for-byte.",
        "",
        "## Shape",
        "",
        f"- {summary['centre_count']} fictional AWC centres across {summary['district_count']} fictional districts",
        f"- {len(summary['files'])} monthly files, `{summary['files'][0]['period']}` through `{summary['files'][-1]['period']}`",
        "- Columns match `harmonize_merge_awc.py` / `awc_pipeline_utils.py` (`STANDARD_COLUMNS`)",
        "  exactly, including the PERCENT-era (`SUW %`, `SAM %`, `MAM %`) to COUNT-era (`SUW`,",
        "  `MUW`, `SEVERELY STUNTED`, `MODERATELY STUNTED`, `SAM`, `MAM`) schema transition, and",
        "  the same filename quirks as the real exports (numeric-month, month-name-only, and",
        "  all-caps filenames, plus a UTF-8 BOM on some files).",
        "",
        "## Deliberately injected anomalies",
        "",
        f"- **Row-count drop** (`{drop_file}`): ships with roughly "
        f"{int(ROW_COUNT_DROP_FRACTION * 100)}% fewer rows than the other months. Running "
        "`harmonize_merge_awc.py` across the full folder will raise `Abnormal row-count drift "
        "detected` for this file - that's intentional, and demonstrates the harmonizer's "
        "built-in row-count drift guard (`validate_file_summaries` in `awc_pipeline_utils.py`). "
        "Remove or fix that one file to let the harmonize step proceed across the rest.",
        f"- **Schema drift / renamed column** (`{rename_file}`): ships with `MODERATELY STUNTED` "
        "renamed to `MODERATE STUNTED`. The COUNT-schema classification is unaffected "
        "(`classify_schema` still sees the other count columns), so the harmonizer does not "
        "raise - it silently backfills `MODERATELY STUNTED` as blank for every row that month. "
        "Look for the resulting dip to zero in `moderately_stunted_count` / `stunting_rate_pct` "
        "for that month in the dashboard's trend charts, and cross-check it against "
        "`schema_transition_check.py`'s output.",
        f"- **Out-of-range row values** (~{summary['row_anomaly_rate_target'] * 100:.0f}% of rows, "
        f"{summary['row_anomaly_count']} rows): measured children exceeding active children, "
        "measuring efficiency outside 0-100%, negative nutrition counts, implausible rate "
        "spikes, and implausible population spikes. These do not crash the current pipeline "
        "(there is no live per-row anomaly-flag layer today - see the main README's 'Known "
        "Scope' section), but they show up as visible outliers in the dashboard and are exactly "
        "the kind of rows the thresholds in `awc_pipeline_config.json` "
        "(`anomaly_thresholds`, `risk_thresholds`) are meant to catch if that layer is rebuilt. "
        "See `synthetic_anomaly_log.csv` for the full list of affected "
        "`(period, awc_code, anomaly_kind)` rows.",
        "",
        "## Using this dataset",
        "",
        "```powershell",
        f'python schema_transition_check.py --folder "{output_dir}"',
        f'python harmonize_merge_awc.py --folder "{output_dir}"',
        f'python load_awc_warehouse.py --folder "{output_dir}"',
        "```",
        "",
        "`awc_dashboard_streamlit.py` reads a fixed `awc_warehouse.sqlite` path next to the",
        "script. To view this synthetic dataset in the dashboard, back up the real",
        f"`awc_warehouse.sqlite` and copy the one produced above "
        f"(`{output_dir}\\awc_warehouse.sqlite`) over it, or point a separate copy of the",
        "dashboard script at the synthetic database file.",
        "",
        "## Files",
        "",
        "- Monthly CSVs: `AWC_Operational_Efficiency_*.csv` / `AWC_OPERATIONAL_EFFICIENCY_*.csv`",
        "- `synthetic_anomaly_log.csv` - every injected row-level anomaly, with period/AWC code/kind",
        "- `synthetic_generation_summary.json` - machine-readable generation summary (seed, files, counts)",
        "",
    ]
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic monthly AWC dataset for demoing harmonize_merge_awc.py's "
        "schema/drift detection and the Streamlit dashboard."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write synthetic monthly CSVs into (default: <repo_root>/synthetic_data).",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else repo_root / "synthetic_data"
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    centres = build_centres(rng)

    anomaly_log = []
    file_summaries = []
    for spec in PERIOD_SPECS:
        year, month, filename, schema, use_bom = spec
        df, dropped_count, is_rename = build_period_file(centres, spec, rng, anomaly_log)

        out_path = output_dir / filename
        encoding = "utf-8-sig" if use_bom else "utf-8"
        df.to_csv(out_path, index=False, encoding=encoding)

        file_summaries.append({
            "period": f"{year:04d}-{month:02d}",
            "file": filename,
            "schema": schema,
            "row_count": len(df),
            "bom": use_bom,
            "row_count_drop_injected": dropped_count,
            "column_rename_injected": is_rename,
        })
        print(f"Wrote {filename}: {len(df)} rows ({schema} schema{' + BOM' if use_bom else ''})")

    anomaly_df = pd.DataFrame(anomaly_log, columns=["period", "source_file", "awc_code", "anomaly_kind"])
    anomaly_log_path = output_dir / "synthetic_anomaly_log.csv"
    anomaly_df.to_csv(anomaly_log_path, index=False)

    total_rows = sum(f["row_count"] for f in file_summaries)
    summary = {
        "generator": "generate_synthetic_data",
        "run_timestamp_utc": utc_now_iso(),
        "seed": args.seed,
        "output_dir": str(output_dir),
        "centre_count": len(centres),
        "state_name": STATE_NAME,
        "district_count": len(DISTRICT_NAMES),
        "total_rows": total_rows,
        "row_anomaly_rate_target": ROW_ANOMALY_RATE,
        "row_anomaly_count": len(anomaly_log),
        "row_count_drop_period": f"{ROW_COUNT_DROP_PERIOD[0]:04d}-{ROW_COUNT_DROP_PERIOD[1]:02d}",
        "column_rename_period": f"{COLUMN_RENAME_PERIOD[0]:04d}-{COLUMN_RENAME_PERIOD[1]:02d}",
        "files": file_summaries,
    }
    write_run_summary(output_dir / "synthetic_generation_summary.json", summary)
    write_readme_note(output_dir, summary)

    print(f"\nSynthetic dataset written to: {output_dir}")
    print(f"Total rows: {total_rows}")
    print(f"Row-level anomalies injected: {len(anomaly_log)} ({len(anomaly_log) / total_rows * 100:.2f}% of rows)")
    print(f"Row-count drop injected in: {summary['row_count_drop_period']}")
    print(f"Column-rename schema drift injected in: {summary['column_rename_period']}")
    print(f"Anomaly log: {anomaly_log_path}")
    print(f"Generation summary: {output_dir / 'synthetic_generation_summary.json'}")
    print(f"Dataset README: {output_dir / 'README.md'}")


if __name__ == "__main__":
    main()
