#!/usr/bin/env python3
"""Builds staffing_data.py, outlook_data.py, projects_meta.py and client_history.py
from the Snowflake pulls in raw/ (written by pipeline/fetch.py).

A raw file is {"result_set": {"data": [...]}}. Rows are either lists of column values
(pipeline/fetch.py) or, in files saved from the Claude Snowflake connector, a single
'~'-delimited string padded with RPAD('x',N,'x'). Both shapes are accepted.
"""
import json
import pprint
from collections import defaultdict

EXCLUDE = {"Ankitha Thirakala", "Riddhima Shukla"}  # standing exclusions; never printed

# Week, month and label constants come from params.py, which pipeline/run.py writes for the
# run date (America/Los_Angeles). Nothing in this file is edited by hand week to week; the
# per-week choices (requisition matches, manual demand lines, filled hires) live in
# pipeline/config.json and arrive through params.CONFIG.
from params import (WEEKS, WEEK_LABELS, MONTHS, MONTH_LABELS, GENERATED, MEETING_DATE, THIS_WEEK,
                    HOURS_CUTOFF, ORG_MONTHLY, ORG_THIS_IDX, S3_WEEKS_ORDER, S3_WEEK_LABELS,
                    HISTORY_FROM, HISTORY_TO, ATS_JSON, ATS_AS_OF, ATS_SOURCE, PRIOR_JOBS,
                    PRIOR_ASOF, NEW_REQ_SINCE, CONFIG)

BASE_WEEK = 40.0          # standard week, used when the view has no utilization denominator
IMPUTED = {}              # name -> weeks whose utilization was imputed from booked hours


def rows(path):
    d = json.load(open(path))["result_set"]["data"]
    out = []
    for row in d:
        if len(row) == 1:
            parts = row[0].split("~")
            if parts and set(parts[-1]) == {"x"}:
                parts = parts[:-1]
        else:
            parts = ["" if v is None else str(v) for v in row]
        out.append(parts)
    return out


def f(x):
    return float(x) if x not in ("", None) else 0.0


# ------------------------------------------------- allocations (parsed first)
# Needed before the roster is built: a consultant whose HRS_UTIL_DENOM is zero has
# their utilization imputed from booked hours, so the allocations have to be in hand.
raw_alloc = defaultdict(list)
import glob as _glob
for _path in sorted(_glob.glob("raw/alloc*.json")):
    for _name, _wk, _proj, _hrs in (r[:4] for r in rows(_path)):
        _h = round(float(_hrs or 0), 2)
        if _h > 0:
            raw_alloc[(_name, _wk)].append((_h, _proj))


def booked_hours(name, wk):
    return sum(h for h, _ in raw_alloc.get((name, wk), []))


VACATED = {}   # no manual adjustments this week (Ascend undo stood, Sep 15)


# ---------------------------------------------------------------- availability
avail = [r for _p in sorted(_glob.glob("raw/avail*.json")) for r in rows(_p)]
# name ~ wk ~ practice ~ target ~ billable ~ denom ~ timeoff ~ rel ~ region ~ country ~ joblevel
staff = {}
meta = {}
for r in avail:
    name, wk, practice, target, bill, denom, toff, rel, region, country, jl = r[:11]
    if name in EXCLUDE or rel != "Direct" or practice == "Grand Total":
        continue
    denom_v, bill_v, toff_v = f(denom), f(bill), f(toff)
    pct = bill_v / denom_v if denom_v > 0 else 0.0
    # PTO fraction of the week = HRS_TIME_OFF / HRS_UTIL_DENOM. HRS_* on this view are
    # scaled, so only the ratio is meaningful; a full-week PTO row has toff == denom.
    # Verified against the Sep 9 build on all 427 overlapping staff-weeks.
    pto = min(1.0, toff_v / denom_v) if denom_v > 0 else 0.0
    # The availability view's billable hours still include anything UNASSIGN dropped
    # above, so the percentage has to come down with the allocation. On the forward
    # weeks this view's pct is exactly booked/40 (checked against booked hours for all
    # four adjusted consultants), so subtract the removed hours' share of a standard
    # week. Measured rows only: an imputed pct is derived from booked_hours(), which
    # already reflects the removal, and subtracting again would double-count it.
    if denom_v > 0:
        _rm = VACATED.get(name, {}).get(wk, 0.0)
        if _rm:
            pct = max(0.0, pct - _rm / BASE_WEEK)
    measured = denom_v > 0
    # A zero HRS_UTIL_DENOM is an upstream gap, not an absence: the consultant is on the
    # roster and carries real allocations, but the view has no denominator to divide by,
    # so every week renders "n/m" and the person reads as excluded. Mark flagged this on
    # Alexander Markow, Sep 14 2026 - he is not on leave. Where that happens and the week
    # has booked hours, impute against the standard week instead of dropping the person,
    # and record it so the cell can say the number is imputed.
    if not measured:
        bk = booked_hours(name, wk)
        if bk > 0:
            pct = bk / (BASE_WEEK * (1.0 - pto)) if pto < 1.0 else 0.0
            measured = True
            IMPUTED.setdefault(name, []).append(wk)
    staff.setdefault(name, {"practice": practice, "target": f(target), "weeks": {}})
    staff[name]["weeks"][wk] = (round(pct, 5), round(pto, 5), measured)
    meta[name] = {"region": region, "country": country, "job_level": jl}

