from awc_pipeline_utils import DEFAULT_PIPELINE_CONFIG, evaluate_anomaly_flag

ANOMALY_THRESHOLDS = DEFAULT_PIPELINE_CONFIG["anomaly_thresholds"]


class TestEvaluateAnomalyFlag:
    def test_no_previous_or_baseline_never_flags(self):
        result = evaluate_anomaly_flag(current_value=999.0, previous_value=None, rolling_baseline_value=None, threshold_value=5)
        assert result == {
            "delta_value": None, "absolute_delta_value": None, "baseline_gap_value": None, "flag_reason": None,
        }

    def test_missing_current_value_short_circuits(self):
        result = evaluate_anomaly_flag(current_value=None, previous_value=10, rolling_baseline_value=10, threshold_value=5)
        assert result["flag_reason"] is None
        assert result["delta_value"] is None

    def test_nan_current_value_short_circuits(self):
        result = evaluate_anomaly_flag(current_value=float("nan"), previous_value=10, rolling_baseline_value=10, threshold_value=5)
        assert result["flag_reason"] is None

    def test_delta_at_threshold_does_not_flag(self):
        result = evaluate_anomaly_flag(current_value=15.0, previous_value=10.0, rolling_baseline_value=None, threshold_value=5.0)
        assert result["delta_value"] == 5.0
        assert result["flag_reason"] is None

    def test_delta_just_over_threshold_flags_rise(self):
        result = evaluate_anomaly_flag(current_value=15.01, previous_value=10.0, rolling_baseline_value=None, threshold_value=5.0)
        assert result["flag_reason"] == "PERIOD_OVER_PERIOD_RISE"

    def test_delta_just_over_negative_threshold_flags_drop(self):
        result = evaluate_anomaly_flag(current_value=4.99, previous_value=10.0, rolling_baseline_value=None, threshold_value=5.0)
        assert result["flag_reason"] == "PERIOD_OVER_PERIOD_DROP"

    def test_baseline_gap_over_threshold_flags_independent_of_delta(self):
        # previous period is close (no delta flag) but the rolling baseline is far away
        result = evaluate_anomaly_flag(current_value=15.0, previous_value=14.0, rolling_baseline_value=5.0, threshold_value=5.0)
        assert result["flag_reason"] == "BASELINE_DEVIATION_RISE"

    def test_baseline_gap_at_threshold_does_not_flag(self):
        result = evaluate_anomaly_flag(current_value=10.0, previous_value=10.0, rolling_baseline_value=5.0, threshold_value=5.0)
        assert result["flag_reason"] is None

    def test_both_delta_and_baseline_combine_with_plus(self):
        result = evaluate_anomaly_flag(current_value=20.0, previous_value=5.0, rolling_baseline_value=5.0, threshold_value=5.0)
        assert result["flag_reason"] == "PERIOD_OVER_PERIOD_RISE+BASELINE_DEVIATION_RISE"

    def test_drop_below_baseline_flags_deviation_drop(self):
        result = evaluate_anomaly_flag(current_value=0.0, previous_value=1.0, rolling_baseline_value=10.0, threshold_value=5.0)
        assert result["flag_reason"] == "BASELINE_DEVIATION_DROP"

    def test_real_config_efficiency_threshold_boundary(self):
        threshold = ANOMALY_THRESHOLDS["MEASURING EFFICIENCY (0-6 YEARS) (%)"]
        assert threshold == 20
        # previous=100: a delta of exactly 20 points (down to 80.0) must not flag,
        # a hair past it (79.99) must.
        at_threshold = evaluate_anomaly_flag(current_value=80.0, previous_value=100.0, rolling_baseline_value=None, threshold_value=threshold)
        just_past_threshold = evaluate_anomaly_flag(current_value=79.99, previous_value=100.0, rolling_baseline_value=None, threshold_value=threshold)
        assert at_threshold["flag_reason"] is None
        assert just_past_threshold["flag_reason"] == "PERIOD_OVER_PERIOD_DROP"

    def test_real_config_rate_thresholds_are_five_points(self):
        for key in ("suw_rate_pct", "sam_rate_pct", "mam_rate_pct", "stunting_rate_pct"):
            assert ANOMALY_THRESHOLDS[key] == 5
