#!/usr/bin/env python3
"""Weekly staffing dashboard build: Snowflake + Greenhouse -> page -> the app.

    python pipeline/run.py                       # build only, into pipeline/out/
    python pipeline/run.py --publish             # build, archive last week's agenda, upload the page
    python pipeline/run.py --date 2026-10-12     # build as of another day (defaults to today, Pacific)
    python pipeline/run.py --replay DIR          # Snowflake results from saved files (testing)

Environment (GitHub Actions secrets):
    SNOWFLAKE_ACCOUNT SNOWFLAKE_USER SNOWFLAKE_ROLE SNOWFLAKE_WAREHOUSE SNOWFLAKE_PRIVATE_KEY
    APP_URL (https://staffingapp-ivory.vercel.app)   IMPORT_TOKEN (same value as in Vercel)

State: pipeline/state/ (downloaded from the previous successful published run by the workflow)
holds last week's requisitions and headline numbers, for "closed since last week" and the
week-over-week checks, and org_history.json (every run's org-wide utilization figures, for the
projected month close). Missing state is fine; those two features just stay quiet.

Nothing here is edited week to week. The per-week choices live in pipeline/config.json.
"""
import argparse
import datetime as dt
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import fetch

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
TZ = ZoneInfo("America/Los_Angeles")
EXCLUDED_NAMES = ["Ankitha Thirakala", "Riddhima Shukla"]
MONEY = re.compile(r"\bsalary\b|pay rate|hourly pay|\$\s?\d|\b\d{2,3}k\b|\bwage", re.I)


# ------------------------------------------------------------------ dates
def mid(d):
    return f"{d.year}{d.month:02d}"


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, 1)


def us_holiday_mondays(year):
    """Monday of every week holding a US company holiday (observed): New Year, Presidents' Day,
    Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas. These are the
    32-hour weeks (matches the hand-kept 2026 list: Feb 16, May 25, Jun 15, Jun 29, Sep 7)."""
    def nth(month, weekday, n):          # n-th weekday of month (n=-1: last)
        if n > 0:
            d = dt.date(year, month, 1)
            d += dt.timedelta((weekday - d.weekday()) % 7)
            return d + dt.timedelta(weeks=n - 1)
        d = add_months(dt.date(year, month, 1), 1) - dt.timedelta(1)
        return d - dt.timedelta((d.weekday() - weekday) % 7)

    def observed(d):
        return d - dt.timedelta(1) if d.weekday() == 5 else d + dt.timedelta(1) if d.weekday() == 6 else d

    days = [observed(dt.date(year, 1, 1)), nth(2, 0, 3), nth(5, 0, -1), observed(dt.date(year, 6, 19)),
            observed(dt.date(year, 7, 4)), nth(9, 0, 1), nth(11, 3, 4), observed(dt.date(year, 12, 25))]
    return {d - dt.timedelta(d.weekday()) for d in days}


def dates(today):
    monday = today - dt.timedelta(today.weekday())
    weeks = [monday + dt.timedelta(weeks=k) for k in range(8)]
    first = monday.replace(day=1)
    months = [add_months(first, k) for k in range(4)]   # this month + 3 out (Mark, Oct 20 2026)
    org = [add_months(first, k) for k in range(-6, 4)]  # 6 back, this month, 3 forward
    s3 = [monday - dt.timedelta(weeks=k) for k in (4, 3, 2, 1)]
    holidays = set().union(*(us_holiday_mondays(y) for y in {monday.year - 1, monday.year, monday.year + 1}))
    lab = lambda d: f"{d:%b} {d.day}"
    return {
        "today": today, "monday": monday,
        "week_iso": [w.isoformat() for w in weeks], "weeks": [f"{w:%m%d}" for w in weeks],
        "week_labels": {f"{w:%m%d}": lab(w) for w in weeks},
        "months": [mid(m) for m in months], "month_labels": {mid(m): f"{m:%b}" for m in months},
        "org_months": [mid(m) for m in org], "org_labels": {mid(m): f"{m:%b} '{m:%y}" for m in org},
        "s3_iso": [w.isoformat() for w in s3], "s3_weeks": [f"{w:%m%d}" for w in s3],
        "s3_labels": {f"{w:%m%d}": lab(w) for w in s3}, "s3_year": s3[-1].year,
        "year": monday.year, "current_month": mid(monday),
        "util_months": [f"{monday.year}{m:02d}" for m in range(1, monday.month + 1)],
        "history_from": mid(add_months(first, -11)), "history_to": mid(first),
        "grand_from": min(f"{monday.year}01", mid(org[0])), "grand_to": mid(org[-1]),
        "recent_month": mid(add_months(first, -2)),
        "week_base": {f"{w:%m%d}": 32.0 for w in weeks if w in holidays},
        "holiday_weeks": sorted(h.isoformat() for h in holidays),
    }