for name, p in staff.items():
    for wk in WEEKS:
        p["weeks"].setdefault(wk, (0.0, 0.0, False))

# ---------------------------------------------------------------- contractors (Mark, Oct 20 2026)
# Active non-Direct consultants with bookings in the window. CONS_WEEKLY_AVAILABILITY carries no
# rows for them, so every week is imputed from booked hours over a standard week (tagged est. on
# the page). They live in their own dict: the 8 Week Outlook shows them behind an
# "Include contractors" toggle (off by default); capacity, suggestions and the cohort stay
# employees-only.
CONTRACTORS = {}
import os as _os
if _os.path.exists("raw/contractors.json"):
    for name, title, practice, country, target, rel in (r[:6] for r in rows("raw/contractors.json")):
        if name in EXCLUDE or name in staff:
            continue
        wks = {}
        any_booked = False
        for wk in WEEKS:
            bk = booked_hours(name, wk)
            if bk > 0:
                any_booked = True
                wks[wk] = (round(bk / BASE_WEEK, 5), 0.0, True)
            else:
                wks[wk] = (0.0, 0.0, False)
        if not any_booked:
            continue
        CONTRACTORS[name] = {"practice": practice or "Other", "target": f(target), "weeks": wks,
                             "rel": rel, "title": title, "country": country}

# ---------------------------------------------------------------- allocations
alloc = defaultdict(list)
booked = defaultdict(float)
alloc_contract = defaultdict(list)
for (name, wk), items in raw_alloc.items():
    if name in CONTRACTORS:
        for h, proj in items:
            alloc_contract[(name, wk)].append((h, proj))
for k in alloc_contract:
    alloc_contract[k].sort(key=lambda t: (-t[0], t[1]))
for (name, wk), items in raw_alloc.items():
    if name in EXCLUDE or name not in staff:
        continue
    for h, proj in items:
        alloc[(name, wk)].append((h, proj))
        booked[wk] += h
for k in alloc:
    alloc[k].sort(key=lambda t: (-t[0], t[1]))

# ---------------------------------------------------------------- open demand
GEO = [("CTI", "india"), ("EU", "eu"), ("US", "us")]


def geo_of(role):
    for tag, g in GEO:
        if tag in role.split():
            return g
    if role.startswith("CTI ") or " CTI " in role:
        return "india"
    if "US " in role or role.startswith("US"):
        return "us"
    return "us"


od = defaultdict(lambda: {"weeks": []})
for r in rows("raw/opendemand.json"):
    client, proj, role, wk, hrs, stage, prob, cat, start, pstat = r[:10]
    key = (client, proj, role)
    rec = od[key]
    rec.update({"client": client, "project": proj, "role": role, "hrs": int(round(f(hrs))),
                "geo": geo_of(role), "stage": stage,
                "prob": int(f(prob)) if prob else None, "cat": cat,
                "start": start, "pstatus": pstat, "ats": None})
    rec["weeks"].append(wk)
