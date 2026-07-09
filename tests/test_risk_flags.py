import pytest

from awc_pipeline_utils import (
    DEFAULT_PIPELINE_CONFIG,
    classify_measurement_gap,
    compute_risk_level,
    evaluate_risk_flags,
)

RISK_THRESHOLDS = DEFAULT_PIPELINE_CONFIG["risk_thresholds"]
RISK_LEVEL_RULES = DEFAULT_PIPELINE_CONFIG["risk_level_rules"]


class TestClassifyMeasurementGap:
    def test_just_above_high_threshold_is_not_flagged(self):
        assert classify_measurement_gap(80.0, RISK_THRESHOLDS) is None

    def test_just_below_high_threshold_is_high_gap(self):
        assert classify_measurement_gap(79.9, RISK_THRESHOLDS) == "HIGH_MEASUREMENT_GAP"

    def test_at_critical_threshold_is_high_not_critical(self):
        assert classify_measurement_gap(60.0, RISK_THRESHOLDS) == "HIGH_MEASUREMENT_GAP"

    def test_just_below_critical_threshold_is_critical(self):
        assert classify_measurement_gap(59.9, RISK_THRESHOLDS) == "CRITICAL_MEASUREMENT_GAP"

    def test_perfect_efficiency_is_not_flagged(self):
        assert classify_measurement_gap(100.0, RISK_THRESHOLDS) is None

    def test_missing_value_is_not_flagged(self):
        assert classify_measurement_gap(None, RISK_THRESHOLDS) is None
        assert classify_measurement_gap(float("nan"), RISK_THRESHOLDS) is None


class TestEvaluateRiskFlags:
    @pytest.mark.parametrize(
        "column,threshold_key,flag_name",
        [
            ("suw_rate_pct", "high_suw", "HIGH_SUW_RATE"),
            ("sam_rate_pct", "high_sam", "HIGH_SAM_RATE"),
            ("mam_rate_pct", "high_mam", "HIGH_MAM_RATE"),
            ("stunting_rate_pct", "high_stunting", "HIGH_STUNTING_RATE"),
        ],
    )
    def test_rate_flag_boundaries(self, column, threshold_key, flag_name):
        threshold = RISK_THRESHOLDS[threshold_key]
        row_at_threshold = {"measuring_efficiency_0_6_years_pct": 100.0, column: threshold}
        row_above_threshold = {"measuring_efficiency_0_6_years_pct": 100.0, column: threshold + 0.1}
        assert evaluate_risk_flags(row_at_threshold, RISK_THRESHOLDS) == []
        assert evaluate_risk_flags(row_above_threshold, RISK_THRESHOLDS) == [flag_name]

    def test_multiple_flags_accumulate_in_order(self):
        row = {
            "measuring_efficiency_0_6_years_pct": 50.0,  # CRITICAL_MEASUREMENT_GAP
            "suw_rate_pct": 20.0,  # HIGH_SUW_RATE
            "sam_rate_pct": 10.0,  # HIGH_SAM_RATE
            "mam_rate_pct": 0.0,
            "stunting_rate_pct": 0.0,
        }
        assert evaluate_risk_flags(row, RISK_THRESHOLDS) == [
            "CRITICAL_MEASUREMENT_GAP", "HIGH_SUW_RATE", "HIGH_SAM_RATE",
        ]

    def test_clean_row_has_no_flags(self):
        row = {
            "measuring_efficiency_0_6_years_pct": 100.0,
            "suw_rate_pct": 1.0,
            "sam_rate_pct": 0.5,
            "mam_rate_pct": 1.0,
            "stunting_rate_pct": 5.0,
        }
        assert evaluate_risk_flags(row, RISK_THRESHOLDS) == []

    def test_missing_rate_values_are_skipped_not_flagged(self):
        row = {"measuring_efficiency_0_6_years_pct": 100.0}
        assert evaluate_risk_flags(row, RISK_THRESHOLDS) == []


class TestComputeRiskLevel:
    @pytest.mark.parametrize(
        "flag_count,expected_level",
        [(0, "LOW"), (1, "MEDIUM"), (2, "MEDIUM"), (3, "HIGH"), (5, "HIGH")],
    )
    def test_boundaries(self, flag_count, expected_level):
        assert compute_risk_level(flag_count, RISK_LEVEL_RULES) == expected_level