# ------------------------------------------------------------------ app calls
def app_call(method, path, body=None, ctype="application/json", note=None, timeout=120):
    url = os.environ["APP_URL"].rstrip("/") + path
    req = urllib.request.Request(url, method=method, data=body)
    req.add_header("Authorization", "Bearer " + os.environ["IMPORT_TOKEN"])
    if body is not None:
        req.add_header("Content-Type", ctype)
    if note:
        req.add_header("X-Note", note)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:   # DNS, refused, timeout
        return 0, f"{type(e).__name__}: {e}"


def recruiting(state_dir, warnings):
    """Live Greenhouse through the app; else last week's saved pull; else the seed file."""
    if os.environ.get("APP_URL") and os.environ.get("IMPORT_TOKEN"):
        try:
            code, text = app_call("GET", "/api/recruiting?fresh=1")
            if code == 200:
                d = json.loads(text)
                try:
                    day = dt.date.fromisoformat(str(d.get("asOf", ""))[:10])
                    asof = f"{day:%B} {day.day}, {day.year}"
                except ValueError:
                    asof = "today"
                return d["reqs"], "Greenhouse (live)", asof
            warnings.append(f"Greenhouse pull through the app answered {code} ({text[:120]}); "
                            "recruiting updates are from the last saved pull.")
        except Exception as e:  # network trouble must not stop the build
            warnings.append(f"Greenhouse pull failed ({e}); recruiting updates are from the last saved pull.")
    for path, label in ((os.path.join(state_dir, "ats.json"), "last week's Greenhouse pull"),
                        (os.path.join(HERE, "seed", "ats.json"), "the Oct 13 2026 ATS export (seed)")):
        if os.path.exists(path):
            d = json.load(open(path))
            reqs = d["reqs"] if isinstance(d, dict) else d
            return reqs, label, (d.get("asOf") if isinstance(d, dict) else None) or "an earlier date"
    warnings.append("No recruiting data at all; Recruiting Updates are blank this week.")
    return [], "none", "n/a"


# ------------------------------------------------------------------ build
CHAIN = [
    ["make_data.py"],
    ["make_util_data.py"],
    ["build_dashboard.py"],
    ["inject_app_layer.py", "dashboard_artifact.html"],
    ["merge_open_roles.py", "dashboard_artifact.html", "dashboard_artifact.html"],
    ["layout_pass.py", "dashboard_artifact.html", "dashboard_artifact.html"],
    ["build_utilization_section.py", "dashboard_artifact.html", "dashboard_artifact.html"],
    "ADD_ACTION_ITEMS",
    ["finalize_page.py", "dashboard_artifact.html"],
    ["unmerge_open_roles.py", "dashboard_artifact.html", "dashboard_artifact.html"],
    ["flatten_open_roles.py", "dashboard_artifact.html", "dashboard_artifact.html"],
    ["allocate_layer.py", "dashboard_artifact.html", "dashboard_artifact.html"],
    ["recruiting_bgcheck.py", "dashboard_artifact.html", "ats.json"],
    ["util_controls.py", "dashboard_artifact.html"],
    ["open_roles_polish.py", "dashboard_artifact.html"],
    ["drawer_form_hold.py", "dashboard_artifact.html"],
    ["roles_alloc_only.py", "dashboard_artifact.html"],
    ["recruiting_roles_format.py", "dashboard_artifact.html"],
    ["recruiting_band_toggle.py", "dashboard_artifact.html"],
    "HIDE",
    ["collapsible_sections.py", "dashboard_artifact.html"],
]