OPEN_DEMAND = []
for key in sorted(od, key=lambda k: (k[0], k[2])):
    rec = od[key]
    rec["weeks"] = sorted(set(rec["weeks"]), key=WEEKS.index)
    OPEN_DEMAND.append({k: rec[k] for k in
                        ("client", "project", "role", "hrs", "weeks", "geo",
                         "stage", "prob", "cat", "start", "pstatus", "ats")})

# Manual demand lines (pipeline/config.json "manual_demand"): roles Mark has asked for that are not
# yet an allocation on a generic resource in NetSuite, so CONS_OPEN_DEMAND does not carry them.
# A line is dropped automatically once Snowflake carries a role for the same client whose title
# matches its "drop_when_role_matches" pattern, or after its "until" date.
import re as _re
MANUAL_ACTIVE = []
for _m in CONFIG.get("manual_demand", []):
    if _m.get("until") and THIS_WEEK > _m["until"]:
        continue
    _pat = _m.get("drop_when_role_matches")
    if _pat and any(r["client"] == _m["client"] and _re.search(_pat, r["role"], _re.I) for r in OPEN_DEMAND):
        continue
    _wks = [w for w, iso in zip(WEEKS, CONFIG["_week_iso"]) if iso >= _m.get("start", "")]
    OPEN_DEMAND.append({"client": _m["client"], "project": _m["project"], "role": _m["role"],
                        "hrs": _m.get("hrs_per_day", 8), "weeks": _wks, "geo": _m.get("geo", "us"),
                        "stage": _m.get("stage", "New open role (added manually; not yet in NetSuite)"),
                        "prob": None, "cat": "", "start": _m.get("start", ""), "pstatus": "Open role",
                        "ats": None})
    MANUAL_ACTIVE.append(_m)
OPEN_DEMAND.sort(key=lambda r: (r["client"], r["role"]))

# ---------------------------------------------------------------- roster meta
TITLES = {}
for name, title, jl, practice, country, region, target in (r[:7] for r in rows("raw/roster.json")):
    if name in EXCLUDE:
        continue
    TITLES[name] = {"title": title.strip(), "level": jl, "practice": practice,
                    "country": country, "region": region, "target": f(target)}

# PROJECT_META values are 4-TUPLES, not dicts: build_projects_section unpacks them as
# `client, pm, status, stage = meta`. Writing dicts here unpacks the keys instead, which
# silently files every project under a client literally named "customer" - shipped that
# way in Versions 23-24 before Mark spotted the grouping. Keep the tuple shape.
PROJECT_META = {}
for proj, cust, pm, pstat, stage in (r[:5] for r in rows("raw/projmeta.json")):
    PROJECT_META[proj] = (cust, pm, pstat, stage)
for _m in MANUAL_ACTIVE:
    PROJECT_META[_m["project"]] = (_m["client"], _m.get("pm", ""), "Open role", "New open role (manual)")

# ---------------------------------------------------------------- section 3
s3_raw = rows("raw/s3.json")   # name ~ practice ~ customer ~ project ~ alloc ~ actual ~ week(MMDD)
s3_rows = [(n, pr, cu, pj, f(a), f(ac)) for n, pr, cu, pj, a, ac, _wk in (r[:7] for r in s3_raw)]
_wk_tot = defaultdict(lambda: [0.0, 0.0])
for n, pr, cu, pj, a, ac, wk in (r[:7] for r in s3_raw):
    _wk_tot[wk][0] += f(a)
    _wk_tot[wk][1] += f(ac)
S3_WEEKS = [(S3_WEEK_LABELS[w], round(_wk_tot[w][0], 1), round(_wk_tot[w][1], 1)) for w in S3_WEEKS_ORDER if w in _wk_tot]
people = {r[0] for r in s3_rows}
S3_TOTAL = {"people": len(people),
            "alloc": round(sum(r[4] for r in s3_rows), 1),
            "actual": round(sum(r[5] for r in s3_rows), 1)}
