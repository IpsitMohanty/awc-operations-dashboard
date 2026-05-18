CREATE VIEW IF NOT EXISTS vw_awc_monthly_trends AS
SELECT
    state_name,
    district_name,
    project_name,
    sector_name,
    awc_code,
    awc_name,
    period,
    total_active_children_0_6_years,
    total_active_children_measured_0_6_years,
    measuring_efficiency_0_6_years_pct,
    total_active_children_measured_0_5_years,
    suw_count,
    muw_count,
    severely_stunted_count,
    moderately_stunted_count,
    sam_count,
    mam_count,
    suw_rate_pct,
    sam_rate_pct,
    mam_rate_pct,
    stunting_rate_pct
FROM fct_awc_monthly_snapshot;
