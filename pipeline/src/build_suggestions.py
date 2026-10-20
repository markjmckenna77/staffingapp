#!/usr/bin/env python3
"""Open-role suggestions from current staff.

For every unfilled role in outlook_data.OPEN_DEMAND, ranks the roster and returns the
top few consultants with a plain-language reason. Added Sep 14 2026; replaces the
never-rendered `fits_for()` in build_dashboard.py, which scored a hand-set list of
three skills per role against the Section 1 cohort only.

Five signals, 100 points:

  availability 40  free hours in exactly the weeks the role needs
                   (40 hrs/wk minus scheduled PTO minus hours already booked)
  client       20  billable hours for that customer in the last 12 months
  skills       25  skills-matrix ratings on the technologies named in the role title
  discipline   10  practice vs. the discipline the role names
  seniority     5  job level vs. the seniority the role names

Geography is a hard filter, not a score: a US role does not suggest CTI staff and the
reverse. If fewer than MIN_POOL people survive the filter the role says so rather than
silently widening.

Inputs
  outlook_data.OUTLOOK_STAFF / OUTLOOK_ALLOC / OPEN_DEMAND   this week's schedule
  client_history.CLIENT_HISTORY / ROSTER_META                12 months of delivery
  skills_matrix.csv                                          Skills Matrix 2025
                                                             (Nov 2025 consolidation)

The skills matrix is optional: with the file absent or a consultant missing from it,
the skills component scores 0 and the reason line says so, so an unrated person is
never silently ranked as a poor fit.
"""
from params import RECENT_MONTH_ID   # MONTH_ID two months back: client work since then reads 'current'
import csv
import os
import re
from collections import defaultdict

import outlook_data as O

try:
    import client_history as CH
except Exception:                                            # pragma: no cover
    CH = None

SKILLS_CSV = "skills_matrix.csv"
TOP_N = 3
MIN_POOL = 3
MIN_SCORE = 20.0          # below this the match is noise; drop it rather than pad to 3
MIN_FREE = 6.0            # hrs/wk; less than this is not a candidate, it is a rounding error
MIN_RATING = 3            # skills-matrix rating that counts as a real skill

W_AVAIL, W_CLIENT, W_SKILL, W_DISC, W_SEN = 40.0, 20.0, 25.0, 10.0, 5.0


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def key(s):
    return norm(s).lower()


# ---------------------------------------------------------------- disciplines

# (regex on the role title, practices that fit, skills-matrix categories that fit,
#  extra skill names to look for)
DISCIPLINES = [
    (r"\bpm\b|project manager|program manager|portfolio",
     {"Portfolio Mgmt", "Delivery"}, {"Business Practices"},
     ["Project Management", "Agile", "Scrum"]),
    (r"data governance|governance|steward",
     {"Data Management"}, {"Data Management"},
     ["Data Governance", "Data Quality", "Data Cataloging", "MDM"]),
    (r"solution architect|architect",
     {"Solution Architecture"}, {"Data Engineering", "Data Management"}, []),
    (r"full stack|software engineer|\bai\b|ai/ml|\bml\b|machine learning|genai",
     {"AI Engineering"}, {"AI/ML & Data Science", "Languages/Frameworks"},
     ["Python", "AI/ML & Data Science"]),
    (r"dv&a|data viz|visuali[sz]ation|dashboard|analytics|reporting|\bbi\b",
     {"Data Viz. & Analytics"}, {"Data Visualization", "Data Analytics"}, []),
    (r"data engineer|data engineering|ingestion|etl|pipeline|accelerator",
     {"Data Management"}, {"Data Engineering", "Date Engineering"},
     ["SQL", "Python (ETL and Ingestion)"]),
]

SENIORITY = [
    (r"director|principal|head of", 3),
    (r"\bsr\.?\b|senior|tech lead|team lead|\blead\b", 2),
]
LEVEL_RANK = {
    "Associate Consultant": 0, "Consultant": 1, "Senior Consultant": 2,
    "Lead/Specialist": 3, "Manager/Expert": 4, "Principal/Director": 5,
    "Sr Principal/Director": 6, "Officer/Exec": 7,
}
# Seniority the role names -> the job level it is really asking for, and the band of
# levels worth suggesting. The ceiling matters more than the floor: practice directors
# carry 50% utilization targets, so they show up with the most free hours on the roster
# and would otherwise top every list regardless of what the role actually needs.
WANT_LEVEL = {1: 2, 2: 3, 3: 5}
LEVEL_BAND = {1: (0, 3), 2: (1, 4), 3: (3, 7)}
# Disciplines where a director or practice lead genuinely is the right answer.
SENIOR_OK = {"Portfolio Mgmt", "Solution Architecture"}