acc = defaultdict(lambda: [set(), 0.0, 0.0])
for n, pr, cu, pj, a, ac in s3_rows:
    acc[cu][0].add(n)
    acc[cu][1] += a
    acc[cu][2] += ac
S3_ACCOUNTS = sorted((cu, len(v[0]), round(v[1], 1), round(v[2], 1)) for cu, v in acc.items())

by_person = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
prac_hours = defaultdict(lambda: defaultdict(float))
for n, pr, cu, pj, a, ac in s3_rows:
    by_person[n][pj][0] += a
    by_person[n][pj][1] += ac
    prac_hours[n][pr] += a + ac
# consultant x client account (Mark, Oct 20 2026): lets an account row open the consultants
# allocated to it and show who did not bill, and a consultant row open the accounts they did
# not bill to. [(consultant, practice, account, alloc, actual)], every nonzero pair.
_pair = defaultdict(lambda: [0.0, 0.0])
_pair_prac = {}
for n, pr, cu, pj, a, ac in s3_rows:
    if n in EXCLUDE:
        continue
    _pair[(n, cu)][0] += a
    _pair[(n, cu)][1] += ac
    _pair_prac[n] = pr
S3_PAIRS = sorted((n, _pair_prac[n], cu, round(v[0], 1), round(v[1], 1)) for (n, cu), v in _pair.items())

S3_CONSULTANTS = []
for n in sorted(by_person):
    if n in EXCLUDE:
        continue
    tot_a = sum(v[0] for v in by_person[n].values())
    tot_b = sum(v[1] for v in by_person[n].values())
    if abs(tot_b - tot_a) < 0.05:   # rolling view lists every nonzero variance (Sep 16 change)
        continue
    practice = max(prac_hours[n], key=lambda p: prac_hours[n][p])
    projs = sorted((pj, round(v[0], 1), round(v[1], 1)) for pj, v in by_person[n].items())
    S3_CONSULTANTS.append((n, practice, projs))
S3_CONSULTANTS.sort(key=lambda t: -abs(sum(p[2] for p in t[2]) - sum(p[1] for p in t[2])))

# ---------------------------------------------------------------- cohort
# Cohort rule (pinned in staffing-dashboard-spec.md): FLAG_UNDER_TARGET in any week of
# the current month through the next two, Direct, practice <> 'Grand Total', standing
# exclusions applied, and on the current-week roster (drops departures). Recomputing
# "monthly pct < target" directly instead of using the flag over-collects by ~8 people.
flags = defaultdict(dict)
for name, mid, target, nflag, nweeks, pct, npto, practice in (r[:8] for r in rows("raw/cohort.json")):
    if name in EXCLUDE:
        continue
    flags[name][mid] = {"target": f(target), "flag": int(nflag) > 0,
                        "pct": round(f(pct), 5) if pct else None,
                        "pto": int(npto), "practice": practice}
COHORT_MONTHS = MONTHS[:3]   # this month + next two: the fourth month out is too thinly booked to flag anyone on
COHORT = []
for name in sorted(flags):
    if name not in staff:          # no current-week availability row -> departed
        continue
    per = flags[name]
    if not any(per.get(m, {}).get("flag") for m in COHORT_MONTHS):
        continue
    any_month = next(iter(per.values()))
    COHORT.append({"name": name,
                   "practice": any_month["practice"],
                   "target": any_month["target"],
                   "pct": {m: per.get(m, {}).get("pct") for m in MONTHS},
                   "pto": {m: ["x"] * per.get(m, {}).get("pto", 0) for m in MONTHS}})

# Documented exception to the flag-only rule: FLAG_UNDER_TARGET is computed upstream from
# the same denominator that is missing for an imputed consultant, so it is never set for
# them and they drop out of the under-target headline band as well as the grid. Add them
# back on their imputed monthly values, or the band understates the gap.
for name in IMPUTED:
    if name in EXCLUDE or name not in staff or any(p["name"] == name for p in COHORT):
        continue
    p = staff[name]
    months = {}
    for m in MONTHS:
        wks = [w for w in WEEKS if w[:2] == m[4:] and p["weeks"][w][2]]
        months[m] = round(sum(p["weeks"][w][0] for w in wks) / len(wks), 5) if wks else None
    if any(months.get(m) is not None and months[m] < p["target"] - 1e-9 for m in COHORT_MONTHS):
        COHORT.append({"name": name, "practice": p["practice"], "target": p["target"],
                       "pct": months, "pto": {m: [] for m in MONTHS}})
