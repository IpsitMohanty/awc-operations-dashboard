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


# ---------------------------------------------------------------------------
# Anomaly / risk / alert scoring
#
# Two independent scoring layers over fct_awc_monthly_snapshot:
#   - "risk" is an absolute, single-period read: does this period's value
#     cross a static level (risk_thresholds)? Feeds fct_awc_risk_snapshot.
#   - "anomaly" is a relative, movement read: did this period's value move
#     too far from the previous period or its own recent baseline
#     (anomaly_thresholds)? Feeds fct_awc_anomaly_flags.
# mart_awc_alerts_latest combines both plus a period-over-period risk-level
# comparison into a single current-vs-previous alert_scenario per centre.
# ---------------------------------------------------------------------------

RISK_LEVEL_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _is_num(value) -> bool:
    return value is not None and not pd.isna(value)


def classify_measurement_gap(efficiency_pct, risk_thresholds: dict) -> str | None:
    if not _is_num(efficiency_pct):
        return None
    if efficiency_pct < risk_thresholds["critical_measurement_gap"]:
        return "CRITICAL_MEASUREMENT_GAP"
    if efficiency_pct < risk_thresholds["high_measurement_gap"]:
        return "HIGH_MEASUREMENT_GAP"
    return None


RISK_RATE_CHECKS = (
    ("suw_rate_pct", "high_suw", "HIGH_SUW_RATE"),
    ("sam_rate_pct", "high_sam", "HIGH_SAM_RATE"),
    ("mam_rate_pct", "high_mam", "HIGH_MAM_RATE"),
    ("stunting_rate_pct", "high_stunting", "HIGH_STUNTING_RATE"),
)


def evaluate_risk_flags(row: dict, risk_thresholds: dict) -> list[str]:
    flags = []
    gap_flag = classify_measurement_gap(row.get("measuring_efficiency_0_6_years_pct"), risk_thresholds)
    if gap_flag:
        flags.append(gap_flag)
    for value_key, threshold_key, flag_name in RISK_RATE_CHECKS:
        value = row.get(value_key)
        if _is_num(value) and value > risk_thresholds[threshold_key]:
            flags.append(flag_name)
    return flags


def compute_risk_level(flag_count: int, risk_level_rules: dict) -> str:
    if flag_count >= risk_level_rules["high_min_flags"]:
        return "HIGH"
    if flag_count >= risk_level_rules["medium_min_flags"]:
        return "MEDIUM"
    return "LOW"


def evaluate_anomaly_flag(current_value, previous_value, rolling_baseline_value, threshold_value) -> dict:
    """Compare a metric's current value against its previous period and its
    own recent rolling baseline. Flags when either move exceeds threshold_value."""
    result = {
        "delta_value": None,
        "absolute_delta_value": None,
        "baseline_gap_value": None,
        "flag_reason": None,
    }
    if not _is_num(current_value):
        return result

    reasons = []
    if _is_num(previous_value):
        delta_value = current_value - previous_value
        result["delta_value"] = delta_value
        result["absolute_delta_value"] = abs(delta_value)
        if abs(delta_value) > threshold_value:
            reasons.append("PERIOD_OVER_PERIOD_RISE" if delta_value > 0 else "PERIOD_OVER_PERIOD_DROP")

    if _is_num(rolling_baseline_value):
        baseline_gap_value = current_value - rolling_baseline_value
        result["baseline_gap_value"] = baseline_gap_value
        if abs(baseline_gap_value) > threshold_value:
            reasons.append("BASELINE_DEVIATION_RISE" if baseline_gap_value > 0 else "BASELINE_DEVIATION_DROP")

    if reasons:
        result["flag_reason"] = "+".join(reasons)
    return result


def risk_direction(current_level: str, previous_level: str | None) -> str:
    if previous_level is None:
        return "NEW"
    current_rank = RISK_LEVEL_ORDER[current_level]
    previous_rank = RISK_LEVEL_ORDER[previous_level]
    if current_rank > previous_rank:
        return "WORSENED"
    if current_rank < previous_rank:
        return "IMPROVED"
    return "UNCHANGED"


def compute_alert_scenario(
    current_risk_level: str,
    previous_risk_level: str | None,
    recent_anomaly_count: int,
    alerts_config: dict,
) -> str:
    if previous_risk_level is None:
        return "NEW_HIGH_RISK" if current_risk_level == "HIGH" else "NEW_MONITORING"
    if current_risk_level == "HIGH" and previous_risk_level != "HIGH":
        return "NEW_HIGH_RISK"

    current_rank = RISK_LEVEL_ORDER[current_risk_level]
    previous_rank = RISK_LEVEL_ORDER[previous_risk_level]
    if current_rank > previous_rank:
        return "RISK_ESCALATED"
    if current_rank < previous_rank:
        return "RISK_IMPROVED"
    if current_risk_level == "HIGH":
        return "PERSISTENT_HIGH_RISK"
    if recent_anomaly_count >= alerts_config["high_recent_anomaly_count"]:
        return "ANOMALY_PRESSURE"
    return "STABLE"
