import argparse
from pathlib import Path

import pandas as pd

from awc_pipeline_utils import (
    compute_alert_scenario,
    compute_risk_level,
    evaluate_anomaly_flag,
    evaluate_risk_flags,
    load_pipeline_config,
    resolve_folder,
    risk_direction,
    utc_now_iso,
    write_run_summary,
)
from load_awc_warehouse import monthly_snapshot_frame

# Anomaly thresholds are keyed by the column they compare against; efficiency
# is looked up under its verbose config key, the rest are already snake_case.
ANOMALY_METRIC_COLUMNS = {
    "MEASURING EFFICIENCY (0-6 YEARS) (%)": "measuring_efficiency_0_6_years_pct",
    "suw_rate_pct": "suw_rate_pct",
    "sam_rate_pct": "sam_rate_pct",
    "mam_rate_pct": "mam_rate_pct",
    "stunting_rate_pct": "stunting_rate_pct",
}

ANOMALY_FLAG_COLUMNS = [
    "awc_code", "period", "metric_name", "state_name", "district_name", "project_name", "sector_name",
    "awc_name", "source_file", "current_value", "previous_value", "delta_value", "absolute_delta_value",
    "rolling_baseline_value", "baseline_gap_value", "threshold_value", "flag_reason",
]

RISK_SNAPSHOT_COLUMNS = [
    "awc_code", "period", "state_name", "district_name", "project_name", "sector_name", "awc_name",
    "source_file", "measuring_efficiency_0_6_years_pct", "suw_rate_pct", "sam_rate_pct", "mam_rate_pct",
    "stunting_rate_pct", "risk_flags", "risk_flag_count", "risk_level",
]

METRIC_DELTA_FIELDS = [
    "total_active_children_0_6_years", "total_active_children_measured_0_6_years",
    "measuring_efficiency_0_6_years_pct", "total_active_children_measured_0_5_years",
    "suw_count", "muw_count", "severely_stunted_count", "moderately_stunted_count",
    "sam_count", "mam_count", "suw_rate_pct", "sam_rate_pct", "mam_rate_pct", "stunting_rate_pct",
]

ALERTS_LATEST_COLUMNS = (
    ["awc_code", "current_period", "previous_period", "state_name", "district_name", "project_name",
     "sector_name", "awc_name", "source_file"]
    + [
        column
        for field in METRIC_DELTA_FIELDS
        for column in (field, f"previous_{field}", f"delta_{field}")
    ]
    + [
        "risk_level", "risk_flags", "risk_flag_count",
        "previous_risk_period", "previous_risk_level", "previous_risk_flags", "previous_risk_flag_count",
        "risk_direction", "recent_anomaly_count", "latest_anomaly_period", "recent_anomaly_metrics",
        "recent_flag_reasons", "alert_scenario",
    ]
)

IDENTITY_FIELDS = ["state_name", "district_name", "project_name", "sector_name", "awc_name", "source_file"]

NEGATIVE_COUNT_FIELDS = {
    "suw_count": "NEGATIVE_SUW_COUNT",
    "muw_count": "NEGATIVE_MUW_COUNT",
    "severely_stunted_count": "NEGATIVE_SEVERELY_STUNTED_COUNT",
    "moderately_stunted_count": "NEGATIVE_MODERATELY_STUNTED_COUNT",
    "sam_count": "NEGATIVE_SAM_COUNT",
    "mam_count": "NEGATIVE_MAM_COUNT",
}

NEGATIVE_RATE_FIELDS = {
    "suw_rate_pct": "NEGATIVE_SUW_RATE_PCT",
    "sam_rate_pct": "NEGATIVE_SAM_RATE_PCT",
    "mam_rate_pct": "NEGATIVE_MAM_RATE_PCT",
}


def _is_num(value) -> bool:
    return value is not None and not pd.isna(value)


def _period_label(period) -> str | None:
    if period is None or (not isinstance(period, str) and pd.isna(period)):
        return None
    ts = pd.Timestamp(period)
    return f"{ts.year:04d}-{ts.month:02d}"