COHORT.sort(key=lambda d: d["name"])

# ---------------------------------------------------------------- client history
HIST = defaultdict(dict)
for name, cust, hrs, nmonths, last in (r[:5] for r in rows("raw/history.json")):
    if name in EXCLUDE:
        continue
    HIST[name][cust] = (int(f(hrs)), int(nmonths), int(last))

# ---------------------------------------------------------------- emit
pp = pprint.PrettyPrinter(indent=1, width=112)


def w(path, header, body):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + "\n\n" + body)
    print(f"wrote {path}")


sd = [f'GENERATED = {GENERATED!r}', f'MEETING_DATE = {MEETING_DATE!r}',
      f'THIS_WEEK = {THIS_WEEK!r}', f'HOURS_CUTOFF = {HOURS_CUTOFF!r}',
      'SKILLS_CSV = "skills_matrix.csv"', '',
      f'MONTHS = {MONTHS!r}', f'MONTH_LABELS = {MONTH_LABELS!r}', f'COHORT_MONTHS = {COHORT_MONTHS!r}', '',
      f'ORG_MONTHLY = {pp.pformat(ORG_MONTHLY)}', f'ORG_THIS_IDX = {ORG_THIS_IDX}', '',
      f'COHORT = {pp.pformat(COHORT)}', '',
      'ALLOCATIONS = {}', 'OPEN_ROLES = []', '',
      f'S3_TOTAL = {S3_TOTAL!r}', '', f'S3_WEEKS = {S3_WEEKS!r}', '',
      f'S3_ACCOUNTS = {pp.pformat(S3_ACCOUNTS)}', '',
      f'S3_CONSULTANTS = {pp.pformat(S3_CONSULTANTS)}', '',
      f'S3_PAIRS = {pp.pformat(S3_PAIRS)}']
w("staffing_data.py",
  f'"""Staffing dashboard data - {GENERATED} refresh ({MEETING_DATE}).\n\n'
  "ORG_MONTHLY: CONS_WEEKLY_AVAILABILITY, PRACTICE='Grand Total'.\n"
  f"COHORT: under target in any of {'/'.join(MONTH_LABELS[m] for m in MONTHS)}, Direct, current-week roster,\n"
  "standing exclusions applied. Feeds only the consultants-under-target band.\n"
  f"S3_*: CONS_PROJECT_TIME, weeks of {S3_WEEK_LABELS[S3_WEEKS_ORDER[0]]} - {S3_WEEK_LABELS[S3_WEEKS_ORDER[-1]]} (rolling last 4 complete weeks). No cost columns.\n"
  '"""', "\n".join(sd))

od_out = [f'OUTLOOK_WEEKS = {WEEKS!r}', '', f'WEEK_LABELS = {pp.pformat(WEEK_LABELS)}', '',
          f'OUTLOOK_STAFF = {pp.pformat(staff)}', '',
          f'OUTLOOK_ALLOC = {pp.pformat(dict(alloc))}', '',
          f'OUTLOOK_BOOKED = {pp.pformat({k: round(v, 2) for k, v in booked.items()})}', '',
          '# Weeks whose utilization was imputed from booked hours because the view carried',
          '# no HRS_UTIL_DENOM. The consultant is on the roster and working; the denominator',
          '# is the thing that is missing. Cells render the figure with an "est." tag.',
          f'OUTLOOK_IMPUTED = {pp.pformat({k: sorted(v, key=WEEKS.index) for k, v in IMPUTED.items()})}', '',
          '# Active contractors with bookings in the window (Mark, Oct 20 2026). Shown in the 8 Week',
          '# Outlook only when "Include contractors" is on; not in capacity, suggestions or the cohort.',
          f'OUTLOOK_CONTRACTORS = {pp.pformat(CONTRACTORS)}', '',
          f'OUTLOOK_ALLOC_CONTRACT = {pp.pformat(dict(alloc_contract))}', '',
          f'OPEN_DEMAND = {pp.pformat(OPEN_DEMAND)}', '',
          'INTERNAL_ROLES = []', 'FILLED_ROLES = []', '', 'RECRUITING_WEEK = None']