def run_chain(build, hide_patterns, log):
    def py(args):
        r = subprocess.run([sys.executable] + args, cwd=build, capture_output=True, text=True)
        log.write(f"$ python {' '.join(args)}\n{r.stdout}{r.stderr}\n")
        if r.returncode != 0:
            raise SystemExit(f"build step failed: {' '.join(args)}\n{r.stdout[-2000:]}{r.stderr[-4000:]}")
        return r.stdout

    out = {}
    for step in CHAIN:
        if step == "ADD_ACTION_ITEMS":
            p = os.path.join(build, "dashboard_artifact.html")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("</body></html>")
            py(["add_action_items.py", "dashboard_artifact.html", "dashboard_artifact.html"])
            s = open(p, encoding="utf-8").read()
            assert s.endswith("</body></html>"), "add_action_items.py changed the page ending"
            open(p, "w", encoding="utf-8").write(s[:-len("</body></html>")].rstrip("\n") + "\n")
        elif step == "HIDE":
            out["hide"] = py(["hide_open_roles.py", "dashboard_artifact.html", "--extra"] + hide_patterns)
        else:
            out[step[0]] = py(step)
    return out


# ------------------------------------------------------------------ checks + summary
def page_text(page):
    t = re.sub(r"<script\b.*?</script>", " ", page, flags=re.S | re.I)
    t = re.sub(r"<style\b.*?</style>", " ", t, flags=re.S | re.I)
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", t))


def check_page(page, staff_count):
    """Hard stops: anything here keeps last week's page live."""
    errors = []
    if not (300_000 < len(page) < 6_000_000):
        errors.append(f"page size {len(page):,} bytes is outside 300 KB - 6 MB")
    for must in ("Cleartelligence Staffing Dashboard", 'id="staff-grid"', 'id="open-roles"'):
        if must not in page:
            errors.append(f"page is missing {must}")
    text = page_text(page)
    bad = MONEY.search(text)
    if bad:
        errors.append(f'guardrail: page text contains "{bad.group(0)}"')
    for n in EXCLUDED_NAMES:
        # full name or first name (both are unique on the roster), any case, anywhere in the page
        if re.search(re.escape(n), page, re.I) or re.search(r"\b" + re.escape(n.split()[0]) + r"\b", page, re.I):
            errors.append("guardrail: a standing exclusion appears on the page")
            break
    if "Alexander Markow" not in text:
        errors.append("Alexander Markow is missing (he must never be excluded)")
    if staff_count < 40:
        errors.append(f"only {staff_count} consultants in the 8 Week Outlook (expected ~60) - Snowflake data looks incomplete")
    if "Internal:" in text:
        errors.append("an Internal: role is still visible (hide_open_roles.py did not run cleanly)")
    return errors


