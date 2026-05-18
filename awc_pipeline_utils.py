import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

MONTHLY_FILE_PATTERNS = (
    "AWC_Operational_Efficiency_*.csv",
    "AWC_OPERATIONAL_EFFICIENCY_*.csv",
)

MONTH_NAME_TO_NUM = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}

STANDARD_COLUMNS = [
    "STATE NAME",
    "DISTRICT NAME",
    "PROJECT NAME",
    "SECTOR NAME",
    "AWC CODE",
    "AWC NAME",
    "TOTAL ACTIVE CHILDREN (0-6 YEARS)",
    "TOTAL ACTIVE CHILDREN MEASURED (0-6 YEARS)",
    "MEASURING EFFICIENCY (0-6 YEARS) (%)",
    "SUW",
    "MUW",
    "SEVERELY STUNTED",
    "MODERATELY STUNTED",
    "TOTAL ACTIVE CHILDREN MEASURED (0-5 YEARS)",
    "SAM",
    "MAM",
    "SUW %",
    "SAM %",
    "MAM %",
    "SOURCE_FILE",
]

DEFAULT_PIPELINE_CONFIG = {
    "anomaly_thresholds": {
        "MEASURING EFFICIENCY (0-6 YEARS) (%)": 20,
        "suw_rate_pct": 5,
        "sam_rate_pct": 5,
        "mam_rate_pct": 5,
        "stunting_rate_pct": 5,
    },
    "risk_thresholds": {
        "critical_measurement_gap": 60,
        "high_measurement_gap": 80,
        "high_suw": 15,
        "high_sam": 8,
        "high_mam": 15,
        "high_stunting": 25,
    },
    "risk_level_rules": {
        "high_min_flags": 3,
        "medium_min_flags": 1,
    },
    "alerts": {
        "recent_period_window": 3,
        "high_recent_anomaly_count": 3,
        "medium_recent_anomaly_count": 1,
    },
}


@dataclass(frozen=True, order=True)
class FilePeriod:
    year: int
    month: int

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def resolve_folder(folder: str | None = None) -> Path:
    return Path(folder).expanduser().resolve() if folder else Path(__file__).resolve().parent


def parse_period_from_name(source_file: str) -> FilePeriod:
    upper_name = source_file.upper()
    year_match = re.search(r"(20\d{2})", upper_name)
    if not year_match:
        raise ValueError(f"Could not parse year from source file: {source_file}")

    year = int(year_match.group(1))
    numeric_month_match = re.search(r"AWC[_ ]OPERATIONAL[_ ]EFFICIENCY_(\d{2})", upper_name)
    if numeric_month_match:
        return FilePeriod(year=year, month=int(numeric_month_match.group(1)))

    for month_name, month_num in MONTH_NAME_TO_NUM.items():
        if month_name in upper_name:
            return FilePeriod(year=year, month=month_num)

    raise ValueError(f"Could not parse month/year from source file: {source_file}")


def get_source_files(folder: Path, excluded_files: Iterable[str] | None = None) -> list[Path]:
    files = []
    seen = set()
    excluded = set(excluded_files or [])

    for pattern in MONTHLY_FILE_PATTERNS:
        for path in sorted(folder.glob(pattern)):
            if path.name in excluded or path.name in seen:
                continue
            seen.add(path.name)
            files.append(path)

    return sorted(files, key=lambda path: (parse_period_from_name(path.name), path.name))


def find_header_line_index(path: Path) -> int:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    for i, line in enumerate(lines[:100]):
        s = line.strip().upper()
        if "STATE NAME" in s and "DISTRICT NAME" in s:
            return i
    return 0


def safe_float(val):
    if val in ["", None]:
        return None
    try:
        return float(str(val).replace("%", "").strip())
    except ValueError:
        return None


def classify_schema(headers: Iterable[str]) -> str:
    header_set = set(headers)
    percent_columns = {"SUW %", "SAM %", "MAM %"}
    count_columns = {
        "SUW",
        "MUW",
        "SEVERELY STUNTED",
        "MODERATELY STUNTED",
        "SAM",
        "MAM",
    }
    if header_set & percent_columns:
        return "PERCENT"
    if header_set & count_columns:
        return "COUNT"
    return "UNKNOWN"


def validate_periods(source_files: list[Path]) -> None:
    periods = [parse_period_from_name(path.name).label for path in source_files]
    duplicates = pd.Series(periods).value_counts()
    duplicate_periods = duplicates[duplicates > 1]
    if not duplicate_periods.empty:
        raise ValueError(
            "Duplicate monthly periods detected: "
            + ", ".join(f"{period} ({count} files)" for period, count in duplicate_periods.items())
        )


def write_run_summary(path: Path, summary: dict) -> None:
    serializable_summary = json.loads(json.dumps(summary, default=_json_default))
    path.write_text(json.dumps(serializable_summary, indent=2), encoding="utf-8")


def load_pipeline_config(path: Path | None = None) -> dict:
    config = copy.deepcopy(DEFAULT_PIPELINE_CONFIG)
    if path is None or not path.exists():
        return config

    user_config = json.loads(path.read_text(encoding="utf-8"))
    _deep_update(config, user_config)
    return config


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _deep_update(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