w("outlook_data.py",
  f'"""8-Week Outlook data - {MEETING_DATE} ({GENERATED} refresh).\n\n'
  "Sources: CONS_WEEKLY_AVAILABILITY, CONS_CONSULTANT_PROJECT_DETAIL, CONS_OPEN_DEMAND.\n"
  f"Standing exclusions applied. Recruiting data ({ATS_SOURCE}, as of {ATS_AS_OF}) spliced in below.\n"
  '"""', "\n".join(od_out))

pm_out = [f'CONSULTANT_TITLES = {pp.pformat({k: (v["title"], v["level"]) for k, v in TITLES.items()})}',
          '',
          '# project -> (customer, project manager, project status, opportunity stage).',
          '# Tuple, not dict - build_projects_section unpacks it positionally.',
          f'PROJECT_META = {pp.pformat(PROJECT_META)}']
w("projects_meta.py", f'"""Consultant titles / job levels and project metadata - {GENERATED}."""', "\n".join(pm_out))

ch_out = [f'ROSTER_META = {pp.pformat(TITLES)}', '',
          f'CLIENT_HISTORY = {pp.pformat(dict(HIST))}']
w("client_history.py",
  '"""Per-consultant delivery history and roster attributes, for open-role suggestions.\n\n'
  "CLIENT_HISTORY[name][customer] = (actual billable hrs, months active, last MONTH_ID)\n"
  f"over MONTH_ID {HISTORY_FROM}-{HISTORY_TO} from CONS_PROJECT_TIME (Direct only, >= 8 hrs).\n"
  "ROSTER_META[name] = title / job level / practice / country / region / target.\n"
  '"""', "\n".join(ch_out))

print(f"\nstaff={len(staff)} cohort={len(COHORT)} alloc_cells={len(alloc)} "
      f"roles={len(OPEN_DEMAND)} s3_people={S3_TOTAL['people']} accounts={len(S3_ACCOUNTS)} "
      f"s3_flagged={len(S3_CONSULTANTS)} hist_people={len(HIST)}")
print("booked:", {k: round(booked[k], 1) for k in WEEKS})


# ---------------------------------------------------------------- recruiting ATS
# The weekly "all jobs status report" export. Matched onto the Salesforce demand lines
# where a requisition exists for one; requisitions with no demand line (practice
# director searches, SG&A hires, and client roles Salesforce has not scheduled) are
# carried separately so they still appear in Open Roles & Recruiting.
#
# Compensation never reaches this file: ats_parse drops the pay columns at read time
# and scrubs money language out of the status notes.
import os

ATS_BY_ROLE, UNMATCHED_REQS, RECRUITING_WEEK = {}, [], None
ATS_XLSX = ATS_JSON   # named in the outlook_data.py comment