def compute_data_quality_flags(snapshot_df: pd.DataFrame) -> list:
    records = []
    for row in snapshot_df.to_dict("records"):
        base = {"awc_code": row["awc_code"], "period": row["period"], **{k: row.get(k) for k in IDENTITY_FIELDS}}

        active = row.get("total_active_children_0_6_years")
        measured = row.get("total_active_children_measured_0_6_years")
        if _is_num(active) and _is_num(measured) and measured > active:
            delta = measured - active
            records.append({
                **base, "metric_name": "MEASURED_EXCEEDS_ACTIVE", "current_value": measured,
                "previous_value": active, "delta_value": delta, "absolute_delta_value": abs(delta),
                "rolling_baseline_value": None, "baseline_gap_value": None,
                "threshold_value": 0.0, "flag_reason": "MEASURED_EXCEEDS_ACTIVE",
            })

        efficiency = row.get("measuring_efficiency_0_6_years_pct")
        if _is_num(efficiency) and (efficiency < 0 or efficiency > 100):
            records.append({
                **base, "metric_name": "MEASURING_EFFICIENCY_OUT_OF_RANGE", "current_value": efficiency,
                "previous_value": None, "delta_value": None, "absolute_delta_value": None,
                "rolling_baseline_value": None, "baseline_gap_value": None,
                "threshold_value": 100.0, "flag_reason": "MEASURING_EFFICIENCY_OUT_OF_RANGE",
            })

        for field, metric_name in {**NEGATIVE_COUNT_FIELDS, **NEGATIVE_RATE_FIELDS}.items():
            value = row.get(field)
            if _is_num(value) and value < 0:
                records.append({
                    **base, "metric_name": metric_name, "current_value": value,
                    "previous_value": None, "delta_value": None, "absolute_delta_value": None,
                    "rolling_baseline_value": None, "baseline_gap_value": None,
                    "threshold_value": 0.0, "flag_reason": metric_name,
                })
    return records


