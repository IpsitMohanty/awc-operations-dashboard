import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="AWC Operations Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


DB_FILE = Path(__file__).resolve().parent / "awc_warehouse.sqlite"


def _resolve_database_url() -> str | None:
    """OS env var wins (local dev, docker, most non-Streamlit-Cloud hosts).
    Falls back to st.secrets, which is how Streamlit Community Cloud actually
    delivers secrets - it does not set OS environment variables. Falls back
    to None (SQLite) if neither is configured; st.secrets raises if no
    secrets.toml exists at all, which is a normal local-dev state, not an
    error, so that's caught rather than left to crash the app.
    """
    env_value = os.environ.get("DATABASE_URL")
    if env_value:
        return env_value
    try:
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


DATABASE_URL = _resolve_database_url()
USE_POSTGRES = bool(DATABASE_URL)

# Query results: long enough that clicking one filter doesn't re-query for
# every other unrelated widget on the page, short enough that a fresh
# pipeline run shows up without restarting the app. Connection: cached much
# longer than any single query, since reconnecting is what actually pays for
# a cold Neon compute - the whole point is to pay that cost once per TTL
# window, not once per rerun.
QUERY_CACHE_TTL_SECONDS = 300
CONNECTION_CACHE_TTL_SECONDS = 900


@st.cache_resource(ttl=CONNECTION_CACHE_TTL_SECONDS, show_spinner="Connecting to warehouse...")
def get_connection():
    if USE_POSTGRES:
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2 is required to connect to Postgres. Install it with `pip install psycopg2-binary`."
            ) from exc
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True  # read-only dashboard; avoid holding idle transactions open against Neon
        return conn
    return sqlite3.connect(str(DB_FILE), check_same_thread=False)


def _adapt_sql(sql: str, use_postgres: bool) -> str:
    """Translate SQLite-style `?` placeholders to psycopg2-style `%s`."""
    return sql.replace("?", "%s") if use_postgres else sql


def like_operator(use_postgres: bool) -> str:
    """Postgres LIKE is case-sensitive; ILIKE matches SQLite's default LIKE behavior."""
    return "ilike" if use_postgres else "like"


def _period_label(value) -> str | None:
    """Normalize a period value (SQLite text, e.g. "2024-01-01 00:00:00", or a
    Postgres DATE returned as datetime.date) to a "YYYY-MM" label."""
    if value is None:
        return None
    if isinstance(value, str):
        return value[:7]
    return value.strftime("%Y-%m")


def _execute_rows(conn, sql: str, params: tuple) -> list[dict]:
    if USE_POSTGRES:
        import psycopg2.extras

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def fetch_rows(sql: str, params: tuple = ()) -> list[dict]:
    adapted_sql = _adapt_sql(sql, USE_POSTGRES)
    try:
        return _execute_rows(get_connection(), adapted_sql, params)
    except Exception:
        # One retry against a fresh connection - covers a dropped/expired
        # connection (e.g. after a Neon idle timeout) without looping forever.
        get_connection.clear()
        return _execute_rows(get_connection(), adapted_sql, params)


def fetch_rows_safe(sql: str, params: tuple = ()) -> list[dict]:
    """Like fetch_rows, but degrades to an empty result instead of raising -
    used only for the anomaly/risk/alert tables, which may not exist yet if
    anomaly_risk_flags.py has never been run against this warehouse."""
    try:
        return fetch_rows(sql, params)
    except Exception:
        return []


def build_filter_clause(query: dict, use_postgres: bool = USE_POSTGRES) -> tuple[str, list]:
    clauses = []
    params = []
    period_value = query.get("period", [""])[0].strip()
    if period_value:
        clauses.append("period = ?")
        params.append(f"{period_value}-01")
    mapping = {
        "state": "state_name",
        "district": "district_name",
        "project": "project_name",
        "sector": "sector_name",
        "awc_code": "awc_code",
    }
    for key, column in mapping.items():
        value = query.get(key, [""])[0].strip()
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    awc_name = query.get("awc_name", [""])[0].strip()
    if awc_name:
        clauses.append(f"awc_name {like_operator(use_postgres)} ?")
        params.append(f"%{awc_name}%")
    return (" where " + " and ".join(clauses)) if clauses else "", params