if ATS_JSON and os.path.exists(ATS_JSON):
    import ats_parse

    _d = json.load(open(ATS_JSON))
    reqs = _d["reqs"] if isinstance(_d, dict) else _d

    # (requisition job name -> the OPEN_DEMAND role it staffs). Explicit rather than
    # fuzzy: there are never more than a dozen of each, and a wrong auto-match would
    # put one recruiter's update under someone else's role.
    # (requisition job name -> the OPEN_DEMAND role it staffs), from pipeline/config.json
    # "match". Explicit rather than fuzzy: there are never more than a dozen of each, and a
    # wrong auto-match would put one recruiter's update under someone else's role.
    MATCH = {job: (v[0], v[1]) for job, v in CONFIG.get("match", {}).items()}

    def ats_payload(q):
        return {"interviewing": q["interviewing"], "start": q["start"],
                "emp": q["emp"], "recruiter": q["recruiter"], "update": q["update"],
                "manager": q.get("manager") or "", "history": list(q.get("history") or []),
                "days_open": q["days_open"], "opened": q["opened"], "title": q.get("title") or q.get("job") or ""}

    matched_jobs = set()
    for q in reqs:
        key = MATCH.get(q["job"])
        if not key:
            continue
        for r in OPEN_DEMAND:
            if (r["client"], r["role"]) == key:
                r["ats"] = ats_payload(q)
                matched_jobs.add(q["job"])
                break

    for q in reqs:
        if q["job"] in matched_jobs:
            continue
        internal = not q["client"]
        UNMATCHED_REQS.append({
            "client": q["client"] or "Cleartelligence (internal)",
            "project": (f'{q["department"]}{" · " + q["portfolio"] if q["portfolio"] else ""}'
                        if internal else f'{q["department"]} (no scheduled demand in Salesforce)'),
            "role": q["job"],
            "hrs": 0, "weeks": [], "geo": ats_parse.geo_of(q["offices"]),
            "stage": "Internal hire" if internal else "Requisition only",
            "prob": None, "cat": "", "start": q["start"], "pstatus": "",
            "ats": ats_payload(q),
        })

    # Closed = a requisition in last week's pull that is gone now (PRIOR_JOBS comes from the
    # previous run's saved state). Filled hires are named in config.json "filled" for the week
    # they happened; recruiters' notes are not parsed for that.
    filled = [{k: v for k, v in x.items() if k != "week"}
              for x in CONFIG.get("filled", []) if x.get("week") == THIS_WEEK]
    cur_jobs = {q["job"] for q in reqs}
    closed = sorted(set(PRIOR_JOBS) - cur_jobs) if PRIOR_JOBS else []
    new_reqs = [q["job"] for q in reqs if (q.get("opened") or "") > NEW_REQ_SINCE]
    RECRUITING_WEEK = {
        "as_of": ATS_AS_OF,
        "filled": filled,
        "closed_reqs": closed,
        "closed_note": (f"Compared against the {PRIOR_ASOF} pull: a requisition present then and absent now "
                        "is listed as closed." if PRIOR_JOBS else
                        "No earlier pull to compare against, so no requisitions are listed as closed."),
        "new_reqs": new_reqs,
        "interviewing_total": sum(q["interviewing"] or 0 for q in reqs),
        "open_req_count": len(reqs),
        "oldest_days": max(((q["days_open"] or 0) for q in reqs), default=0),
        "no_req": [f'{r["client"]}: {r["role"]}' for r in OPEN_DEMAND if not r["ats"]],
    }

    # outlook_data.py was written above with ats=None on every role and empty recruiting
    # placeholders. Swap both blocks for the enriched versions rather than appending, or
    # the earlier definitions win and the updates never reach the page.
    src = open("outlook_data.py", encoding="utf-8").read()
    head, _, rest = src.partition("OPEN_DEMAND = ")
    _, _, tail = rest.partition("\nINTERNAL_ROLES = []\nFILLED_ROLES = []\n\nRECRUITING_WEEK = None\n")
    assert head and tail == "", "outlook_data.py layout changed - re-check the splice"
    src = (head
           + "OPEN_DEMAND = " + pp.pformat(OPEN_DEMAND) + "\n\n"
           + "# ---------------------------------------------------------------- recruiting\n"
           + f"# From {ATS_XLSX} (as of {ATS_AS_OF}). Compensation columns, and any money\n"
           + "# language in the free-text status notes, are stripped in ats_parse.py and\n"
           + "# never reach this file.\n"
           + f"INTERNAL_ROLES = {pp.pformat(UNMATCHED_REQS)}\n\n"
           + "FILLED_ROLES = []\n\n"
           + f"RECRUITING_WEEK = {pp.pformat(RECRUITING_WEEK)}\n")
    open("outlook_data.py", "w", encoding="utf-8").write(src)

    print(f"ats: {len(reqs)} reqs, {len(matched_jobs)} matched to demand lines, "
          f"{len(UNMATCHED_REQS)} without one, "
          f"{RECRUITING_WEEK['interviewing_total']} interviewing, "
          f"{len(RECRUITING_WEEK['no_req'])} demand lines with no requisition")