# Categories that describe what someone can build. The rest of the matrix is soft
# skills, office tools and industry exposure - real, but not what fills an open role,
# and left out so a reason line never reads "Empathy 5/5".
TECH_CATEGORIES = {
    "Data Engineering", "Date Engineering", "Data Management", "Data Visualization",
    "Data Analytics", "AI/ML & Data Science", "Languages/Frameworks",
    "Infrastructure/Security", "Design",
}
# Explicit allowlist for delivery-management roles, whose skills live in the
# soft-skill categories that TECH_CATEGORIES deliberately excludes.
PM_SKILLS = {"Project Management", "Project Portfolio Management", "Agile", "Scrum",
             "Program Management", "Change Management", "Requirements Gathering"}


def role_profile(role_title, catalog):
    """Role title -> {skills, practices, categories, seniority}."""
    t = key(role_title)
    practices, categories, want = set(), set(), set()
    for pattern, pracs, cats, extra in DISCIPLINES:
        if re.search(pattern, t):
            practices |= pracs
            categories |= cats
            want |= {s for s in extra if s in catalog}
    # named technologies: any catalog skill whose head term appears in the title
    for skill in catalog:
        head = key(re.split(r"\s*[-(/]", skill)[0])
        if len(head) < 3 or head in ("data", "sql", "design", "other"):
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(head) + r"(?![a-z0-9])", t):
            want.add(skill)
    sen = 1
    for pattern, rank in SENIORITY:
        if re.search(pattern, t):
            sen = max(sen, rank)
    return {"skills": want, "practices": practices, "categories": categories, "seniority": sen}


# ---------------------------------------------------------------- skills matrix

def load_skills(path=SKILLS_CSV):
    """name -> {skill: rating}, plus the skill catalog and skill -> category."""
    by_person, catalog, cat_of = defaultdict(dict), set(), {}
    if not os.path.exists(path):
        print("  note: no skills matrix on disk - suggestions run without the skills signal")
        return by_person, catalog, cat_of
    alias = {key(n): n for n in O.OUTLOOK_STAFF}
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            skill = norm(row.get("Technology/Skill"))
            if not skill:
                continue
            catalog.add(skill)
            cat_of.setdefault(skill, norm(row.get("Category")))
            who = alias.get(key(row.get("Name")))
            if not who:
                continue
            try:
                rating = float(row.get("Skill Rating") or 0)
            except ValueError:
                rating = 0.0
            if rating > by_person[who].get(skill, 0):
                by_person[who][skill] = rating
    return by_person, catalog, cat_of


# ---------------------------------------------------------------- availability

BASE_WEEK = 40.0


def free_hours(name, wk):
    pct, pto, meas = O.OUTLOOK_STAFF[name]["weeks"][wk]
    booked = sum(h for h, _ in O.OUTLOOK_ALLOC.get((name, wk), []))
    return max(0.0, BASE_WEEK * (1.0 - pto) - booked)


def booked_pct(name, weeks):
    vals = []
    for wk in weeks:
        pct, pto, meas = O.OUTLOOK_STAFF[name]["weeks"][wk]
        if pto < 0.99:
            vals.append(pct / (1.0 - pto) if pto > 0 else pct)
    return sum(vals) / len(vals) if vals else 0.0


# ---------------------------------------------------------------- geography

def geo_of_person(name):
    meta = (CH.ROSTER_META.get(name) if CH else None) or {}
    country = meta.get("country") or ""
    if country == "India":
        return "india"
    if country == "United States":
        return "us"
    return "eu"


# ---------------------------------------------------------------- scoring

def projects_in_window(name):
    out = set()
    for (who, wk), rows in O.OUTLOOK_ALLOC.items():
        if who == name:
            out |= {p for _, p in rows}
    return out