@st.cache_data(ttl=QUERY_CACHE_TTL_SECONDS, show_spinner=False)
def fetch_period_state(query: dict) -> list[dict]:
    where_sql, params = build_filter_clause(query)
    sql = f"""
    select
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
    from vw_awc_monthly_trends
    {where_sql}
    """
    rows = fetch_rows(sql, tuple(params))
    for row in rows:
        row["period"] = _period_label(row["period"])
    return rows


def _num(value) -> float:
    return float(value) if value not in (None, "") else 0.0


def _estimated_numerator(row: dict, count_key: str, rate_key: str, denom_key: str) -> float:
    count_value = row.get(count_key)
    if count_value not in (None, ""):
        return float(count_value)
    rate_value = row.get(rate_key)
    denom_value = row.get(denom_key)
    if rate_value in (None, "") or denom_value in (None, ""):
        return 0.0
    return (float(rate_value) / 100.0) * float(denom_value)


def _rolled_rate_pct(rows: list[dict], count_key: str, rate_key: str, denom_key: str) -> float:
    numerator = sum(_estimated_numerator(row, count_key, rate_key, denom_key) for row in rows)
    denominator = sum(_num(row.get(denom_key)) for row in rows)
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def _rolled_efficiency_pct(rows: list[dict]) -> float:
    measured = sum(_num(row.get("total_active_children_measured_0_6_years")) for row in rows)
    active = sum(_num(row.get("total_active_children_0_6_years")) for row in rows)
    return round((measured / active) * 100, 2) if active else 0.0


def _rolled_stunting_rate_pct(rows: list[dict]) -> float:
    numerator = sum(
        _num(row.get("severely_stunted_count")) + _num(row.get("moderately_stunted_count"))
        for row in rows
    )
    denominator = sum(_num(row.get("total_active_children_measured_0_6_years")) for row in rows)
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def build_overview_rows(rows: list[dict]) -> list[dict]:
    grouped = {}
    for r in rows:
        key = (r["state_name"], r["district_name"], r["project_name"], r["sector_name"])
        if key not in grouped:
            grouped[key] = {
                "state_name": r["state_name"],
                "district_name": r["district_name"],
                "project_name": r["project_name"],
                "sector_name": r["sector_name"],
                "awc_count": 0,
                "total_active_children_0_6_years": 0.0,
                "total_active_children_measured_0_6_years": 0.0,
                "total_active_children_measured_0_5_years": 0.0,
                "total_suw_count": 0.0,
                "total_muw_count": 0.0,
                "total_sam_count": 0.0,
                "total_mam_count": 0.0,
                "total_severely_stunted_count": 0.0,
                "total_moderately_stunted_count": 0.0,
                "rows": [],
            }
        grouped[key]["awc_count"] += 1
        grouped[key]["total_active_children_0_6_years"] += r["total_active_children_0_6_years"] or 0
        grouped[key]["total_active_children_measured_0_6_years"] += r["total_active_children_measured_0_6_years"] or 0
        grouped[key]["total_active_children_measured_0_5_years"] += r["total_active_children_measured_0_5_years"] or 0
        grouped[key]["total_suw_count"] += r["suw_count"] or 0
        grouped[key]["total_muw_count"] += r["muw_count"] or 0
        grouped[key]["total_sam_count"] += r["sam_count"] or 0
        grouped[key]["total_mam_count"] += r["mam_count"] or 0
        grouped[key]["total_severely_stunted_count"] += r["severely_stunted_count"] or 0
        grouped[key]["total_moderately_stunted_count"] += r["moderately_stunted_count"] or 0
        grouped[key]["rows"].append(r)

    overview_rows = []
    for row in grouped.values():
        grouped_rows = row["rows"]
        overview_rows.append(
            {
                "state_name": row["state_name"],
                "district_name": row["district_name"],
                "project_name": row["project_name"],
                "sector_name": row["sector_name"],
                "awc_count": row["awc_count"],
                "total_active_children_0_6_years": round(row["total_active_children_0_6_years"], 0),
                "total_active_children_measured_0_6_years": round(row["total_active_children_measured_0_6_years"], 0),
                "total_active_children_measured_0_5_years": round(row["total_active_children_measured_0_5_years"], 0),
                "total_suw_count": round(row["total_suw_count"], 0),
                "total_muw_count": round(row["total_muw_count"], 0),
                "total_sam_count": round(row["total_sam_count"], 0),
                "total_mam_count": round(row["total_mam_count"], 0),
                "total_severely_stunted_count": round(row["total_severely_stunted_count"], 0),
                "total_moderately_stunted_count": round(row["total_moderately_stunted_count"], 0),
                "avg_measuring_efficiency_pct": _rolled_efficiency_pct(grouped_rows),
                "avg_suw_rate_pct": _rolled_rate_pct(grouped_rows, "suw_count", "suw_rate_pct", "total_active_children_measured_0_6_years"),
                "avg_sam_rate_pct": _rolled_rate_pct(grouped_rows, "sam_count", "sam_rate_pct", "total_active_children_measured_0_5_years"),
                "avg_mam_rate_pct": _rolled_rate_pct(grouped_rows, "mam_count", "mam_rate_pct", "total_active_children_measured_0_5_years"),
                "avg_stunting_rate_pct": _rolled_stunting_rate_pct(grouped_rows),
            }
        )

    return sorted(
        overview_rows,
        key=lambda r: (r["total_active_children_0_6_years"], r["total_sam_count"], r["total_suw_count"]),
        reverse=True,
    )


