IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name = '__SCHEMA__')
BEGIN
    EXEC('CREATE SCHEMA __SCHEMA__');
END

IF OBJECT_ID('__SCHEMA__.fct_awc_monthly_snapshot', 'U') IS NULL
BEGIN
    CREATE TABLE __SCHEMA__.fct_awc_monthly_snapshot (
        awc_code NVARCHAR(64) NOT NULL,
        period DATE NOT NULL,
        state_name NVARCHAR(255) NULL,
        district_name NVARCHAR(255) NULL,
        project_name NVARCHAR(255) NULL,
        sector_name NVARCHAR(255) NULL,
        awc_name NVARCHAR(255) NULL,
        source_file NVARCHAR(255) NOT NULL,
        total_active_children_0_6_years FLOAT NULL,
        total_active_children_measured_0_6_years FLOAT NULL,
        measuring_efficiency_0_6_years_pct FLOAT NULL,
        total_active_children_measured_0_5_years FLOAT NULL,
        suw_count FLOAT NULL,
        muw_count FLOAT NULL,
        severely_stunted_count FLOAT NULL,
        moderately_stunted_count FLOAT NULL,
        sam_count FLOAT NULL,
        mam_count FLOAT NULL,
        suw_rate_pct FLOAT NULL,
        sam_rate_pct FLOAT NULL,
        mam_rate_pct FLOAT NULL,
        stunting_rate_pct FLOAT NULL,
        CONSTRAINT pk_fct_awc_monthly_snapshot PRIMARY KEY (awc_code, period)
    );
END

IF OBJECT_ID('__SCHEMA__.fct_awc_anomaly_flags', 'U') IS NULL
BEGIN
    CREATE TABLE __SCHEMA__.fct_awc_anomaly_flags (
        awc_code NVARCHAR(64) NOT NULL,
        period DATE NOT NULL,
        metric_name NVARCHAR(128) NOT NULL,
        state_name NVARCHAR(255) NULL,
        district_name NVARCHAR(255) NULL,
        project_name NVARCHAR(255) NULL,
        sector_name NVARCHAR(255) NULL,
        awc_name NVARCHAR(255) NULL,
        source_file NVARCHAR(255) NOT NULL,
        current_value FLOAT NULL,
        previous_value FLOAT NULL,
        delta_value FLOAT NULL,
        absolute_delta_value FLOAT NULL,
        rolling_baseline_value FLOAT NULL,
        baseline_gap_value FLOAT NULL,
        threshold_value FLOAT NULL,
        flag_reason NVARCHAR(128) NOT NULL,
        CONSTRAINT pk_fct_awc_anomaly_flags PRIMARY KEY (awc_code, period, metric_name)
    );
END

IF OBJECT_ID('__SCHEMA__.fct_awc_risk_snapshot', 'U') IS NULL
BEGIN
    CREATE TABLE __SCHEMA__.fct_awc_risk_snapshot (
        awc_code NVARCHAR(64) NOT NULL,
        period DATE NOT NULL,
        state_name NVARCHAR(255) NULL,
        district_name NVARCHAR(255) NULL,
        project_name NVARCHAR(255) NULL,
        sector_name NVARCHAR(255) NULL,
        awc_name NVARCHAR(255) NULL,
        source_file NVARCHAR(255) NOT NULL,
        measuring_efficiency_0_6_years_pct FLOAT NULL,
        suw_rate_pct FLOAT NULL,
        sam_rate_pct FLOAT NULL,
        mam_rate_pct FLOAT NULL,
        stunting_rate_pct FLOAT NULL,
        risk_flags NVARCHAR(MAX) NULL,
        risk_flag_count INT NOT NULL,
        risk_level NVARCHAR(16) NOT NULL,
        CONSTRAINT pk_fct_awc_risk_snapshot PRIMARY KEY (awc_code, period)
    );
END

IF OBJECT_ID('__SCHEMA__.mart_awc_alerts_latest', 'U') IS NULL
BEGIN
    CREATE TABLE __SCHEMA__.mart_awc_alerts_latest (
        awc_code NVARCHAR(64) NOT NULL,
        current_period NVARCHAR(7) NOT NULL,
        previous_period NVARCHAR(7) NULL,
        state_name NVARCHAR(255) NULL,
        district_name NVARCHAR(255) NULL,
        project_name NVARCHAR(255) NULL,
        sector_name NVARCHAR(255) NULL,
        awc_name NVARCHAR(255) NULL,
        source_file NVARCHAR(255) NOT NULL,
        total_active_children_0_6_years FLOAT NULL,
        previous_total_active_children_0_6_years FLOAT NULL,
        delta_total_active_children_0_6_years FLOAT NULL,
        total_active_children_measured_0_6_years FLOAT NULL,
        previous_total_active_children_measured_0_6_years FLOAT NULL,
        delta_total_active_children_measured_0_6_years FLOAT NULL,
        measuring_efficiency_0_6_years_pct FLOAT NULL,
        previous_measuring_efficiency_0_6_years_pct FLOAT NULL,
        delta_measuring_efficiency_0_6_years_pct FLOAT NULL,
        total_active_children_measured_0_5_years FLOAT NULL,
        previous_total_active_children_measured_0_5_years FLOAT NULL,
        delta_total_active_children_measured_0_5_years FLOAT NULL,
        suw_count FLOAT NULL,
        previous_suw_count FLOAT NULL,
        delta_suw_count FLOAT NULL,
        muw_count FLOAT NULL,
        previous_muw_count FLOAT NULL,
        delta_muw_count FLOAT NULL,
        severely_stunted_count FLOAT NULL,
        previous_severely_stunted_count FLOAT NULL,
        delta_severely_stunted_count FLOAT NULL,
        moderately_stunted_count FLOAT NULL,
        previous_moderately_stunted_count FLOAT NULL,
        delta_moderately_stunted_count FLOAT NULL,
        sam_count FLOAT NULL,
        previous_sam_count FLOAT NULL,
        delta_sam_count FLOAT NULL,
        mam_count FLOAT NULL,
        previous_mam_count FLOAT NULL,
        delta_mam_count FLOAT NULL,
        suw_rate_pct FLOAT NULL,
        previous_suw_rate_pct FLOAT NULL,
        delta_suw_rate_pct FLOAT NULL,
        sam_rate_pct FLOAT NULL,
        previous_sam_rate_pct FLOAT NULL,
        delta_sam_rate_pct FLOAT NULL,
        mam_rate_pct FLOAT NULL,
        previous_mam_rate_pct FLOAT NULL,
        delta_mam_rate_pct FLOAT NULL,
        stunting_rate_pct FLOAT NULL,
        previous_stunting_rate_pct FLOAT NULL,
        delta_stunting_rate_pct FLOAT NULL,
        risk_level NVARCHAR(16) NOT NULL,
        risk_flags NVARCHAR(MAX) NULL,
        risk_flag_count INT NOT NULL,
        previous_risk_period NVARCHAR(7) NULL,
        previous_risk_level NVARCHAR(16) NULL,
        previous_risk_flags NVARCHAR(MAX) NULL,
        previous_risk_flag_count INT NULL,
        risk_direction NVARCHAR(16) NOT NULL,
        recent_anomaly_count INT NOT NULL,
        latest_anomaly_period NVARCHAR(7) NULL,
        recent_anomaly_metrics NVARCHAR(MAX) NULL,
        recent_flag_reasons NVARCHAR(MAX) NULL,
        alert_scenario NVARCHAR(64) NOT NULL,
        CONSTRAINT pk_mart_awc_alerts_latest PRIMARY KEY (awc_code)
    );
END