def headline(build, page):
    sys.path.insert(0, build)
    import importlib
    D = importlib.import_module("staffing_data")
    O = importlib.import_module("outlook_data")
    org = {lab: round(v * 100, 1) for lab, v in D.ORG_MONTHLY}
    i = D.ORG_THIS_IDX
    k = page.find('id="open-roles"')
    sect = page[k:page.find("</section>", k)] if k >= 0 else ""
    roles_open = len(re.findall(r'class="[^"]*\brole-update\b', sect))
    rw = getattr(O, "RECRUITING_WEEK", None) or {}
    return {
        "week": D.THIS_WEEK,
        "org_this": D.ORG_MONTHLY[i][1], "org_next": D.ORG_MONTHLY[i + 1][1], "org_after": D.ORG_MONTHLY[i + 2][1],
        "org_labels": [D.ORG_MONTHLY[i][0], D.ORG_MONTHLY[i + 1][0], D.ORG_MONTHLY[i + 2][0]],
        "consultants": len(O.OUTLOOK_STAFF),
        "booked_this_week": round(O.OUTLOOK_BOOKED.get(O.OUTLOOK_WEEKS[0], 0.0), 1),
        "cohort": len(D.COHORT),
        "open_roles_shown": roles_open,
        "demand_lines": len(O.OPEN_DEMAND),
        "requisitions": rw.get("open_req_count"),
        "interviewing": rw.get("interviewing_total"),
        "unmatched_client_reqs": [r["role"] for r in getattr(O, "INTERNAL_ROLES", []) if r.get("stage") == "Requisition only"],
        "no_req": rw.get("no_req", []),
        "closed_reqs": rw.get("closed_reqs", []),
        "new_reqs": rw.get("new_reqs", []),
        "org_by_month": org,
    }


def week_over_week(now, prev, warnings):
    if not prev:
        return
    for key, label, tol in (("consultants", "consultants in the Outlook", 3), ("open_roles_shown", "open roles shown", 4)):
        if key in prev and abs(now[key] - prev[key]) > tol:
            warnings.append(f"{label} moved from {prev[key]} to {now[key]} since last week")
    pm = dict(zip(prev.get("org_labels", []), [prev.get("org_this"), prev.get("org_next"), prev.get("org_after")]))
    for lab, v in zip(now["org_labels"], [now["org_this"], now["org_next"], now["org_after"]]):
        if pm.get(lab) is not None and abs(v - pm[lab]) > 0.03:
            warnings.append(f"org-wide utilization for {lab} moved {pm[lab] * 100:.1f}% -> {v * 100:.1f}% since last week")


