import pandas as pd
import pytest

from anomaly_risk_flags import compute_alerts_latest, compute_anomaly_flags, compute_risk_snapshot
from awc_pipeline_utils import DEFAULT_PIPELINE_CONFIG

CONFIG = DEFAULT_PIPELINE_CONFIG

CLEAN_RATES = {
    "measuring_efficiency_0_6_years_pct": 100.0,
    "suw_rate_pct": 1.0,
    "sam_rate_pct": 0.5,
    "mam_rate_pct": 1.0,
    "stunting_rate_pct": 4.0,
}

# efficiency crosses CRITICAL_MEASUREMENT_GAP (<60), suw/sam cross their HIGH_* rate
# thresholds -> exactly 3 risk flags -> HIGH. Also a sharp enough move on all three to
# trip the period-over-period anomaly delta threshold.
SPIKED_RATES = {
    "measuring_efficiency_0_6_years_pct": 50.0,
    "suw_rate_pct": 20.0,
    "sam_rate_pct": 10.0,
    "mam_rate_pct": 1.0,
    "stunting_rate_pct": 4.0,
}


def _row(awc_code: str, period: str, rates: dict, active: int = 100, measured: int = None) -> dict:
    measured = active if measured is None else measured
    return {
        "awc_code": awc_code,
        "period": pd.Timestamp(period),
        "state_name": "Testland",
        "district_name": "Testford",
        "project_name": "Testville",
        "sector_name": "Testburg",
        "awc_name": f"Test AWC {awc_code[-1]}",
        "source_file": "TEST_FIXTURE.csv",
        "total_active_children_0_6_years": active,
        "total_active_children_measured_0_6_years": measured,
        "total_active_children_measured_0_5_years": 80,
        "suw_count": None, "muw_count": None,
        "severely_stunted_count": None, "moderately_stunted_count": None,
        "sam_count": None, "mam_count": None,
        **rates,
    }


@pytest.fixture
def snapshot_df() -> pd.DataFrame:
    rows = [
        _row("77000000001", "2030-01-01", CLEAN_RATES),
        _row("77000000001", "2030-02-01", CLEAN_RATES),
        _row("77000000001", "2030-03-01", SPIKED_RATES, active=100, measured=50),
        _row("77000000002", "2030-01-01", CLEAN_RATES),
        _row("77000000002", "2030-02-01", CLEAN_RATES),
        _row("77000000002", "2030-03-01", CLEAN_RATES),
    ]
    return pd.DataFrame(rows)


class TestEndToEndPipeline:
    def test_anomaly_flags_only_fire_in_the_spike_month(self, snapshot_df):
        anomaly_df = compute_anomaly_flags(snapshot_df, CONFIG)

        centre1_flags = anomaly_df[anomaly_df["awc_code"] == "77000000001"]
        assert set(centre1_flags["period"]) == {pd.Timestamp("2030-03-01")}
        assert set(centre1_flags["metric_name"]) == {
            "MEASURING EFFICIENCY (0-6 YEARS) (%)", "suw_rate_pct", "sam_rate_pct",
        }
        assert (centre1_flags["flag_reason"].str.contains("PERIOD_OVER_PERIOD")).all()

        # centre 2 never moves, so it should never appear in the anomaly table
        assert (anomaly_df["awc_code"] == "77000000002").sum() == 0

    def test_risk_snapshot_reaches_high_only_for_the_spiked_centre_month(self, snapshot_df):
        risk_df = compute_risk_snapshot(snapshot_df, CONFIG)

        centre1 = risk_df[risk_df["awc_code"] == "77000000001"].set_index("period")
        assert centre1.loc[pd.Timestamp("2030-01-01"), "risk_level"] == "LOW"
        assert centre1.loc[pd.Timestamp("2030-02-01"), "risk_level"] == "LOW"
        assert centre1.loc[pd.Timestamp("2030-03-01"), "risk_level"] == "HIGH"
        assert centre1.loc[pd.Timestamp("2030-03-01"), "risk_flag_count"] == 3

        centre2 = risk_df[risk_df["awc_code"] == "77000000002"]
        assert (centre2["risk_level"] == "LOW").all()

    def test_alerts_latest_flags_the_newly_high_risk_centre(self, snapshot_df):
        risk_df = compute_risk_snapshot(snapshot_df, CONFIG)
        anomaly_df = compute_anomaly_flags(snapshot_df, CONFIG)
        alerts_df = compute_alerts_latest(snapshot_df, risk_df, anomaly_df, CONFIG)

        # exactly one row per centre, both present in the latest period (2030-03)
        assert len(alerts_df) == 2
        assert set(alerts_df["current_period"]) == {"2030-03"}

        centre1 = alerts_df[alerts_df["awc_code"] == "77000000001"].iloc[0]
        assert centre1["risk_level"] == "HIGH"
        assert centre1["previous_risk_level"] == "LOW"
        assert centre1["risk_direction"] == "WORSENED"
        assert centre1["alert_scenario"] == "NEW_HIGH_RISK"
        assert centre1["recent_anomaly_count"] == 3

        centre2 = alerts_df[alerts_df["awc_code"] == "77000000002"].iloc[0]
        assert centre2["risk_level"] == "LOW"
        assert centre2["previous_risk_level"] == "LOW"
        assert centre2["risk_direction"] == "UNCHANGED"
        assert centre2["alert_scenario"] == "STABLE"
        assert centre2["recent_anomaly_count"] == 0

    def test_alerts_latest_excludes_centres_missing_from_the_latest_period(self, snapshot_df):
        # a third centre with no row in the latest period should not appear in the mart
        extra = _row("77000000003", "2030-01-01", CLEAN_RATES)
        df = pd.concat([snapshot_df, pd.DataFrame([extra])], ignore_index=True)

        risk_df = compute_risk_snapshot(df, CONFIG)
        anomaly_df = compute_anomaly_flags(df, CONFIG)
        alerts_df = compute_alerts_latest(df, risk_df, anomaly_df, CONFIG)

        assert "77000000003" not in set(alerts_df["awc_code"])
        assert len(alerts_df) == 2