def score_role(role, skills_by_person, catalog, cat_of):
    prof = role_profile(role["role"], catalog)
    weeks = role["weeks"] or O.OUTLOOK_WEEKS
    need_per_week = role["hrs"] * 5.0
    geo = role["geo"]
    out = []
    for name in O.OUTLOOK_STAFF:
        if geo_of_person(name) != geo:
            continue
        meta = (CH.ROSTER_META.get(name) if CH else None) or {}
        why = []

        # --- availability
        frees = [free_hours(name, wk) for wk in weeks]
        mean_free = sum(frees) / len(frees)
        avail = W_AVAIL * min(1.0, mean_free / need_per_week) if need_per_week else 0.0
        util = booked_pct(name, weeks)

        # --- client familiarity
        hist = (CH.CLIENT_HISTORY.get(name, {}) if CH else {})
        hrs, months, last = hist.get(role["client"], (0, 0, 0))
        client = W_CLIENT * min(1.0, hrs / 400.0)
        on_project = role["project"] in projects_in_window(name)
        if on_project:
            client = W_CLIENT          # already booked to this exact project
        # --- skills. Named technologies first; fall back to the strongest ratings in
        # the role's technical categories only when the title named none.
        sk = skills_by_person.get(name, {})
        named = [(s, sk[s]) for s in prof["skills"] if sk.get(s, 0) >= MIN_RATING]
        pool_cats = (prof["categories"] & TECH_CATEGORIES) or set()
        backup = [(s, r) for s, r in sk.items()
                  if r >= 4 and (cat_of.get(s) in pool_cats
                                 or (s in PM_SKILLS and "Portfolio Mgmt" in prof["practices"]))]
        named.sort(key=lambda t: (-t[1], t[0]))
        backup.sort(key=lambda t: (-t[1], t[0]))
        matched = named or backup
        if prof["skills"] or pool_cats:
            denom = max(2, min(4, len(prof["skills"]) or 3))
            weight = 1.0 if named else 0.6      # a category match is weaker evidence
            skill = W_SKILL * weight * min(1.0, sum(r for _, r in matched[:4]) / (denom * 5.0))
        else:
            skill = 0.0
        rated = name in skills_by_person
        strong_named = sum(1 for _, r in named if r >= 4)

        # --- discipline and seniority are gates, not bonuses. A role that names a
        # discipline only suggests that practice, unless the person clears the bar on
        # the named technologies anyway (real cross-practice moves do happen).
        practice = meta.get("practice")
        in_practice = practice in prof["practices"]
        if prof["practices"] and not in_practice and strong_named < 2:
            continue
        rank = LEVEL_RANK.get(meta.get("level"), 1)
        lo, hi = LEVEL_BAND[prof["seniority"]]
        if prof["practices"] & SENIOR_OK:
            hi = 7
        if not lo <= rank <= hi:
            continue
        disc = W_DISC if in_practice else W_DISC * 0.4
        want = WANT_LEVEL[prof["seniority"]]
        sen = W_SEN * max(0.0, 1.0 - abs(rank - want) / 4.0)

        total = avail + client + skill + disc + sen
        if total < MIN_SCORE or mean_free < MIN_FREE:
            continue

        # --- reason line, strongest facts first
        if on_project:
            why.append(f"already booked on {role['project']}")
        elif hrs:
            ago = "current" if last >= RECENT_MONTH_ID else f"through {str(last)[4:]}/{str(last)[:4]}"
            why.append(f"{hrs:,} hrs on {role['client']} over {months} mo ({ago})")
        if matched:
            why.append(", ".join(f"{s} {int(r)}/5" for s, r in matched[:3]))
        elif not rated:
            why.append("no skills-matrix entry")
        if meta.get("title"):
            why.append(norm(meta["title"]))
        why.append(f"{mean_free:.0f} free hrs/wk of {need_per_week:.0f} needed"
                   f" · {util * 100:.0f}% booked {O.WEEK_LABELS[weeks[0]]}"
                   f"–{O.WEEK_LABELS[weeks[-1]]}")

        out.append({"name": name, "score": round(total, 1), "why": why,
                    "free": round(mean_free, 1), "covers": round(min(1.0, mean_free / need_per_week), 2)
                    if need_per_week else 0.0})
    out.sort(key=lambda d: (-d["score"], d["name"]))
    return prof, out


def suggest_all():
    skills_by_person, catalog, cat_of = load_skills()
    result = {}
    for role in O.OPEN_DEMAND:
        prof, ranked = score_role(role, skills_by_person, catalog, cat_of)
        result[(role["client"], role["project"], role["role"])] = {
            "top": ranked[:TOP_N],
            "pool": len(ranked),
            "thin": len(ranked) < MIN_POOL,
            "skills_used": sorted(prof["skills"])[:6],
        }
    return result


if __name__ == "__main__":
    res = suggest_all()
    for role in O.OPEN_DEMAND:
        k = (role["client"], role["project"], role["role"])
        r = res[k]
        print(f"\n{role['client']}: {role['role']}  [{role['geo']}, {role['hrs']}h/d, "
              f"{O.WEEK_LABELS[role['weeks'][0]]}-{O.WEEK_LABELS[role['weeks'][-1]]}]")
        print(f"  role skills read from title: {r['skills_used'] or '(discipline only)'}")
        print(f"  pool {r['pool']}")
        for s in r["top"]:
            print(f"   {s['score']:5.1f}  {s['name']:<26} {' · '.join(s['why'])}")
