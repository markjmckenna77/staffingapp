"""Snowflake pulls for the weekly staffing dashboard build.

Runs the same queries the old Claude runbook ran by hand (claude/staffing-dashboard-refresh-runbook.md,
step 2) and writes them in the shapes the generators read:

    raw/avail.json raw/alloc.json raw/opendemand.json raw/roster.json raw/contractors.json raw/projmeta.json
    raw/s3.json raw/cohort.json raw/history.json            -> make_data.py
    util_raw.json grand_total.json zero_denom_weeks.json     -> make_util_data.py

Every column is cast with ::string and COALESCE'd in SQL so the values are byte-identical to the
strings the runbook's '~'-concatenated pulls produced. Objects default to the cost-free views in
PRD_BI_SUITE.STAFFING_APP (snowflake/pipeline_views.sql); config.json "snowflake_objects" can point
them elsewhere.

Two executors:
  live    snowflake-connector-python, key-pair auth from SNOWFLAKE_* environment variables
  replay  a directory of saved results, <name>.json each {"result_set": {"data": [...]}} - used to
          test the whole pipeline without a Snowflake connection
"""
import json
import os
from collections import defaultdict

EXCLUDE = {"Ankitha Thirakala", "Riddhima Shukla"}   # standing exclusions; never reach the page

DEFAULT_OBJECTS = {
    "avail": "PRD_BI_SUITE.STAFFING_APP.WEEKLY_AVAILABILITY",
    "ptime": "PRD_BI_SUITE.STAFFING_APP.PROJECT_TIME",
    "detail": "PRD_BI_SUITE.STAFFING_APP.CONSULTANT_PROJECT_DETAIL",
    "demand": "PRD_BI_SUITE.STAFFING_APP.OPEN_DEMAND",
    "roster": "PRD_BI_SUITE.STAFFING_APP.CONSULTANT",
}


def s(col):
    """Column as a non-null string, exactly as the runbook pulls rendered it."""
    return f"COALESCE({col}::string,'')"


