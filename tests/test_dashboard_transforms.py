from datetime import date

import pandas as pd

import awc_dashboard_streamlit as dash


class TestPeriodLabel:
    def test_sqlite_text_value_truncated(self):
        assert dash._period_label("2024-01-01 00:00:00") == "2024-01"

    def test_sqlite_text_value_date_only(self):
        assert dash._period_label("2024-12-01") == "2024-12"

    def test_postgres_date_value_formatted(self):
        assert dash._period_label(date(2024, 3, 1)) == "2024-03"

    def test_none_passes_through(self):
        assert dash._period_label(None) is None


class TestAdaptSql:
    def test_sqlite_leaves_placeholders_unchanged(self):
        assert dash._adapt_sql("select * from t where a = ? and b = ?", use_postgres=False) == "select * from t where a = ? and b = ?"

    def test_postgres_translates_placeholders(self):
        assert dash._adapt_sql("select * from t where a = ? and b = ?", use_postgres=True) == "select * from t where a = %s and b = %s"

    def test_no_placeholders_is_a_no_op(self):
        assert dash._adapt_sql("select * from t", use_postgres=True) == "select * from t"


class TestLikeOperator:
    def test_sqlite_uses_like(self):
        assert dash.like_operator(use_postgres=False) == "like"

    def test_postgres_uses_ilike(self):
        assert dash.like_operator(use_postgres=True) == "ilike"


class TestBuildFilterClause:
    def test_no_filters_produces_no_where_clause(self):
        where_sql, params = dash.build_filter_clause({})
        assert where_sql == ""
        assert params == []

    def test_period_is_expanded_to_first_of_month(self):
        where_sql, params = dash.build_filter_clause({"period": ["2024-03"]})
        assert "period = ?" in where_sql
        assert params == ["2024-03-01"]

    def test_district_and_awc_name_combine_with_and(self):
        where_sql, params = dash.build_filter_clause({"district": ["Kirtipur"], "awc_name": ["Kiva"]}, use_postgres=False)
        assert where_sql.startswith(" where ")
        assert " and " in where_sql
        assert "district_name = ?" in where_sql
        assert "awc_name like ?" in where_sql
        assert params == ["Kirtipur", "%Kiva%"]

    def test_awc_name_uses_ilike_on_postgres(self):
        where_sql, _ = dash.build_filter_clause({"awc_name": ["Kiva"]}, use_postgres=True)
        assert "awc_name ilike ?" in where_sql


class TestGeographyFilterClause:
    def test_empty_filters_produce_no_where_clause(self):
        where_sql, params = dash._geography_filter_clause("", "", "", "", "", "", use_postgres=False)
        assert where_sql == ""
        assert params == []

    def test_all_filters_applied_in_order(self):
        where_sql, params = dash._geography_filter_clause(
            "Sundarvana", "Kirtipur", "Kirtipur", "Kivapada", "77001010101", "", use_postgres=False
        )
        assert params == ["Sundarvana", "Kirtipur", "Kirtipur", "Kivapada", "77001010101"]
        assert where_sql.count(" and ") == 4


class TestBuildAlertsFilterClause:
    def test_no_filters(self):
        where_sql, params = dash.build_alerts_filter_clause("", "")
        assert where_sql == ""
        assert params == []

    def test_district_only(self):
        where_sql, params = dash.build_alerts_filter_clause("Kirtipur", "")
        assert where_sql == " where district_name = ?"
        assert params == ["Kirtipur"]

    def test_district_and_scenario(self):
        where_sql, params = dash.build_alerts_filter_clause("Kirtipur", "NEW_HIGH_RISK")
        assert "district_name = ?" in where_sql
        assert "alert_scenario = ?" in where_sql
        assert params == ["Kirtipur", "NEW_HIGH_RISK"]


class TestPivotRiskLevelCounts:
    def test_empty_rows_returns_empty_frame_with_expected_columns(self):
        result = dash.pivot_risk_level_counts([])
        assert list(result.columns) == ["period", "LOW", "MEDIUM", "HIGH"]
        assert result.empty

    def test_pivots_long_rows_to_wide(self):
        rows = [
            {"period": "2024-01", "risk_level": "LOW", "awc_count": 18},
            {"period": "2024-01", "risk_level": "HIGH", "awc_count": 2},
            {"period": "2024-02", "risk_level": "MEDIUM", "awc_count": 5},
        ]
        result = dash.pivot_risk_level_counts(rows)
        row_jan = result[result["period"] == "2024-01"].iloc[0]
        assert row_jan["LOW"] == 18
        assert row_jan["HIGH"] == 2
        assert row_jan["MEDIUM"] == 0

        row_feb = result[result["period"] == "2024-02"].iloc[0]
        assert row_feb["MEDIUM"] == 5
        assert row_feb["LOW"] == 0
        assert row_feb["HIGH"] == 0

    def test_missing_level_across_all_periods_still_present_as_zero_column(self):
        rows = [{"period": "2024-01", "risk_level": "LOW", "awc_count": 10}]
        result = dash.pivot_risk_level_counts(rows)
        assert "HIGH" in result.columns
        assert (result["HIGH"] == 0).all()