def summary_md(h, warnings, published, ats_source, ats_asof, manual, hides):
    pct = lambda v: f"{v * 100:.1f}%"
    L = [f"## Staffing dashboard - week of {h['week']}",
         "",
         ("**Published** to the app." if published else "**Built, not published** (dry run, a failed check or a failed upload - last week's page is still live)."),
         "",
         f"- Org-wide utilization: {h['org_labels'][0]} {pct(h['org_this'])} · {h['org_labels'][1]} {pct(h['org_next'])} (fcst) · "
         f"{h['org_labels'][2]} {pct(h['org_after'])} (fcst)",
         f"- 8 Week Outlook: {h['consultants']} consultants, {h['booked_this_week']:,} booked hrs this week; "
         f"under-target cohort {h['cohort']}",
         f"- Open Roles & Recruiting: {h['open_roles_shown']} roles shown ({h['demand_lines']} demand lines incl. manual); "
         f"{h['requisitions']} requisitions, {h['interviewing']} interviewing",
         f"- Recruiting data: {ats_source} (as of {ats_asof})",
         ]
    if h["closed_reqs"]:
        L.append(f"- Requisitions closed since last week: {', '.join(h['closed_reqs'])}")
    if h["new_reqs"]:
        L.append(f"- New requisitions: {', '.join(h['new_reqs'])}")
    if manual:
        L.append(f"- Manual demand lines still on (config.json): {', '.join(m['client'] + ': ' + m['role'] for m in manual)}")
    if hides:
        L.append(f"- Extra roles hidden (config.json): {', '.join(hides)}")
    if h["unmatched_client_reqs"]:
        L.append(f"- Client requisitions with no matching demand line (add to config.json \"match\" if one fits): "
                 f"{', '.join(h['unmatched_client_reqs'])}")
    if warnings:
        L += ["", "### Needs a look"] + [f"- {w}" for w in warnings]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="build as of this day (YYYY-MM-DD); default today in America/Los_Angeles")
    ap.add_argument("--publish", action="store_true", help="upload the page")
    ap.add_argument("--archive", action="store_true",
                    help="after a successful upload, file last Monday's Meeting Agenda in the Meeting Log "
                         "(scheduled runs only: it clears the agenda's done items)")
    ap.add_argument("--replay", help="read Snowflake results from saved files in this folder")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--state", default=os.path.join(HERE, "state"))
    a = ap.parse_args()

    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(TZ).date()
    p = dates(today)
    config = json.load(open(os.path.join(HERE, "config.json")))
    warnings = []

    build = os.path.join(a.out, "build")
    shutil.rmtree(a.out, ignore_errors=True)
    shutil.copytree(SRC, build)
    os.makedirs(a.state, exist_ok=True)

    # 1. Snowflake
    run = fetch.Replay(a.replay) if a.replay else fetch.Live()
    try:
        counts, grand = fetch.fetch(p, run, build, config.get("snowflake_objects"))
    finally:
        run.close()
    print("snowflake rows:", counts)
    if counts["util_practices"] != 6:
        warnings.append(f"Utilization by Practice has {counts['util_practices']} practices (expected 6)")
    missing = [m for m in p["org_months"] if m not in grand]
    if missing:
        raise SystemExit(f"Grand Total utilization missing for {missing}")

    # 2. Recruiting
    reqs, ats_source, ats_asof = recruiting(a.state, warnings)
    assert not MONEY.search(json.dumps(reqs)), "recruiting data carries pay language - refusing to build"
    json.dump({"reqs": reqs}, open(os.path.join(build, "ats.json"), "w"))
    prev_ats = os.path.join(a.state, "ats.json")
    prior = json.load(open(prev_ats)) if os.path.exists(prev_ats) else None
    prior_jobs = sorted({q["job"] for q in (prior or {}).get("reqs", [])})
    prior_asof = (prior or {}).get("week", "last week's")

    # 2b. Org-wide utilization history (for the projected month close): seed + last week's state,
    #     plus today's figures. Every observation is [run date, month id, fraction].
    org_history = []
    for path in (os.path.join(HERE, "seed", "org_history.json"), os.path.join(a.state, "org_history.json")):
        if os.path.exists(path):
            org_history += [list(o) for o in json.load(open(path)).get("observations", [])]
    seen = {(o[0], o[1]) for o in org_history}
    for m in p["org_months"]:
        if m in grand and (today.isoformat(), m) not in seen:
            org_history.append([today.isoformat(), m, round(grand[m], 5)])
    org_history.sort()

    # 3. params.py for the generators
    cfg = dict(config, _week_iso=p["week_iso"])
    hides = [h["pattern"] for h in config.get("hide_roles", [])
             if not h.get("until") or p["week_iso"][0] <= h["until"]]
    params = {
        "WEEKS": p["weeks"], "WEEK_LABELS": p["week_labels"], "MONTHS": p["months"],
        "MONTH_LABELS": p["month_labels"],
        "GENERATED": f"{today:%B} {today.day}, {today.year}",
        "MEETING_DATE": f"week of {p['monday']:%B} {p['monday'].day}",
        "THIS_WEEK": p["week_iso"][0],
        "HOURS_CUTOFF": f"{p['monday'] - dt.timedelta(1):%b} {(p['monday'] - dt.timedelta(1)).day}",
        "ORG_MONTHLY": [(p["org_labels"][m], round(grand[m], 5)) for m in p["org_months"]], "ORG_THIS_IDX": 6,
        "ORG_HISTORY": org_history, "BUILD_DATE": today.isoformat(),
        "S3_WEEKS_ORDER": p["s3_weeks"], "S3_WEEK_LABELS": p["s3_labels"], "S3_YEAR": p["s3_year"],
        "HISTORY_FROM": p["history_from"], "HISTORY_TO": p["history_to"],
        "ATS_JSON": "ats.json", "ATS_AS_OF": ats_asof, "ATS_SOURCE": ats_source,
        "PRIOR_JOBS": prior_jobs, "PRIOR_ASOF": prior_asof,
        "NEW_REQ_SINCE": (p["monday"] - dt.timedelta(7)).isoformat(),
        "CONFIG": cfg,
        "UTIL_MONTHS": p["util_months"],
        "UTIL_LABELS": {m: dt.date(int(m[:4]), int(m[4:]), 1).strftime("%b") for m in p["util_months"]},
        "CURRENT_MONTH": p["current_month"], "UTIL_YEAR": p["year"],
        "HOLIDAY_WEEKS": set(p["holiday_weeks"]),
        "WEEK_BASE": p["week_base"], "RECENT_MONTH_ID": int(p["recent_month"]),
    }
    with open(os.path.join(build, "params.py"), "w", encoding="utf-8") as fh:
        fh.write('"""Written by pipeline/run.py for this build - do not edit."""\n')
        for k, v in params.items():
            fh.write(f"{k} = {v!r}\n")

    # 4. Build
    with open(os.path.join(a.out, "build.log"), "w", encoding="utf-8") as log:
        outs = run_chain(build, hides, log)
    page = open(os.path.join(build, "dashboard_artifact.html"), encoding="utf-8").read()
    print(outs.get("make_data.py", "").strip())

    # 5. Checks
    h = headline(build, page)
    errors = check_page(page, h["consultants"])
    prev_sum = os.path.join(a.state, "summary.json")
    week_over_week(h, json.load(open(prev_sum)) if os.path.exists(prev_sum) else None, warnings)
    manual = [m for m in config.get("manual_demand", [])
              if any(r["project"] == m["project"] for r in __import__("outlook_data").OPEN_DEMAND)]

    published = False
    if errors:
        warnings = [f"BLOCKED: {e}" for e in errors] + warnings
    elif a.publish:
        code, text = app_call("POST", "/api/dashboard", page.encode("utf-8"), "text/html",
                              note=f"{params['GENERATED']} automated refresh", timeout=300)
        if code != 200:
            errors.append(f"upload to /api/dashboard answered {code or 'no response'}: {text[:300]}")
            warnings.insert(0, errors[-1])
        else:
            published = True
            print("uploaded:", text)
            if a.archive:
                last_monday = (p["monday"] - dt.timedelta(7)).isoformat()
                code, text = app_call("POST", "/api/agenda/archive", json.dumps(
                    {"week": last_monday, "source": f"archived by the {p['week_iso'][0]} automated refresh"}).encode())
                if code == 200:
                    print("agenda archived:", text)
                else:
                    warnings.append(f"Meeting Agenda for {last_monday} was not archived (answered {code or 'no response'}: "
                                    f"{text[:200]}) - the page is live; archive it from the app or re-run with --archive")

    # 6. Outputs
    shutil.copy(os.path.join(build, "dashboard_artifact.html"), os.path.join(a.out, f"dashboard_{p['week_iso'][0]}.html"))
    md = summary_md(h, warnings, published, ats_source, ats_asof, manual, hides)
    open(os.path.join(a.out, "summary.md"), "w").write(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(md)
    print(md)
    if published:   # next week's comparison basis - only a published run becomes state
        os.makedirs(os.path.join(a.out, "state"), exist_ok=True)
        json.dump({"week": p["week_iso"][0], "asOf": ats_asof, "reqs": reqs},
                  open(os.path.join(a.out, "state", "ats.json"), "w"))
        json.dump(h, open(os.path.join(a.out, "state", "summary.json"), "w"), indent=1)
        json.dump({"observations": org_history}, open(os.path.join(a.out, "state", "org_history.json"), "w"))
    if errors:
        raise SystemExit("not published: " + "; ".join(errors))


if __name__ == "__main__":
    main()