def queries(p, obj):
    """name -> SQL. `p` is the run's date parameters (see run.py: dates())."""
    w0, w7 = p["week_iso"][0], p["week_iso"][-1]
    s3_in = ",".join(f"'{d}'" for d in p["s3_iso"])
    months = ",".join(p["months"])
    q = {}
    q["avail"] = f"""SELECT {s('CONSULTANT_NAME')}, TO_CHAR(WEEK_FIRST_DAY_AT,'MMDD'), {s('PRACTICE')},
  {s('TARGET_UTILIZATION')}, {s('HRS_BILLABLE')}, {s('HRS_UTIL_DENOM')}, {s('HRS_TIME_OFF')},
  {s('RELATIONSHIP')}, {s('REGION')}, {s('COUNTRY')}, {s('JOB_LEVEL')}
FROM {obj['avail']}
WHERE PRACTICE <> 'Grand Total' AND WEEK_FIRST_DAY_AT BETWEEN '{w0}' AND '{w7}'
ORDER BY 1, 2, 3"""
    q["alloc"] = f"""SELECT {s('CONSULTANT_NAME')}, TO_CHAR(WEEK_FIRST_DAY_AT,'MMDD'), {s('PROJECT_NAME')},
  SUM(ALLOCATED_BILLABLE_HOURS)::string
FROM {obj['detail']}
WHERE WEEK_FIRST_DAY_AT BETWEEN '{w0}' AND '{w7}'
GROUP BY CONSULTANT_NAME, WEEK_FIRST_DAY_AT, PROJECT_NAME
HAVING SUM(ALLOCATED_BILLABLE_HOURS) > 0
ORDER BY 1, 2, 3"""
    q["opendemand"] = f"""SELECT DISTINCT {s('CUSTOMER_NAME')}, {s('PROJECT_NAME')}, {s('ROLE_TITLE')},
  TO_CHAR(WEEK_FIRST_DAY_AT,'MMDD'), {s('HRS_ALLOCATED_RAW')}, {s('OPTY_STAGE')}, {s('OPTY_PROBABILITY')},
  {s('OPTY_FORECAST_CATEGORY')}, COALESCE(TO_CHAR(OPTY_ESTIMATED_START_DATE,'YYYY-MM-DD'),''), {s('PROJECT_STATUS')}
FROM {obj['demand']}
WHERE WEEK_FIRST_DAY_AT BETWEEN '{w0}' AND '{w7}'
ORDER BY 1, 2, 3, 4"""
    q["roster"] = f"""SELECT {s('NAME')}, {s('TITLE')}, {s('JOB_LEVEL')}, {s('PRACTICE')}, {s('COUNTRY')},
  {s('REGION')}, {s('TARGET_UTILIZATION')}
FROM {obj['roster']}
WHERE RELATIONSHIP = 'Direct' AND ACTIVE_FLAG::string = 'Y'
ORDER BY 1"""
    q["contractors"] = f"""SELECT {s('NAME')}, {s('TITLE')}, {s('PRACTICE')}, {s('COUNTRY')}, {s('TARGET_UTILIZATION')}, {s('RELATIONSHIP')}
FROM {obj['roster']}
WHERE RELATIONSHIP <> 'Direct' AND ACTIVE_FLAG::string = 'Y'
ORDER BY 1"""
    q["projmeta"] = f"""SELECT DISTINCT * FROM (
  SELECT {s('PROJECT_NAME')} P, {s('CUSTOMER_NAME')} C, {s('PROJECT_MANAGER')} M, {s('PROJECT_STATUS')} S, {s('OPTY_STAGE')} O
  FROM {obj['detail']} WHERE WEEK_FIRST_DAY_AT BETWEEN '{w0}' AND '{w7}' AND ALLOCATED_BILLABLE_HOURS > 0
  UNION
  SELECT {s('PROJECT_NAME')}, {s('CUSTOMER_NAME')}, {s('PROJECT_MANAGER')}, {s('PROJECT_STATUS')}, {s('OPTY_STAGE')}
  FROM {obj['demand']} WHERE WEEK_FIRST_DAY_AT BETWEEN '{w0}' AND '{w7}')
ORDER BY 1, 2"""
    q["s3"] = f"""SELECT {s('CONSULTANT_NAME')}, {s('PRACTICE')}, {s('CUSTOMER_NAME')}, {s('PROJECT_NAME')},
  SUM(ALLOCATED_BILLABLE_HOURS)::string, SUM(ACTUAL_BILLABLE_HOURS)::string, TO_CHAR(WEEK_FIRST_DAY_AT,'MMDD')
FROM {obj['ptime']}
WHERE RELATIONSHIP = 'Direct' AND WEEK_FIRST_DAY_AT IN ({s3_in})
GROUP BY CONSULTANT_NAME, PRACTICE, CUSTOMER_NAME, PROJECT_NAME, WEEK_FIRST_DAY_AT
HAVING SUM(ALLOCATED_BILLABLE_HOURS) <> 0 OR SUM(ACTUAL_BILLABLE_HOURS) <> 0
ORDER BY 1, 2, 3, 4, 7"""
    q["cohort"] = f"""SELECT {s('CONSULTANT_NAME')}, DATE_MONTH_ID::string, {s('MAX(TARGET_UTILIZATION)')},
  SUM(IFF(FLAG_UNDER_TARGET::string ILIKE 'true',1,0))::string, COUNT(*)::string,
  COALESCE((SUM(HRS_BILLABLE)/NULLIF(SUM(HRS_UTIL_DENOM),0))::string,''),
  SUM(IFF(FLAG_TIME_OFF::string ILIKE 'true',1,0))::string, {s('MAX(PRACTICE)')}
FROM {obj['avail']}
WHERE RELATIONSHIP = 'Direct' AND PRACTICE <> 'Grand Total' AND DATE_MONTH_ID IN ({months})
GROUP BY CONSULTANT_NAME, DATE_MONTH_ID
ORDER BY 1, 2"""
    q["history"] = f"""SELECT {s('CONSULTANT_NAME')}, {s('CUSTOMER_NAME')}, SUM(ACTUAL_BILLABLE_HOURS)::string,
  COUNT(DISTINCT MONTH_ID)::string, MAX(MONTH_ID)::string
FROM {obj['ptime']}
WHERE RELATIONSHIP = 'Direct' AND MONTH_ID BETWEEN {p['history_from']} AND {p['history_to']}
GROUP BY CONSULTANT_NAME, CUSTOMER_NAME
HAVING SUM(ACTUAL_BILLABLE_HOURS) >= 8
ORDER BY 1, 2"""
    q["grand"] = f"""SELECT DATE_MONTH_ID::string, (SUM(HRS_BILLABLE)/NULLIF(SUM(HRS_UTIL_DENOM),0))::string
FROM {obj['avail']}
WHERE PRACTICE = 'Grand Total' AND DATE_MONTH_ID BETWEEN {p['grand_from']} AND {p['grand_to']}
GROUP BY DATE_MONTH_ID
ORDER BY 1"""
    q["zero"] = f"""SELECT {s('CONSULTANT_NAME')}, DATE_MONTH_ID::string, TO_CHAR(WEEK_FIRST_DAY_AT,'YYYY-MM-DD'),
  COALESCE(HRS_BILLABLE::string,'0'), COALESCE(HRS_TIME_OFF::string,'0'), COALESCE(HRS_UTIL_DENOM::string,'0')
FROM {obj['avail']}
WHERE RELATIONSHIP = 'Direct' AND PRACTICE <> 'Grand Total' AND DATE_YEAR_ID = {p['year']}
  AND HRS_UTIL_DENOM = 0 AND HRS_BILLABLE > 0
ORDER BY 1, 3"""
    q["util"] = f"""SELECT {s('CONSULTANT_NAME')}, {s('PRACTICE')}, DATE_MONTH_ID::string,
  SUM(HRS_BILLABLE)::string, SUM(HRS_UTIL_DENOM)::string, {s('MAX(TARGET_UTILIZATION)')},
  {s('MAX(JOB_LEVEL)')}, {s('MAX(COUNTRY)')}
FROM {obj['avail']}
WHERE RELATIONSHIP = 'Direct' AND PRACTICE <> 'Grand Total' AND DATE_YEAR_ID = {p['year']}
  AND DATE_MONTH_ID <= {p['current_month']}
GROUP BY CONSULTANT_NAME, PRACTICE, DATE_MONTH_ID
ORDER BY 1, 2, 3"""
    return q