@st.cache_data(ttl=QUERY_CACHE_TTL_SECONDS, show_spinner=False)
def get_filter_options() -> dict:
    period_rows = fetch_rows("select distinct period from fct_awc_monthly_snapshot order by period")
    periods = sorted({_period_label(row["period"]) for row in period_rows if row["period"] is not None})
    alert_scenario_rows = fetch_rows_safe(
        "select distinct alert_scenario from mart_awc_alerts_latest where alert_scenario is not null order by alert_scenario"
    )
    return {
        "periods": periods,
        "states": [row["state_name"] for row in fetch_rows("select distinct state_name from fct_awc_monthly_snapshot order by state_name")],
        "districts": [row["district_name"] for row in fetch_rows("select distinct district_name from fct_awc_monthly_snapshot order by district_name")],
        "projects": [row["project_name"] for row in fetch_rows("select distinct project_name from fct_awc_monthly_snapshot order by project_name")],
        "sectors": [row["sector_name"] for row in fetch_rows("select distinct sector_name from fct_awc_monthly_snapshot order by sector_name")],
        "alert_scenarios": [row["alert_scenario"] for row in alert_scenario_rows],
    }


def _query_dict(period: str, state: str, district: str, project: str, sector: str, awc_code: str, awc_name: str) -> dict:
    query = {}
    mapping = {
        "period": period,
        "state": state,
        "district": district,
        "project": project,
        "sector": sector,
        "awc_code": awc_code.strip(),
        "awc_name": awc_name.strip(),
    }
    for key, value in mapping.items():
        if value:
            query[key] = [value]
    return query