def compute_anomaly_flags(snapshot_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """For each tracked metric, compute the previous-period value and a rolling
    baseline (mean of up to recent_period_window prior periods) per centre
    using vectorized groupby/shift/rolling - not a per-row Python loop, which
    does not scale to real AWC centre counts (~74k vs. ~2k in the synthetic
    demo dataset). evaluate_anomaly_flag (unit-tested in tests/) still decides
    the actual flag_reason; it's only invoked for rows that already cross a
    threshold on a vectorized pre-filter, keeping the Python-level loop small.
    """
    thresholds = config["anomaly_thresholds"]
    baseline_window = config["alerts"]["recent_period_window"]
    sorted_df = snapshot_df.sort_values(["awc_code", "period"]).reset_index(drop=True)
    grouped_awc_code = sorted_df.groupby("awc_code", sort=False)

    records = []
    for metric_key, column in ANOMALY_METRIC_COLUMNS.items():
        threshold = thresholds[metric_key]
        current_value = sorted_df[column]
        previous_value = grouped_awc_code[column].shift(1)
        rolling_baseline_value = (
            previous_value.groupby(sorted_df["awc_code"])
            .rolling(baseline_window, min_periods=1)
            .mean()
            .reset_index(level=0, drop=True)
        )

        delta_value = current_value - previous_value
        baseline_gap_value = current_value - rolling_baseline_value
        candidate_mask = current_value.notna() & (
            (delta_value.abs() > threshold) | (baseline_gap_value.abs() > threshold)
        )
        if not candidate_mask.any():
            continue

        candidates = sorted_df.loc[candidate_mask, ["awc_code", "period", *IDENTITY_FIELDS]].copy()
        candidates["current_value"] = current_value[candidate_mask]
        candidates["previous_value"] = previous_value[candidate_mask]
        candidates["rolling_baseline_value"] = rolling_baseline_value[candidate_mask]

        for row in candidates.to_dict("records"):
            result = evaluate_anomaly_flag(
                row["current_value"], row["previous_value"], row["rolling_baseline_value"], threshold,
            )
            if result["flag_reason"] is None:
                continue
            records.append({
                "awc_code": row["awc_code"], "period": row["period"], "metric_name": metric_key,
                **{k: row.get(k) for k in IDENTITY_FIELDS},
                "current_value": row["current_value"], "previous_value": row["previous_value"],
                "delta_value": result["delta_value"], "absolute_delta_value": result["absolute_delta_value"],
                "rolling_baseline_value": row["rolling_baseline_value"], "baseline_gap_value": result["baseline_gap_value"],
                "threshold_value": threshold, "flag_reason": result["flag_reason"],
            })

    records.extend(compute_data_quality_flags(snapshot_df))
    if not records:
        return pd.DataFrame(columns=ANOMALY_FLAG_COLUMNS)
    return (
        pd.DataFrame.from_records(records, columns=ANOMALY_FLAG_COLUMNS)
        .sort_values(["period", "awc_code", "metric_name"])
        .reset_index(drop=True)
    )


def compute_risk_snapshot(snapshot_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    risk_thresholds = config["risk_thresholds"]
    risk_level_rules = config["risk_level_rules"]
    records = []
    for row in snapshot_df.to_dict("records"):
        flags = evaluate_risk_flags(row, risk_thresholds)
        records.append({
            "awc_code": row["awc_code"], "period": row["period"],
            **{k: row.get(k) for k in IDENTITY_FIELDS},
            "measuring_efficiency_0_6_years_pct": row.get("measuring_efficiency_0_6_years_pct"),
            "suw_rate_pct": row.get("suw_rate_pct"),
            "sam_rate_pct": row.get("sam_rate_pct"),
            "mam_rate_pct": row.get("mam_rate_pct"),
            "stunting_rate_pct": row.get("stunting_rate_pct"),
            "risk_flags": "|".join(flags),
            "risk_flag_count": len(flags),
            "risk_level": compute_risk_level(len(flags), risk_level_rules),
        })
    return pd.DataFrame.from_records(records, columns=RISK_SNAPSHOT_COLUMNS)


def compute_alerts_latest(snapshot_df: pd.DataFrame, risk_df: pd.DataFrame, anomaly_df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """One row per centre for the latest period. Looks up each centre's risk
    history and recent anomalies via pre-grouped dicts, not by re-filtering
    the full risk_df/anomaly_df per centre - that per-centre full-table scan
    is O(centres * total_rows) and does not scale to real AWC centre counts.
    """
    alerts_config = config["alerts"]
    window = alerts_config["recent_period_window"]
    latest_period = snapshot_df["period"].max()

    risk_by_awc_code = {code: g.set_index("period") for code, g in risk_df.groupby("awc_code", sort=False)}
    anomaly_by_awc_code = (
        {code: g for code, g in anomaly_df.groupby("awc_code", sort=False)} if not anomaly_df.empty else {}
    )
    empty_anomalies = anomaly_df.iloc[0:0]

    records = []
    for awc_code, snap_group in snapshot_df.sort_values("period").groupby("awc_code", sort=False):
        snap_group = snap_group.reset_index(drop=True)
        if snap_group["period"].iloc[-1] != latest_period:
            continue  # centre has no row in the latest period; nothing to alert on

        current_row = snap_group.iloc[-1]
        previous_row = snap_group.iloc[-2] if len(snap_group) >= 2 else None

        risk_group = risk_by_awc_code[awc_code]
        current_risk = risk_group.loc[current_row["period"]]
        previous_risk = None
        if previous_row is not None and previous_row["period"] in risk_group.index:
            previous_risk = risk_group.loc[previous_row["period"]]

        recent_periods = set(snap_group["period"].iloc[-window:])
        centre_anomalies = anomaly_by_awc_code.get(awc_code, empty_anomalies)
        recent_anomalies = centre_anomalies[centre_anomalies["period"].isin(recent_periods)] if not centre_anomalies.empty else centre_anomalies

        recent_anomaly_count = len(recent_anomalies)
        current_risk_level = current_risk["risk_level"]
        previous_risk_level = previous_risk["risk_level"] if previous_risk is not None else None

        record = {
            "awc_code": awc_code,
            "current_period": _period_label(current_row["period"]),
            "previous_period": _period_label(previous_row["period"]) if previous_row is not None else None,
            **{k: current_row.get(k) for k in IDENTITY_FIELDS},
            "risk_level": current_risk_level,
            "risk_flags": current_risk["risk_flags"],
            "risk_flag_count": int(current_risk["risk_flag_count"]),
            "previous_risk_period": _period_label(previous_row["period"]) if previous_risk is not None else None,
            "previous_risk_level": previous_risk_level,
            "previous_risk_flags": previous_risk["risk_flags"] if previous_risk is not None else None,
            "previous_risk_flag_count": int(previous_risk["risk_flag_count"]) if previous_risk is not None else None,
            "risk_direction": risk_direction(current_risk_level, previous_risk_level),
            "recent_anomaly_count": recent_anomaly_count,
            "latest_anomaly_period": _period_label(recent_anomalies["period"].max()) if recent_anomaly_count else None,
            "recent_anomaly_metrics": "|".join(sorted(recent_anomalies["metric_name"].unique())) if recent_anomaly_count else None,
            "recent_flag_reasons": "|".join(sorted(recent_anomalies["flag_reason"].unique())) if recent_anomaly_count else None,
            "alert_scenario": compute_alert_scenario(current_risk_level, previous_risk_level, recent_anomaly_count, alerts_config),
        }

        for field in METRIC_DELTA_FIELDS:
            current_value = current_row.get(field)
            previous_value = previous_row.get(field) if previous_row is not None else None
            record[field] = current_value
            record[f"previous_{field}"] = previous_value
            record[f"delta_{field}"] = (
                current_value - previous_value if _is_num(current_value) and _is_num(previous_value) else None
            )

        records.append(record)

    return pd.DataFrame.from_records(records, columns=ALERTS_LATEST_COLUMNS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute AWC anomaly flags, risk snapshots, and latest alerts.")
    parser.add_argument("--folder", default=None, help="Folder containing the harmonized AWC parquet output.")
    parser.add_argument(
        "--config-file",
        default="awc_pipeline_config.json",
        help="Name or path of the pipeline config JSON.",
    )
    parser.add_argument(
        "--summary-file",
        default="anomaly_risk_flags_run_summary.json",
        help="Name or path of the JSON run summary.",
    )
    return parser.parse_args()


def resolve_output_path(folder: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else folder / path


def main() -> None:
    args = parse_args()
    folder = resolve_folder(args.folder)
    config_file = resolve_output_path(folder, args.config_file)
    summary_file = resolve_output_path(folder, args.summary_file)

    snapshot_file = folder / "AWC_HARMONIZED_MERGED.parquet"
    if not snapshot_file.exists():
        raise FileNotFoundError(f"Required harmonized Parquet file is missing: {snapshot_file}")

    config = load_pipeline_config(config_file)
    snapshot_df = monthly_snapshot_frame(pd.read_parquet(snapshot_file))

    anomaly_df = compute_anomaly_flags(snapshot_df, config)
    risk_df = compute_risk_snapshot(snapshot_df, config)
    alerts_df = compute_alerts_latest(snapshot_df, risk_df, anomaly_df, config)

    outputs = {
        "AWC_ANOMALY_FLAGS": anomaly_df,
        "AWC_RISK_FLAGS_LATEST": risk_df,
        "AWC_ALERTS_LATEST": alerts_df,
    }
    for stem, df in outputs.items():
        df.to_csv(folder / f"{stem}.csv", index=False)
        df.to_parquet(folder / f"{stem}.parquet", index=False)

    risk_level_counts = risk_df["risk_level"].value_counts().to_dict() if not risk_df.empty else {}
    alert_scenario_counts = alerts_df["alert_scenario"].value_counts().to_dict() if not alerts_df.empty else {}
    summary = {
        "pipeline": "anomaly_risk_flags",
        "run_timestamp_utc": utc_now_iso(),
        "folder": str(folder),
        "config_file": str(config_file),
        "snapshot_rows": int(len(snapshot_df)),
        "anomaly_flag_rows": int(len(anomaly_df)),
        "risk_snapshot_rows": int(len(risk_df)),
        "alerts_latest_rows": int(len(alerts_df)),
        "risk_level_counts": risk_level_counts,
        "alert_scenario_counts": alert_scenario_counts,
    }
    write_run_summary(summary_file, summary)

    print(f"Anomaly flags: {len(anomaly_df)} rows -> {folder / 'AWC_ANOMALY_FLAGS.parquet'}")
    print(f"Risk snapshot: {len(risk_df)} rows -> {folder / 'AWC_RISK_FLAGS_LATEST.parquet'}")
    print(f"Alerts latest: {len(alerts_df)} rows -> {folder / 'AWC_ALERTS_LATEST.parquet'}")
    print(f"Run summary saved at: {summary_file}")


if __name__ == "__main__":
    main()