# ------------------------------------------------------------------ executors
class Live:
    """Key-pair auth as the pipeline's service user. Reads SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
    SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE and SNOWFLAKE_PRIVATE_KEY (PKCS8 PEM; literal \\n allowed)."""

    def __init__(self):
        import snowflake.connector
        from cryptography.hazmat.primitives import serialization
        pem = os.environ["SNOWFLAKE_PRIVATE_KEY"].replace("\\n", "\n").strip().encode()
        key = serialization.load_pem_private_key(pem, password=None)
        der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        self.conn = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
            private_key=der, role=os.environ.get("SNOWFLAKE_ROLE") or None,
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE") or None,
            login_timeout=60, network_timeout=300,
            session_parameters={"QUERY_TAG": "staffing-dashboard-pipeline"})

    def __call__(self, name, sql):
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            rows = [list(r) for r in cur.fetchall()]
        finally:
            cur.close()
        return rows

    def close(self):
        self.conn.close()


class Replay:
    """Saved results, one file per query name: a Claude Snowflake connector result
    ({"result_set": {"data": [...], "resultSetMetaData": {"numRows": n}}}) or a bare list."""

    def __init__(self, folder):
        self.folder = folder

    def __call__(self, name, sql):
        d = json.load(open(os.path.join(self.folder, f"{name}.json")))
        if isinstance(d, list):
            return d
        rs = d["result_set"]
        n = rs.get("resultSetMetaData", {}).get("numRows")
        assert n is None or n == len(rs["data"]), f"replay {name}: {len(rs['data'])} of {n} rows (truncated save)"
        # results saved from the Claude connector may carry a trailing RPAD('x',N,'x') column
        # (it forces the tool to write a file); drop it
        return [r[:-1] if r and isinstance(r[-1], str) and r[-1] and set(r[-1]) == {"x"} else r
                for r in rs["data"]]

    def close(self):
        pass


# ------------------------------------------------------------------ run
def fetch(p, run, out_dir, objects=None):
    """Run every query, write the raw files into out_dir. Returns {name: row count} and the
    Grand Total series {month_id: utilization}."""
    obj = dict(DEFAULT_OBJECTS, **(objects or {}))
    q = queries(p, obj)
    os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)
    counts, got = {}, {}
    for name, sql in q.items():
        rows = run(name, sql)
        got[name] = rows
        counts[name] = len(rows)

    for name in ("avail", "alloc", "opendemand", "roster", "contractors", "projmeta", "s3", "cohort", "history"):
        with open(os.path.join(out_dir, "raw", f"{name}.json"), "w", encoding="utf-8") as fh:
            json.dump({"result_set": {"data": got[name], "resultSetMetaData": {"numRows": len(got[name])}}}, fh)

    grand = {str(m): float(v) for m, v in got["grand"] if v not in ("", None)}
    with open(os.path.join(out_dir, "grand_total.json"), "w") as fh:
        json.dump({m: v for m, v in grand.items() if m.startswith(str(p["year"])) and m <= p["current_month"]}, fh)

    zero = [[n, str(m), w, float(b), float(t), float(d)] for n, m, w, b, t, d in got["zero"] if n not in EXCLUDE]
    with open(os.path.join(out_dir, "zero_denom_weeks.json"), "w") as fh:
        json.dump(zero, fh)

    # person x practice x month, standing exclusions dropped, AI/ML variants folded into AI Engineering
    agg = defaultdict(lambda: [0.0, 0.0, None, None, None])
    for name, prac, mon, bill, den, tgt, lvl, ctry in got["util"]:
        if name in EXCLUDE:
            continue
        if prac in ("AI/ML", "AI/ML/AppDev"):
            prac = "AI Engineering"
        a = agg[(name, prac, str(mon))]
        a[0] += float(bill or 0)
        a[1] += float(den or 0)
        a[2] = float(tgt) if tgt not in ("", None) else a[2]
        a[3] = lvl or a[3]
        a[4] = ctry or a[4]
    util = [dict(name=k[0], practice=k[1], month=k[2], billable=v[0], denom=v[1], target=v[2], level=v[3],
                 country=v[4]) for k, v in sorted(agg.items())]
    with open(os.path.join(out_dir, "util_raw.json"), "w") as fh:
        json.dump(util, fh)
    counts["util_practices"] = len({u["practice"] for u in util})
    return counts, grand