def _rows_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in df.columns:
        if col.endswith("_count") or col.endswith("_years") or col.endswith("_pct"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _geography_filter_clause(
    state: str, district: str, project: str, sector: str, awc_code: str, awc_name: str, use_postgres: bool = USE_POSTGRES
) -> tuple[str, list]:
    clauses = []
    params: list[str] = []
    mapping = {
        "state": ("state_name", state),
        "district": ("district_name", district),
        "project": ("project_name", project),
        "sector": ("sector_name", sector),
        "awc_code": ("awc_code", awc_code.strip()),
    }
    for _, (column, value) in mapping.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if awc_name.strip():
        clauses.append(f"awc_name {like_operator(use_postgres)} ?")
        params.append(f"%{awc_name.strip()}%")
    return (" where " + " and ".join(clauses)) if clauses else "", params


@st.cache_data(ttl=QUERY_CACHE_TTL_SECONDS, show_spinner=False)
def get_geography_trends(state: str, district: str, project: str, sector: str, awc_code: str, awc_name: str) -> pd.DataFrame:
    where_sql, params = _geography_filter_clause(state, district, project, sector, awc_code, awc_name)
    rows = fetch_rows(
        f"""
        select
          period,
          avg(total_active_children_0_6_years) as avg_total_active_children_0_6_years,
          avg(total_active_children_measured_0_6_years) as avg_total_active_children_measured_0_6_years,
          avg(total_active_children_measured_0_5_years) as avg_total_active_children_measured_0_5_years,
          sum(total_active_children_measured_0_6_years) * 100.0 / nullif(sum(total_active_children_0_6_years), 0) as avg_measuring_efficiency_0_6_years_pct,
          sum(coalesce(suw_count, (suw_rate_pct / 100.0) * total_active_children_measured_0_6_years)) * 100.0 / nullif(sum(total_active_children_measured_0_6_years), 0) as avg_suw_rate_pct,
          sum(coalesce(sam_count, (sam_rate_pct / 100.0) * total_active_children_measured_0_5_years)) * 100.0 / nullif(sum(total_active_children_measured_0_5_years), 0) as avg_sam_rate_pct,
          sum(coalesce(mam_count, (mam_rate_pct / 100.0) * total_active_children_measured_0_5_years)) * 100.0 / nullif(sum(total_active_children_measured_0_5_years), 0) as avg_mam_rate_pct,
          sum(coalesce(severely_stunted_count, 0) + coalesce(moderately_stunted_count, 0)) * 100.0 / nullif(sum(total_active_children_measured_0_6_years), 0) as avg_stunting_rate_pct,
          avg(suw_count) as avg_suw_count,
          avg(sam_count) as avg_sam_count,
          avg(mam_count) as avg_mam_count,
          avg(muw_count) as avg_muw_count,
          avg(severely_stunted_count) as avg_severely_stunted_count,
          avg(moderately_stunted_count) as avg_moderately_stunted_count
        from vw_awc_monthly_trends
        {where_sql}
        group by period
        order by period
        """,
        tuple(params),
    )
    for row in rows:
        row["period"] = _period_label(row["period"])
    return _rows_frame(rows)


@st.cache_data(ttl=QUERY_CACHE_TTL_SECONDS, show_spinner=False)
def get_awc_detail(awc_code: str, awc_name: str) -> pd.DataFrame:
    if not awc_code.strip() and not awc_name.strip():
        return pd.DataFrame()
    if awc_code.strip():
        where_sql = "where awc_code = ?"
        params = (awc_code.strip(),)
    else:
        where_sql = f"where awc_name {like_operator(USE_POSTGRES)} ?"
        params = (f"%{awc_name.strip()}%",)
    rows = fetch_rows(
        f"""
        select
          period,
          total_active_children_0_6_years,
          total_active_children_measured_0_6_years,
          total_active_children_measured_0_5_years,
          measuring_efficiency_0_6_years_pct,
          suw_count,
          muw_count,
          sam_count,
          mam_count,
          severely_stunted_count,
          moderately_stunted_count,
          suw_rate_pct,
          sam_rate_pct,
          mam_rate_pct,
          stunting_rate_pct
        from vw_awc_monthly_trends
        {where_sql}
        order by period
        """,
        params,
    )
    for row in rows:
        row["period"] = _period_label(row["period"])
    return _rows_frame(rows)


def _top_burden_frames(snapshot_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if snapshot_df.empty:
        return {name: pd.DataFrame() for name in ["suw", "muw", "sam", "mam", "severe", "moderate"]}
    base_cols = ["awc_code", "awc_name", "district_name"]
    return {
        "suw": snapshot_df.sort_values(["suw_count", "sam_count"], ascending=False)[base_cols + ["suw_count"]].head(10),
        "muw": snapshot_df.sort_values(["muw_count", "mam_count"], ascending=False)[base_cols + ["muw_count"]].head(10),
        "sam": snapshot_df.sort_values(["sam_count", "suw_count"], ascending=False)[base_cols + ["sam_count"]].head(10),
        "mam": snapshot_df.sort_values(["mam_count", "muw_count"], ascending=False)[base_cols + ["mam_count"]].head(10),
        "severe": snapshot_df.sort_values(["severely_stunted_count", "moderately_stunted_count"], ascending=False)[base_cols + ["severely_stunted_count"]].head(10),
        "moderate": snapshot_df.sort_values(["moderately_stunted_count", "severely_stunted_count"], ascending=False)[base_cols + ["moderately_stunted_count"]].head(10),
    }


def _metric_value(value: float | int | str) -> str:
    if value in ("", None):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{int(value):,}"


def build_alerts_filter_clause(district: str, scenario: str) -> tuple[str, list]:
    clauses = []
    params = []
    if district:
        clauses.append("district_name = ?")
        params.append(district)
    if scenario:
        clauses.append("alert_scenario = ?")
        params.append(scenario)
    return (" where " + " and ".join(clauses)) if clauses else "", params


@st.cache_data(ttl=QUERY_CACHE_TTL_SECONDS, show_spinner=False)
def get_latest_alerts(district: str, scenario: str) -> pd.DataFrame:
    where_sql, params = build_alerts_filter_clause(district, scenario)
    rows = fetch_rows_safe(
        f"""
        select
          awc_code, awc_name, district_name, project_name, sector_name,
          current_period, previous_period,
          risk_level, previous_risk_level, risk_direction,
          risk_flags, risk_flag_count,
          alert_scenario, recent_anomaly_count, latest_anomaly_period,
          measuring_efficiency_0_6_years_pct, suw_rate_pct, sam_rate_pct, mam_rate_pct, stunting_rate_pct
        from mart_awc_alerts_latest
        {where_sql}
        order by risk_flag_count desc, recent_anomaly_count desc
        """,
        tuple(params),
    )
    return _rows_frame(rows)


RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"]


def pivot_risk_level_counts(rows: list[dict]) -> pd.DataFrame:
    """Reshape long (period, risk_level, awc_count) rows into a wide
    period x risk_level frame, suitable for a stacked chart."""
    if not rows:
        return pd.DataFrame(columns=["period", *RISK_LEVELS])
    df = pd.DataFrame(rows)
    pivoted = df.pivot_table(index="period", columns="risk_level", values="awc_count", fill_value=0, aggfunc="sum")
    for level in RISK_LEVELS:
        if level not in pivoted.columns:
            pivoted[level] = 0
    return pivoted[RISK_LEVELS].reset_index()


@st.cache_data(ttl=QUERY_CACHE_TTL_SECONDS, show_spinner=False)
def get_risk_level_trend(state: str, district: str, project: str, sector: str, awc_code: str, awc_name: str) -> pd.DataFrame:
    where_sql, params = _geography_filter_clause(state, district, project, sector, awc_code, awc_name)
    rows = fetch_rows_safe(
        f"""
        select period, risk_level, count(distinct awc_code) as awc_count
        from fct_awc_risk_snapshot
        {where_sql}
        group by period, risk_level
        order by period
        """,
        tuple(params),
    )
    for row in rows:
        row["period"] = _period_label(row["period"])
    return pivot_risk_level_counts(rows)


@st.cache_data(ttl=QUERY_CACHE_TTL_SECONDS, show_spinner=False)
def get_anomaly_history(awc_code: str) -> pd.DataFrame:
    if not awc_code.strip():
        return pd.DataFrame()
    rows = fetch_rows_safe(
        """
        select period, metric_name, current_value, previous_value, delta_value,
               baseline_gap_value, threshold_value, flag_reason
        from fct_awc_anomaly_flags
        where awc_code = ?
        order by period, metric_name
        """,
        (awc_code.strip(),),
    )
    for row in rows:
        row["period"] = _period_label(row["period"])
    return _rows_frame(rows)


def main() -> None:
    options = get_filter_options()
    default_period = options["periods"][-1] if options["periods"] else ""

    st.title("AWC Operations Dashboard")
    backend_label = "Postgres (Neon)" if USE_POSTGRES else "SQLite (local)"
    st.caption(
        f"Streamlit dashboard over the normalized AWC warehouse - backend: {backend_label}. "
        "Focused on source data, rolled-up percentages, month-by-month movement, and anomaly/risk surveillance."
    )

    with st.sidebar:
        st.header("Filters")
        period = st.selectbox("Snapshot Month", options["periods"], index=(len(options["periods"]) - 1 if options["periods"] else None))
        state = st.selectbox("State", [""] + options["states"], format_func=lambda x: x or "All states")
        district = st.selectbox("District", [""] + options["districts"], format_func=lambda x: x or "All districts")
        project = st.selectbox("Project", [""] + options["projects"], format_func=lambda x: x or "All projects")
        sector = st.selectbox("Sector", [""] + options["sectors"], format_func=lambda x: x or "All sectors")
        awc_code = st.text_input("AWC Code", placeholder="Exact AWC code")
        awc_name = st.text_input("AWC Name", placeholder="Contains AWC name")
        alert_scenario = st.selectbox("Alert Scenario", [""] + options["alert_scenarios"], format_func=lambda x: x or "All scenarios")

    query = _query_dict(period or default_period, state, district, project, sector, awc_code, awc_name)
    snapshot_rows = fetch_period_state(query)
    snapshot_df = _rows_frame(snapshot_rows)
    overview_df = _rows_frame(build_overview_rows(snapshot_rows))
    trend_df = get_geography_trends(state, district, project, sector, awc_code, awc_name)
    awc_detail_df = get_awc_detail(awc_code, awc_name)
    top_frames = _top_burden_frames(snapshot_df)
    alerts_df = get_latest_alerts(district, alert_scenario)
    risk_trend_df = get_risk_level_trend(state, district, project, sector, awc_code, awc_name)
    anomaly_history_df = get_anomaly_history(awc_code)

    summary = {
        "avg_measuring_efficiency_0_6_years_pct": _rolled_efficiency_pct(snapshot_rows) if snapshot_rows else "",
        "avg_suw_rate_pct": _rolled_rate_pct(snapshot_rows, "suw_count", "suw_rate_pct", "total_active_children_measured_0_6_years") if snapshot_rows else "",
        "avg_sam_rate_pct": _rolled_rate_pct(snapshot_rows, "sam_count", "sam_rate_pct", "total_active_children_measured_0_5_years") if snapshot_rows else "",
        "avg_mam_rate_pct": _rolled_rate_pct(snapshot_rows, "mam_count", "mam_rate_pct", "total_active_children_measured_0_5_years") if snapshot_rows else "",
        "avg_stunting_rate_pct": _rolled_stunting_rate_pct(snapshot_rows) if snapshot_rows else "",
    }
    kpis = {
        "Snapshot Month": period or default_period,
        "AWCs": len(snapshot_rows),
        "Active Children 0-6": round(sum((row["total_active_children_0_6_years"] or 0) for row in snapshot_rows), 0),
        "Measured Children 0-6": round(sum((row["total_active_children_measured_0_6_years"] or 0) for row in snapshot_rows), 0),
        "Measured Children 0-5": round(sum((row["total_active_children_measured_0_5_years"] or 0) for row in snapshot_rows), 0),
        "Avg Measuring Efficiency %": summary["avg_measuring_efficiency_0_6_years_pct"],
        "Total SUW": round(sum((row["suw_count"] or 0) for row in snapshot_rows), 0),
        "Total MUW": round(sum((row["muw_count"] or 0) for row in snapshot_rows), 0),
        "Total SAM": round(sum((row["sam_count"] or 0) for row in snapshot_rows), 0),
        "Total MAM": round(sum((row["mam_count"] or 0) for row in snapshot_rows), 0),
        "Severely Stunted": round(sum((row["severely_stunted_count"] or 0) for row in snapshot_rows), 0),
        "Moderately Stunted": round(sum((row["moderately_stunted_count"] or 0) for row in snapshot_rows), 0),
    }

    st.subheader("Snapshot Summary")
    metric_cols = st.columns(4)
    for idx, (label, value) in enumerate(kpis.items()):
        metric_cols[idx % 4].metric(label, _metric_value(value))

    st.subheader("Rolled-up Percentages")
    rate_cols = st.columns(5)
    rate_cols[0].metric("Measuring Efficiency %", _metric_value(summary["avg_measuring_efficiency_0_6_years_pct"]))
    rate_cols[1].metric("SUW %", _metric_value(summary["avg_suw_rate_pct"]))
    rate_cols[2].metric("SAM %", _metric_value(summary["avg_sam_rate_pct"]))
    rate_cols[3].metric("MAM %", _metric_value(summary["avg_mam_rate_pct"]))
    rate_cols[4].metric("Stunting Rate %", _metric_value(summary["avg_stunting_rate_pct"]))

    tab_overview, tab_trends, tab_detail, tab_surveillance = st.tabs(
        ["Overview", "Geography Trends", "AWC Detail", "Anomaly Surveillance"]
    )

    with tab_overview:
        left, right = st.columns([1.2, 1])
        with left:
            st.markdown("**Geography Overview**")
            st.dataframe(
                overview_df.head(25),
                width="stretch",
                hide_index=True,
            )
        with right:
            st.markdown("**AWC Snapshot**")
            snapshot_preview = snapshot_df[
                [
                    "awc_code",
                    "awc_name",
                    "district_name",
                    "total_active_children_0_6_years",
                    "total_active_children_measured_0_6_years",
                    "total_active_children_measured_0_5_years",
                    "measuring_efficiency_0_6_years_pct",
                    "suw_count",
                    "muw_count",
                    "sam_count",
                    "mam_count",
                ]
            ] if not snapshot_df.empty else pd.DataFrame()
            st.dataframe(snapshot_preview.head(50), width="stretch", hide_index=True)

        st.markdown("**Top Burden AWCs**")
        top_cols = st.columns(3)
        top_cols[0].dataframe(top_frames["suw"], width="stretch", hide_index=True)
        top_cols[1].dataframe(top_frames["muw"], width="stretch", hide_index=True)
        top_cols[2].dataframe(top_frames["sam"], width="stretch", hide_index=True)
        lower_top_cols = st.columns(3)
        lower_top_cols[0].dataframe(top_frames["mam"], width="stretch", hide_index=True)
        lower_top_cols[1].dataframe(top_frames["severe"], width="stretch", hide_index=True)
        lower_top_cols[2].dataframe(top_frames["moderate"], width="stretch", hide_index=True)

    with tab_trends:
        st.markdown("**Geography Trends**")
        if trend_df.empty:
            st.info("No trend rows match the current filters.")
        else:
            coverage_chart = trend_df.set_index("period")[
                [
                    "avg_total_active_children_0_6_years",
                    "avg_total_active_children_measured_0_6_years",
                    "avg_total_active_children_measured_0_5_years",
                ]
            ]
            st.line_chart(coverage_chart)

            rate_left, rate_right = st.columns(2)
            with rate_left:
                st.line_chart(trend_df.set_index("period")[["avg_measuring_efficiency_0_6_years_pct"]])
                st.caption("Rolled-up measuring efficiency over time.")
            with rate_right:
                st.line_chart(trend_df.set_index("period")[["avg_suw_rate_pct", "avg_sam_rate_pct", "avg_mam_rate_pct", "avg_stunting_rate_pct"]])
                st.caption("Rolled-up SUW, SAM, MAM, and stunting rates over time.")

            count_left, count_right = st.columns(2)
            with count_left:
                st.line_chart(trend_df.set_index("period")[["avg_suw_count", "avg_muw_count", "avg_sam_count", "avg_mam_count"]])
                st.caption("Average nutrition counts over time.")
            with count_right:
                st.line_chart(trend_df.set_index("period")[["avg_severely_stunted_count", "avg_moderately_stunted_count"]])
                st.caption("Average stunting counts over time.")

            st.dataframe(trend_df, width="stretch", hide_index=True)

    with tab_detail:
        st.markdown("**AWC Detail Trends**")
        if awc_detail_df.empty:
            st.info("Set an AWC code or AWC name filter to load month-by-month AWC detail.")
        else:
            detail_top_left, detail_top_right = st.columns(2)
            with detail_top_left:
                st.line_chart(
                    awc_detail_df.set_index("period")[
                        [
                            "total_active_children_0_6_years",
                            "total_active_children_measured_0_6_years",
                            "total_active_children_measured_0_5_years",
                        ]
                    ]
                )
                st.caption("Children and measurement coverage.")
            with detail_top_right:
                st.line_chart(
                    awc_detail_df.set_index("period")[
                        [
                            "measuring_efficiency_0_6_years_pct",
                            "suw_rate_pct",
                            "sam_rate_pct",
                            "mam_rate_pct",
                            "stunting_rate_pct",
                        ]
                    ]
                )
                st.caption("Efficiency and rates.")

            detail_bottom_left, detail_bottom_right = st.columns(2)
            with detail_bottom_left:
                st.line_chart(
                    awc_detail_df.set_index("period")[
                        [
                            "suw_count",
                            "muw_count",
                            "sam_count",
                            "mam_count",
                        ]
                    ]
                )
                st.caption("Nutrition counts.")
            with detail_bottom_right:
                st.line_chart(
                    awc_detail_df.set_index("period")[
                        [
                            "severely_stunted_count",
                            "moderately_stunted_count",
                        ]
                    ]
                )
                st.caption("Stunting counts.")

            st.dataframe(awc_detail_df, width="stretch", hide_index=True)

    with tab_surveillance:
        st.markdown("**Anomaly Surveillance**")
        if alerts_df.empty and risk_trend_df.empty and anomaly_history_df.empty:
            st.info(
                "No anomaly/risk/alert data available yet. Run anomaly_risk_flags.py and reload the warehouse "
                "to populate this page (see README: Anomaly, Risk, and Alerts)."
            )
        else:
            surveillance_kpis = {
                "AWCs Shown": len(alerts_df),
                "High Risk": int((alerts_df["risk_level"] == "HIGH").sum()) if not alerts_df.empty else 0,
                "New High Risk": int((alerts_df["alert_scenario"] == "NEW_HIGH_RISK").sum()) if not alerts_df.empty else 0,
                "Escalated": int((alerts_df["alert_scenario"] == "RISK_ESCALATED").sum()) if not alerts_df.empty else 0,
            }
            kpi_cols = st.columns(4)
            for idx, (label, value) in enumerate(surveillance_kpis.items()):
                kpi_cols[idx].metric(label, _metric_value(value))

            st.markdown("**Latest Alerts** (District + Alert Scenario filters from the sidebar)")
            if alerts_df.empty:
                st.info("No alerts match the current District / Alert Scenario filters.")
            else:
                st.dataframe(
                    alerts_df[
                        [
                            "awc_code", "awc_name", "district_name", "project_name", "sector_name",
                            "current_period", "risk_level", "previous_risk_level", "risk_direction",
                            "alert_scenario", "recent_anomaly_count", "risk_flags",
                            "measuring_efficiency_0_6_years_pct", "suw_rate_pct", "sam_rate_pct", "mam_rate_pct", "stunting_rate_pct",
                        ]
                    ],
                    width="stretch",
                    hide_index=True,
                )

            st.markdown("**Risk Level Distribution Over Time** (State/District/Project/Sector/AWC filters from the sidebar)")
            if risk_trend_df.empty:
                st.info("No risk snapshot rows match the current filters.")
            else:
                st.area_chart(risk_trend_df.set_index("period")[RISK_LEVELS])
                st.caption("Count of distinct AWCs at each risk level per period.")

            st.markdown("**Per-Centre Anomaly History** (set an AWC Code in the sidebar)")
            if anomaly_history_df.empty:
                st.info("Set an AWC Code filter to load that centre's anomaly flag history.")
            else:
                st.dataframe(
                    anomaly_history_df[
                        [
                            "period", "metric_name", "current_value", "previous_value",
                            "delta_value", "baseline_gap_value", "threshold_value", "flag_reason",
                        ]
                    ],
                    width="stretch",
                    hide_index=True,
                )


if __name__ == "__main__":
    main()
