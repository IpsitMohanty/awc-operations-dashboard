"""Cross-check anomaly_risk_flags.py output against the synthetic generator's
ground-truth anomaly log and produce a small markdown validation report.

Usage:
    python scripts/validate_anomaly_detection.py --folder synthetic_data

Requires synthetic_anomaly_log.csv (written by generate_synthetic_data.py) and
AWC_ANOMALY_FLAGS.csv (written by anomaly_risk_flags.py) to both exist in
--folder.

Note on scope: generate_synthetic_data.py's row-count-drop month is designed
to make harmonize_merge_awc.py raise "Abnormal row-count drift detected" for
the whole folder. Row-level anomalies injected into that specific month never
reach fct_awc_monthly_snapshot (harmonize refuses to merge any file until
that one is fixed or removed), so they cannot be evaluated here and are
reported separately rather than counted against recall.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate_synthetic_data import ROW_COUNT_DROP_PERIOD  # noqa: E402

DATA_QUALITY_METRICS = {
    "MEASURED_EXCEEDS_ACTIVE",
    "MEASURING_EFFICIENCY_OUT_OF_RANGE",
    "NEGATIVE_SUW_COUNT",
    "NEGATIVE_MUW_COUNT",
    "NEGATIVE_SEVERELY_STUNTED_COUNT",
    "NEGATIVE_MODERATELY_STUNTED_COUNT",
    "NEGATIVE_SAM_COUNT",
    "NEGATIVE_MAM_COUNT",
    "NEGATIVE_SUW_RATE_PCT",
    "NEGATIVE_SAM_RATE_PCT",
    "NEGATIVE_MAM_RATE_PCT",
}


def _build_distress_section(distressed_path: Path, alerts_path: Path) -> list:
    """Cross-checks the latest-period alerts mart against the distressed-centre
    log: how much of the organic HIGH-risk / escalation signal actually traces
    back to the deliberately-declining cluster, vs. incidental population
    noise or unrelated pipeline effects (e.g. the November schema-drift
    month's artificially low stunting rate briefly deflating risk levels)."""
    if not distressed_path.exists() or not alerts_path.exists():
        return [
            "## Distressed-centre cluster",
            "",
            f"Skipped: `{distressed_path.name}` or `{alerts_path.name}` not found in this folder.",
            "",
        ]

    distressed = pd.read_csv(distressed_path, dtype={"awc_code": str})
    alerts = pd.read_csv(alerts_path, dtype={"awc_code": str})
    distressed_codes = set(distressed["awc_code"])

    lines = [
        "## Distressed-centre cluster: organic HIGH risk",
        "",
        f"`{len(distressed)}` centres ({(distressed['distress_severity'] == 'severe').sum()} severe, "
        f"{(distressed['distress_severity'] == 'moderate').sum()} moderate) decline over the year per "
        "`scripts/generate_synthetic_data.py`'s distress trajectory. Cross-checking the latest-period",
        "`mart_awc_alerts_latest` against that list:",
        "",
        "| risk_level / alert_scenario | count | from distressed cluster |",
        "|---|---:|---:|",
    ]
    high = alerts[alerts["risk_level"] == "HIGH"]
    lines.append(f"| HIGH risk_level | {len(high)} | {high['awc_code'].isin(distressed_codes).sum()} |")
    for scenario in ["NEW_HIGH_RISK", "PERSISTENT_HIGH_RISK", "RISK_ESCALATED", "ANOMALY_PRESSURE"]:
        subset = alerts[alerts["alert_scenario"] == scenario]
        in_distressed = subset["awc_code"].isin(distressed_codes).sum()
        lines.append(f"| {scenario} | {len(subset)} | {in_distressed} |")

    escalated = alerts[alerts["alert_scenario"] == "RISK_ESCALATED"]
    escalated_from_distress = int(escalated["awc_code"].isin(distressed_codes).sum())
    lines += [
        "",
        "`NEW_HIGH_RISK` and `PERSISTENT_HIGH_RISK` should trace almost entirely to the distressed "
        "cluster - that's the point of it. `RISK_ESCALATED`, if its count is large and its "
        f"distressed-cluster share is low ({escalated_from_distress}/{len(escalated)} here), is most "
        "likely dominated by an unrelated effect: the November schema-drift month "
        "(`COLUMN_RENAME_PERIOD`) silently zeroes `moderately_stunted_count` for every centre that "
        "month, artificially deflating November's stunting rate and risk level for the whole "
        "population; December's rate reverts to normal, which reads as a LOW->MEDIUM escalation for "
        "many centres that were never actually declining. This is a real interaction between two "
        "independently-intentional anomalies, not a bug in either one - verify the actual cause with "
        "`risk['stunting_rate_pct'].groupby(risk['period']).mean()` before assuming it's distress-driven.",
        "",
    ]
    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate anomaly_risk_flags.py recall against synthetic ground truth.")
    parser.add_argument("--folder", default="synthetic_data", help="Folder containing the synthetic dataset and pipeline outputs.")
    parser.add_argument("--report-file", default="ANOMALY_DETECTION_VALIDATION.md", help="Name or path of the markdown report to write.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    folder = Path(args.folder).expanduser().resolve()
    report_path = folder / args.report_file if not Path(args.report_file).is_absolute() else Path(args.report_file)

    ground_truth_path = folder / "synthetic_anomaly_log.csv"
    flags_path = folder / "AWC_ANOMALY_FLAGS.csv"
    if not ground_truth_path.exists():
        raise FileNotFoundError(f"Missing {ground_truth_path} - run scripts/generate_synthetic_data.py first.")
    if not flags_path.exists():
        raise FileNotFoundError(f"Missing {flags_path} - run anomaly_risk_flags.py against {folder} first.")

    ground_truth = pd.read_csv(ground_truth_path)
    flags = pd.read_csv(flags_path)

    distressed_path = folder / "synthetic_distressed_centres.csv"
    alerts_path = folder / "AWC_ALERTS_LATEST.csv"
    distress_section = _build_distress_section(distressed_path, alerts_path)

    drop_period_label = f"{ROW_COUNT_DROP_PERIOD[0]:04d}-{ROW_COUNT_DROP_PERIOD[1]:02d}"
    unreachable = ground_truth[ground_truth["period"] == drop_period_label]
    evaluable = ground_truth[ground_truth["period"] != drop_period_label].copy()

    flags = flags.copy()
    flags["period"] = pd.to_datetime(flags["period"]).dt.strftime("%Y-%m")
    flagged_pairs = set(zip(flags["awc_code"], flags["period"]))
    dq_flagged_pairs = set(zip(
        flags.loc[flags["metric_name"].isin(DATA_QUALITY_METRICS), "awc_code"],
        flags.loc[flags["metric_name"].isin(DATA_QUALITY_METRICS), "period"],
    ))
    rate_flagged_pairs = set(zip(
        flags.loc[~flags["metric_name"].isin(DATA_QUALITY_METRICS), "awc_code"],
        flags.loc[~flags["metric_name"].isin(DATA_QUALITY_METRICS), "period"],
    ))

    evaluable["caught"] = list(zip(evaluable["awc_code"], evaluable["period"]))
    evaluable["caught_any"] = evaluable["caught"].isin(flagged_pairs)
    evaluable["caught_data_quality"] = evaluable["caught"].isin(dq_flagged_pairs)
    evaluable["caught_rate_threshold"] = evaluable["caught"].isin(rate_flagged_pairs)

    by_kind = evaluable.groupby("anomaly_kind").agg(
        injected=("caught_any", "size"),
        caught=("caught_any", "sum"),
        caught_by_data_quality_flag=("caught_data_quality", "sum"),
        caught_by_rate_threshold_flag=("caught_rate_threshold", "sum"),
    )
    by_kind["recall_pct"] = (by_kind["caught"] / by_kind["injected"] * 100).round(1)

    total_injected = len(evaluable)
    total_caught = int(evaluable["caught_any"].sum())
    overall_recall = round(total_caught / total_injected * 100, 1) if total_injected else 0.0

    injected_pairs = set(evaluable["caught"])
    flags["pair"] = list(zip(flags["awc_code"], flags["period"]))
    flags["from_injected_anomaly"] = flags["pair"].isin(injected_pairs)
    flags["is_data_quality_flag"] = flags["metric_name"].isin(DATA_QUALITY_METRICS)

    volume_breakdown = flags.groupby(["is_data_quality_flag", "from_injected_anomaly"]).size().rename("flag_rows")

    lines = [
        "# Anomaly Detection Validation Report",
        "",
        "Generated by `scripts/validate_anomaly_detection.py`, cross-checking `anomaly_risk_flags.py`'s",
        "output (`AWC_ANOMALY_FLAGS.csv`) against the synthetic generator's ground-truth injection log",
        "(`synthetic_anomaly_log.csv`).",
        "",
        "## Recall by injected anomaly kind",
        "",
        "\"Caught\" means at least one row exists in `fct_awc_anomaly_flags` for that `(awc_code, period)`",
        "- either a dedicated data-quality flag or a rate/efficiency threshold flag.",
        "",
        "| anomaly_kind | injected | caught | recall | via data-quality flag | via rate/drift flag |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for kind, row in by_kind.iterrows():
        lines.append(
            f"| {kind} | {int(row['injected'])} | {int(row['caught'])} | {row['recall_pct']:.1f}% | "
            f"{int(row['caught_by_data_quality_flag'])} | {int(row['caught_by_rate_threshold_flag'])} |"
        )
    lines.append(f"| **overall** | **{total_injected}** | **{total_caught}** | **{overall_recall:.1f}%** | | |")
    lines += [
        "",
        f"- {len(unreachable)} row-level anomalies were injected into `{drop_period_label}` "
        "(the deliberate row-count-drop month) and are excluded from the table above: "
        "`harmonize_merge_awc.py` refuses to merge *any* file in the folder while that one fails its "
        "row-count drift check, so those rows never reach `fct_awc_monthly_snapshot` and can't be "
        "evaluated. This is treated as expected behavior, not a detector miss - the drift guard blocks "
        "the whole batch before per-row anomaly scoring ever runs on the bad file.",
        "",
        "## Flag volume: injected anomalies vs. normal-data threshold crossings",
        "",
        "Rate/efficiency-threshold and drift flags are expected to also fire on rows the generator did",
        "*not* deliberately corrupt - a centre's `stunting_rate_pct` swinging past the configured",
        "5-point delta threshold from one month to the next by ordinary random variation is a real,",
        "correctly-detected drift event, not a false positive. Data-quality flags "
        "(`MEASURED_EXCEEDS_ACTIVE`, `MEASURING_EFFICIENCY_OUT_OF_RANGE`, `NEGATIVE_*`), by contrast,",
        "check hard invariants that should never be violated by non-corrupted data, so almost all of",
        "them are expected to trace back to an injected anomaly.",
        "",
        "| flag type | from an injected anomaly row | from normal generated data | total |",
        "|---|---:|---:|---:|",
    ]
    for is_dq, label in ((True, "data-quality"), (False, "rate/drift threshold")):
        from_injected = int(volume_breakdown.get((is_dq, True), 0))
        from_normal = int(volume_breakdown.get((is_dq, False), 0))
        lines.append(f"| {label} | {from_injected} | {from_normal} | {from_injected + from_normal} |")

    lines += [
        "",
        f"Total flag rows in `fct_awc_anomaly_flags`: {len(flags)}.",
        "",
    ]
    lines += distress_section
    lines += [
        "## Notes",
        "",
        "- `HIGH`-risk classification, `NEW_HIGH_RISK`, and `PERSISTENT_HIGH_RISK` are also exercised",
        "  directly in `tests/` with small hand-built fixtures, independent of what this particular",
        "  seed's distressed cluster happens to produce.",
        "- Recall for `measured_exceeds_active`, `efficiency_out_of_range`, and `negative_count` is",
        "  expected to be at or near 100% by construction - each has a dedicated data-quality check.",
        "  `extreme_rate_spike` directly mutates a tracked rate/count field, so it is reliably (though",
        "  not perfectly) caught by the rate/drift threshold flags.",
        "- `population_spike` recall is genuinely weak, and not just \"harder to detect\": it only mutates",
        "  `TOTAL ACTIVE CHILDREN (0-6 YEARS)`, which is not one of the five metrics",
        "  `anomaly_thresholds` tracks (`measuring_efficiency_0_6_years_pct`, `suw/sam/mam_rate_pct`,",
        "  `stunting_rate_pct`), and the synthetic generator does not recompute the reported measuring",
        "  efficiency to match the inflated population, so that mismatch is invisible to every flag",
        "  implemented here. Manually inspecting the population_spike rows that *were* flagged shows",
        "  they were caught by unrelated, coincidental movement in `stunting_rate_pct` or other rates in",
        "  the same row - not genuine detection of the population spike itself. Catching this class of",
        "  anomaly for real would need a population-count drift check, which `awc_pipeline_config.json`",
        "  does not currently define a threshold for and is out of scope here.",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Overall recall: {total_caught}/{total_injected} ({overall_recall:.1f}%)")
    print(f"Report written to: {report_path}")


if __name__ == "__main__":
    main()
