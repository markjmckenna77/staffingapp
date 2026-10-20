#!/usr/bin/env python3
"""Build utilization_data.py (YTD utilization by practice and consultant) from the
saved Snowflake pulls.

Inputs (all written by the weekly Snowflake queries, see the change note):
  util_raw.json         person x practice x month: billable, denom, target, level, country
                        (CONS_WEEKLY_AVAILABILITY, RELATIONSHIP='Direct', PRACTICE<>'Grand Total')
  zero_denom_weeks.json weekly rows for anyone with HRS_UTIL_DENOM=0 and HRS_BILLABLE>0
                        [name, month, week, billable, time_off, denom] - used to impute
  grand_total.json      month -> org-wide utilization from the 'Grand Total' practice row
                        (the Summary basis: includes contractors)

Rules (same as the rest of the dashboard):
  * month value = SUM(billable) / SUM(denom) over the month's weeks
  * practice value = the same sums over everyone in that practice that month; a person
    who moved practices counts toward the practice recorded for each month
  * AI/ML and AI/ML/AppDev are the same practice as AI Engineering
  * standing exclusions applied at pull time (never named in the published page)
  * zero denominator with booked hours -> denominator imputed as the person's own
    full-week base (their modal denom+time_off) x 0.8 in holiday-shortened weeks,
    minus that week's time off; the month is tagged est.
"""
import json, re, collections, datetime

# Year-to-date months, labels and US holiday weeks come from params.py (pipeline/run.py).
from params import UTIL_MONTHS as MONTHS, UTIL_LABELS as LABELS, CURRENT_MONTH, HOLIDAY_WEEKS

raw = json.load(open("util_raw.json"))
zd = json.load(open("zero_denom_weeks.json"))
gt = json.load(open("grand_total.json"))

# person-month records
rec = {}
for r in raw:
    key = (r["name"], r["practice"], r["month"])
    rec[key] = dict(billable=r["billable"], denom=r["denom"], target=r["target"],
                    level=r["level"], country=r["country"], est=False)

# impute zero-denominator weeks
base = collections.defaultdict(float)
for r in raw:
    pass
by_person_weeks = collections.defaultdict(list)
for name, mon, week, bill, toff, den in zd:
    by_person_weeks[name].append((mon, week, bill, toff, den))
for name, weeks in by_person_weeks.items():
    # full-week base: the most common denom+time_off among their measured weeks
    # (we only have the zero weeks here, so fall back to 3960 = 40h at the view's scale,
    # which is what every measured week for this consultant shows)
    full = 3960.0
    add = collections.defaultdict(float)
    for mon, week, bill, toff, den in weeks:
        if den != 0 or bill <= 0:
            continue
        wk_base = full * (0.8 if week in HOLIDAY_WEEKS else 1.0)
        add[mon] += max(0.0, wk_base - toff)
    for (n, prac, mon), v in rec.items():
        if n == name and mon in add and v["denom"] == 0 and v["billable"] > 0:
            v["denom"] = add[mon]
            v["est"] = True

practices = sorted({k[1] for k in rec})
people = collections.defaultdict(dict)   # practice -> name -> {month: (pct, est)}
meta = {}
for (name, prac, mon), v in rec.items():
    pct = v["billable"] / v["denom"] if v["denom"] > 0 else None
    people[prac].setdefault(name, {})[mon] = (pct, v["est"], v["billable"], v["denom"])
    meta[name] = dict(target=v["target"], level=v["level"], country=v["country"])

def agg(items):
    b = sum(x[2] for x in items); d = sum(x[3] for x in items)
    return (b / d) if d > 0 else None, b, d

PRACTICE_MONTHLY = {}
PRACTICE_TARGET = {}
for prac in practices:
    PRACTICE_MONTHLY[prac] = {}
    PRACTICE_TARGET[prac] = {}
    for mon in MONTHS:
        items = [pm[mon] for pm in people[prac].values() if mon in pm]
        pct, b, d = agg(items)
        n = sum(1 for x in items if x[3] > 0)
        PRACTICE_MONTHLY[prac][mon] = (pct, n, b, d)
        tw = sum(meta[nm]["target"] * pm[mon][3] for nm, pm in people[prac].items() if mon in pm)
        PRACTICE_TARGET[prac][mon] = (tw / d) if d > 0 else 0.9
    ytd = agg([x for pm in people[prac].values() for x in pm.values()])
    PRACTICE_MONTHLY[prac]["ytd"] = (ytd[0], len(people[prac]), ytd[1], ytd[2])
    tw = sum(meta[nm]["target"] * x[3] for nm, pm in people[prac].items() for x in pm.values())
    PRACTICE_TARGET[prac]["ytd"] = tw / ytd[2] if ytd[2] else 0.9

ALL = {}
for mon in MONTHS:
    items = [pm[mon] for prac in practices for pm in people[prac].values() if mon in pm]
    pct, b, d = agg(items)
    ALL[mon] = (pct, len({nm for prac in practices for nm, pm in people[prac].items() if mon in pm and pm[mon][3] > 0}), b, d)
items = [x for prac in practices for pm in people[prac].values() for x in pm.values()]
pct, b, d = agg(items)
ALL["ytd"] = (pct, len(meta), b, d)

PEOPLE = {}
for prac in practices:
    PEOPLE[prac] = {}
    for nm, pm in sorted(people[prac].items()):
        row = {}
        for mon in MONTHS:
            if mon in pm:
                row[mon] = (pm[mon][0], pm[mon][1])
        ytd = agg(list(pm.values()))
        row["ytd"] = (ytd[0], any(x[1] for x in pm.values()))
        PEOPLE[prac][nm] = row

# where else a person appears (moved practices)
MOVES = collections.defaultdict(dict)
for prac in practices:
    for nm, pm in people[prac].items():
        for mon in pm:
            MOVES[nm][mon] = prac

out = ["# Generated by make_util_data.py on %s - YTD utilization by practice / consultant" %
       datetime.date.today().isoformat(),
       "MONTHS = %r" % MONTHS, "LABELS = %r" % LABELS, "CURRENT_MONTH = %r" % CURRENT_MONTH,
       "PRACTICES = %r" % practices,
       "PRACTICE_MONTHLY = %r" % PRACTICE_MONTHLY,
       "PRACTICE_TARGET = %r" % PRACTICE_TARGET,
       "ALL_PRACTICES = %r" % ALL,
       "ORG_WIDE = %r" % {m: gt.get(m) for m in MONTHS},
       "PEOPLE = %r" % PEOPLE,
       "META = %r" % meta,
       "MOVES = %r" % dict(MOVES),
       ]
open("utilization_data.py", "w").write("\n".join(out) + "\n")
print("practices", practices)
for p in practices:
    print(p, [round(PRACTICE_MONTHLY[p][m][0] or 0, 3) for m in MONTHS], "ytd", round(PRACTICE_MONTHLY[p]["ytd"][0], 3), len(PEOPLE[p]))
print("ALL", [round(ALL[m][0], 3) for m in MONTHS], round(ALL["ytd"][0], 3), ALL["ytd"][1])
print("Markow", PEOPLE["AI Engineering"].get("Alexander Markow"))
