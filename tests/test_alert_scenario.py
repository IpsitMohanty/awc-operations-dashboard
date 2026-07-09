from awc_pipeline_utils import DEFAULT_PIPELINE_CONFIG, compute_alert_scenario, risk_direction

ALERTS_CONFIG = DEFAULT_PIPELINE_CONFIG["alerts"]


class TestComputeAlertScenario:
    def test_first_ever_period_high_is_new_high_risk(self):
        assert compute_alert_scenario("HIGH", None, 0, ALERTS_CONFIG) == "NEW_HIGH_RISK"

    def test_first_ever_period_not_high_is_new_monitoring(self):
        assert compute_alert_scenario("LOW", None, 0, ALERTS_CONFIG) == "NEW_MONITORING"
        assert compute_alert_scenario("MEDIUM", None, 0, ALERTS_CONFIG) == "NEW_MONITORING"

    def test_becomes_high_from_medium_is_new_high_risk(self):
        assert compute_alert_scenario("HIGH", "MEDIUM", 0, ALERTS_CONFIG) == "NEW_HIGH_RISK"

    def test_becomes_high_from_low_is_new_high_risk(self):
        assert compute_alert_scenario("HIGH", "LOW", 0, ALERTS_CONFIG) == "NEW_HIGH_RISK"

    def test_stays_high_is_persistent_high_risk(self):
        assert compute_alert_scenario("HIGH", "HIGH", 0, ALERTS_CONFIG) == "PERSISTENT_HIGH_RISK"

    def test_low_to_medium_is_risk_escalated(self):
        assert compute_alert_scenario("MEDIUM", "LOW", 0, ALERTS_CONFIG) == "RISK_ESCALATED"

    def test_medium_to_high_is_new_high_risk_not_escalated(self):
        # HIGH always routes through NEW_HIGH_RISK, taking priority over the generic escalation branch.
        assert compute_alert_scenario("HIGH", "MEDIUM", 0, ALERTS_CONFIG) == "NEW_HIGH_RISK"

    def test_high_to_medium_is_risk_improved(self):
        assert compute_alert_scenario("MEDIUM", "HIGH", 0, ALERTS_CONFIG) == "RISK_IMPROVED"

    def test_medium_to_low_is_risk_improved(self):
        assert compute_alert_scenario("LOW", "MEDIUM", 0, ALERTS_CONFIG) == "RISK_IMPROVED"

    def test_unchanged_low_with_high_anomaly_pressure(self):
        threshold = ALERTS_CONFIG["high_recent_anomaly_count"]
        assert compute_alert_scenario("LOW", "LOW", threshold, ALERTS_CONFIG) == "ANOMALY_PRESSURE"

    def test_unchanged_low_below_anomaly_pressure_threshold_is_stable(self):
        threshold = ALERTS_CONFIG["high_recent_anomaly_count"]
        assert compute_alert_scenario("LOW", "LOW", threshold - 1, ALERTS_CONFIG) == "STABLE"

    def test_unchanged_medium_with_high_anomaly_pressure(self):
        threshold = ALERTS_CONFIG["high_recent_anomaly_count"]
        assert compute_alert_scenario("MEDIUM", "MEDIUM", threshold, ALERTS_CONFIG) == "ANOMALY_PRESSURE"


class TestRiskDirection:
    def test_no_previous_is_new(self):
        assert risk_direction("HIGH", None) == "NEW"

    def test_worsened(self):
        assert risk_direction("HIGH", "LOW") == "WORSENED"
        assert risk_direction("MEDIUM", "LOW") == "WORSENED"

    def test_improved(self):
        assert risk_direction("LOW", "HIGH") == "IMPROVED"
        assert risk_direction("MEDIUM", "HIGH") == "IMPROVED"

    def test_unchanged(self):
        assert risk_direction("MEDIUM", "MEDIUM") == "UNCHANGED"
        assert risk_direction("LOW", "LOW") == "UNCHANGED"
        assert risk_direction("HIGH", "HIGH") == "UNCHANGED"
