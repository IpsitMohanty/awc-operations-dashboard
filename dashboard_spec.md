# AWC Operational Dashboard Spec

## Audience
- State leadership
- District and project monitoring teams
- Nutrition surveillance and intervention teams

## Data Sources
- `mart_awc_alerts_latest`
- `fct_awc_monthly_snapshot`
- `fct_awc_anomaly_flags`
- `fct_awc_risk_snapshot`
- `vw_awc_risk_overview`
- `vw_awc_priority_interventions`
- `vw_awc_monthly_trends`
- `vw_awc_anomaly_pressure`

## Page 1: Executive Overview
- KPI: total AWCs in latest period
  - Source: `mart_awc_alerts_latest`
  - Metric: `count(*)`
- KPI: high-risk AWCs
  - Source: `mart_awc_alerts_latest`
  - Metric: `count(*) where risk_level = 'HIGH'`
- KPI: new high-risk AWCs
  - Source: `mart_awc_alerts_latest`
  - Metric: `count(*) where alert_scenario = 'NEW_HIGH_RISK'`
- KPI: escalated AWCs
  - Source: `mart_awc_alerts_latest`
  - Metric: `count(*) where alert_scenario = 'RISK_ESCALATED'`
- Chart: risk-level split
  - Visual: stacked bar or donut
  - Source: `mart_awc_alerts_latest`
  - Dimension: `risk_level`
- Chart: alert-scenario split
  - Visual: horizontal bar
  - Source: `mart_awc_alerts_latest`
  - Dimension: `alert_scenario`
- Chart: district ranking by high-risk AWC count
  - Visual: sorted bar
  - Source: `mart_awc_alerts_latest`
  - Dimension: `district_name`
  - Metric: `sum(case when risk_level='HIGH' then 1 else 0 end)`

## Page 2: Geography Drilldown
- Table: district/project/sector risk overview
  - Source: `vw_awc_risk_overview`
  - Columns:
    - `district_name`
    - `project_name`
    - `sector_name`
    - `awc_count`
    - `high_risk_awc_count`
    - `medium_risk_awc_count`
    - `new_high_risk_awc_count`
    - `escalated_awc_count`
    - `avg_measuring_efficiency_pct`
    - `avg_suw_rate_pct`
    - `avg_sam_rate_pct`
    - `avg_mam_rate_pct`
    - `avg_stunting_rate_pct`
- Map or heat grid:
  - If no GIS layer is available, use a district heat table
  - Metric options:
    - `high_risk_awc_count`
    - `escalated_awc_count`
    - average `stunting_rate_pct`

## Page 3: Priority Intervention Queue
- Table: priority AWCs
  - Source: `vw_awc_priority_interventions`
  - Sort:
    - `risk_level desc`
    - `recent_anomaly_count desc`
  - Columns:
    - `awc_code`
    - `district_name`
    - `project_name`
    - `sector_name`
    - `awc_name`
    - `current_period`
    - `risk_level`
    - `risk_flags`
    - `risk_direction`
    - `recent_anomaly_count`
    - `latest_anomaly_period`
    - `alert_scenario`
    - `measuring_efficiency_0_6_years_pct`
    - `suw_rate_pct`
    - `sam_rate_pct`
    - `mam_rate_pct`
    - `stunting_rate_pct`
- Recommended filters:
  - district
  - project
  - sector
  - risk level
  - alert scenario

## Page 4: AWC Detail
- Filter: single `awc_code`
- Current snapshot card group
  - Source: `mart_awc_alerts_latest`
  - Fields:
    - current and previous active children
    - current and previous measured children
    - current and previous measurement efficiency
    - current and previous `SUW`, `MUW`, `SAM`, `MAM`
    - current and previous severe and moderate stunting
    - current and previous risk
    - current alert scenario
- Trend charts
  - Source: `vw_awc_monthly_trends`
  - Visuals:
    - line chart for `measuring_efficiency_0_6_years_pct`
    - line chart for `suw_rate_pct`, `sam_rate_pct`, `mam_rate_pct`, `stunting_rate_pct`
    - column chart for `SUW`, `MUW`, `SAM`, `MAM`, `severely_stunted_count`, `moderately_stunted_count`
- Anomaly history
  - Source: `fct_awc_anomaly_flags`
  - Columns:
    - `period`
    - `metric_name`
    - `current_value`
    - `previous_value`
    - `delta_value`
    - `baseline_gap_value`
    - `flag_reason`

## Page 5: Trend Monitoring
- Monthly trend by geography
  - Source: `vw_awc_monthly_trends`
  - Dimensions:
    - `period`
    - district/project/sector
  - Metrics:
    - average `measuring_efficiency_0_6_years_pct`
    - average `suw_rate_pct`
    - average `sam_rate_pct`
    - average `mam_rate_pct`
    - average `stunting_rate_pct`
- Risk transition trend
  - Source: `fct_awc_risk_snapshot`
  - Visual:
    - month-by-month counts of `LOW`, `MEDIUM`, `HIGH`

## Page 6: Anomaly Surveillance
- Chart: anomaly pressure by metric
  - Source: `vw_awc_anomaly_pressure`
  - Dimension: `metric_name`
  - Metric: `anomaly_flag_count`
- Chart: anomaly pressure by district
  - Source: `fct_awc_anomaly_flags`
  - Dimension: `district_name`
  - Metric: `count(*)`
- Table: top unstable sectors
  - Source: `vw_awc_anomaly_pressure`
  - Columns:
    - `district_name`
    - `project_name`
    - `sector_name`
    - `metric_name`
    - `affected_awc_count`
    - `anomaly_flag_count`

## Core Filters
- `current_period`
- `district_name`
- `project_name`
- `sector_name`
- `risk_level`
- `alert_scenario`

## Operational KPIs
- High-risk AWCs this month
- New high-risk AWCs this month
- Escalated AWCs this month
- Persistent high-risk AWCs
- Average measurement efficiency by district
- Districts with highest recent anomaly pressure

## Design Notes
- Default landing page should be Executive Overview.
- Priority Intervention Queue should be exportable.
- AWC Detail should open from clicking an `awc_code` or `awc_name`.
- Use red for `HIGH`, amber for `MEDIUM`, green for `LOW`.
- Show both counts and rates to avoid misleading interpretation when denominators are small.
