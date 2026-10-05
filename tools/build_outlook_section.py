#!/usr/bin/env python3
"""Renders the '8-Week Staffing Outlook' section (section4) of the Cleartelligence
Staffing Dashboard: capacity-vs-need summary, per-consultant weekly grid, and
open-roles weekly demand table.

Emits section4.html - FOUR titled sections: '8 Week Outlook' (staff grid,
avg-utilization badge per name), 'Capacity vs. Need' (with a shared commentary textarea
under the header, db doc role_comments/section-capacity-vs-need), 'Open Roles &
Recruiting' (bold 'Client: Role' titles; geography filter with live totals; 'Recruiting
Update:' lines with the ATS date prefix stripped; a shared per-role comment textarea
saved at role_comments/<role_key>, stable slugs so comments survive weekly rebuilds;
FILLED roles excluded from OPEN_DEMAND), and 'Recruiting Activity' (from
O.RECRUITING_WEEK). CSS lives in dashboard_style.css. Data shapes:
claude/outlook_data_2026-09-09.py; queries: run log. WEEK_BASE marks holiday weeks.

Sep 10 2026 (Mark): every week cell now carries a line for EVERY project the
consultant is booked to that week. The default view still shows the largest two
plus a '+n more' control when there are more than three, but the hidden lines are
in the DOM and open in place: clicking '+n more' expands that one cell, and the
'Expand all projects' button above the grid opens every cell at once. Each project
line also carries the full project name(s) behind it as a tooltip, since the visible
label is only the short client tag.
"""
import html
import re
from collections import defaultdict

import outlook_data as O

WEEKS = O.OUTLOOK_WEEKS
WL = O.WEEK_LABELS


def e(s):
    return html.escape(str(s), quote=True)


def pct_str(v):
    return int(v * 100 + 0.5)


# ---------------------------------------------------------------- status logic

def cell_status(pct, pto, target, measured):
    """at/above/below vs target, judged net of PTO (matches upstream FLAG_UNDER_TARGET
    behavior of not penalizing PTO weeks). Below-severity uses the dashboard's
    percentage-point gap bands."""
    if not measured:
        return "na"
    if pto >= 0.99:
        return "pto"
    eff = pct / (1.0 - pto) if pto > 0 else pct
    if eff > target + 0.015:
        return "above"
    if eff >= target - 0.01:
        return "at"
    gap = (target - eff) * 100.0
    if gap <= 20:
        return "warning"
    if gap < 50:
        return "serious"
    return "critical"


# ---------------------------------------------------------------- client tags

TAG_PREFIXES = [
    ("Boston Scientific", "BSC"), ("BSC", "BSC"), ("Analytics COE", "BSC Studio"),
    ("Verizon", "Verizon"), ("DoorDash", "DoorDash"), ("New Leaders", "New Leaders"),
    ("Proceed", "Proceed"), ("Tokyo Century", "Tokyo"), ("TJX", "TJX"),
    ("Stellix", "Stellix"), ("Merz", "Merz"), ("NOV", "NOV"), ("HBP", "HBP"),
    ("NYL", "NYL"), ("Cisco", "Cisco"), ("BBU", "BBU"), ("Octapharma", "Octapharma"),
    ("Taiho", "Taiho"), ("Dynapar", "Dynapar"), ("Care Hospice", "Care Hospice"),
    ("SMPA", "SMPA"), ("Affiliated Dist", "Aff. Dist"), ("Industrial Physics", "Ind. Physics"),
    ("Yellowstone", "Yellowstone"), ("Ascend", "Ascend"), ("Direxion", "Direxion"),
    ("Katz", "Katz"), ("Tompkins", "Tompkins"), ("Counsel Press", "Counsel Press"),
    ("CFS", "CFS"), ("800 Reports", "800 Reports"), ("CT India", "CT India"),
    ("Internal", "Internal"), ("Authorized", "Authorized"), ("Bloomberg", "Bloomberg"),
    ("Tufts", "Tufts"), ("Sunovion", "Sunovion"), ("Xerox", "Xerox"),
]


def client_tag(project):
    for pre, tag in TAG_PREFIXES:
        if project.startswith(pre):
            return tag
    return project.split(" - ")[0].split("-")[0].strip()[:12]


CLIENT_SHORT = {"Ascend Partner Services": "Ascend", "Harvard Business Publishing": "HBP",
                "Cleartelligence (internal)": "Internal"}

GEO_LABELS = [("all", "All roles"), ("us", "US"), ("eu", "EU"), ("india", "India (CTI)")]


# ---------------------------------------------------------------- capacity math

# Base workweek hours: 40, except holiday-shortened weeks (allocations in
# CONS_CONSULTANT_PROJECT_DETAIL confirm a 32-hour base the week of Labor Day).
WEEK_BASE = {"1123": 32.0}   # Thanksgiving week (Nov 23 2026) is a 4-day week


def base_hours(wk):
    return WEEK_BASE.get(wk, 40.0)


def capacity_hours(wk):
    b = base_hours(wk)
    return sum(b * (1.0 - p["weeks"][wk][1]) for p in O.OUTLOOK_STAFF.values())


def capacity_at_target_hours(wk):
    """Each consultant's PTO-adjusted base hours scaled by their personal utilization
    target - the billable hours the org plans for, rather than the physical maximum."""
    b = base_hours(wk)
    return sum(b * p["target"] * (1.0 - p["weeks"][wk][1]) for p in O.OUTLOOK_STAFF.values())


def demand_hours(r, wk):
    """Hours this demand line needs in one week. 'hrs' is per DAY, so the usual case
    scales it by the week; a line carrying 'hrs_wk' (a vacated allocation, which ramps
    with the project's start date) states each week's hours outright and wins."""
    by_wk = r.get("hrs_wk")
    if by_wk and wk in by_wk:
        return float(by_wk[wk])
    return r["hrs"] * base_hours(wk) / 8.0


def open_hours(wk):
    return sum(demand_hours(r, wk) for r in O.OPEN_DEMAND if wk in r["weeks"])


def summary_rows():
    rows = []
    for wk in WEEKS:
        cap = capacity_hours(wk)
        capt = capacity_at_target_hours(wk)
        booked = O.OUTLOOK_BOOKED[wk]
        open_h = open_hours(wk)
        need = booked + open_h
        rows.append((wk, cap, capt, booked, open_h, need, cap - need))
    return rows


# ---------------------------------------------------------------- chart

def capacity_chart(rows):
    top = max(max(r[1] for r in rows), max(r[5] for r in rows)) * 1.08

    def y(v):
        return round(204.0 - (v / top) * 180.0, 1)

    parts = ['  <svg class="capacity-chart" viewBox="0 0 1080 240" role="img" '
             'aria-label="Weekly capacity versus need, 8 weeks">']
    for i, (wk, cap, capt, booked, open_h, need, surplus) in enumerate(rows):
        x0 = 40.0 + i * 130.0
        bx = x0 + 22.0
        yb = y(booked)
        yn = y(need)
        parts.append(f'    <rect x="{bx}" y="{yb}" width="60" height="{round(204.0 - yb, 1)}" '
                     f'class="cap-bar-booked" rx="3"/>')
        if open_h > 0:
            parts.append(f'    <rect x="{bx}" y="{yn}" width="60" height="{round(yb - yn, 1)}" '
                         f'class="cap-bar-open" rx="3"/>')
        yc = y(cap)
        yct = y(capt)
        parts.append(f'    <line x1="{x0 + 8.0}" y1="{yc}" x2="{x0 + 118.0}" y2="{yc}" class="cap-line"/>')
        parts.append(f'    <line x1="{x0 + 8.0}" y1="{yct}" x2="{x0 + 118.0}" y2="{yct}" class="cap-line-target"/>')
        lbl_y = round(min(yn, yc) - 6.0, 1)
        parts.append(f'    <text x="{bx + 30.0}" y="{lbl_y}" class="bar-val-label" '
                     f'text-anchor="middle">{need:,.0f}</text>')
        parts.append(f'    <text x="{bx + 30.0}" y="222.0" class="util-mo-label" '
                     f'text-anchor="middle">{WL[wk]}</text>')
    parts.append("  </svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------- staff grid

# How many project lines a cell shows before the rest go behind "+n more".
VISIBLE_PROJECTS = 2
# ...but a cell with only one more than that shows them all rather than hiding one.
COLLAPSE_ABOVE = 3


def imputed(name, wk=None):
    """True when this consultant's utilization came from booked hours rather than the
    view's own denominator (see outlook_data.OUTLOOK_IMPUTED)."""
    weeks = getattr(O, "OUTLOOK_IMPUTED", {}).get(name)
    if not weeks:
        return False
    return True if wk is None else wk in weeks


def staff_cell(name, wk):
    pct, pto, meas = O.OUTLOOK_STAFF[name]["weeks"][wk]
    target = O.OUTLOOK_STAFF[name]["target"]
    st = cell_status(pct, pto, target, meas)
    allocs = O.OUTLOOK_ALLOC.get((name, wk), [])
    tip_bits = [f"{proj} ({h:g}h)" for h, proj in allocs]
    if pto >= 0.99:
        tip_bits.append("Full-week PTO")
    elif pto > 0:
        tip_bits.append(f"PTO {pto * 5:.0f}d")
    if imputed(name, wk):
        tip_bits.append("Estimated: the source view carries no utilization denominator "
                        "for this consultant, so the percentage is booked hours over a "
                        "40-hour week net of PTO")
    if not meas:
        tip_bits.append("Excluded from utilization measurement (zero denominator)")
    tip = e(f"{WL[wk]}: " + ("; ".join(tip_bits) if tip_bits else "no billable allocations"))

    if st == "na":
        return f'<td class="wk"><div class="wk-cell wk-na" title="{tip}">n/m</div></td>'
    if st == "pto":
        return f'<td class="wk"><div class="wk-cell wk-pto" title="{tip}">PTO</div></td>'
    pto_chip = f'<span class="pto-chip">PTO {pto * 5:.0f}d</span>' if pto > 0.01 else ""
    if imputed(name, wk):
        pto_chip += '<span class="est-chip" title="Estimated from booked hours">est.</span>'

    # one line per project: allocation % (share of the week) + client tag. Projects
    # for the same client are merged onto one line; the line's tooltip names them all.
    totals = {}
    projects = defaultdict(list)
    for h, proj in allocs:  # already sorted by hours desc
        t = client_tag(proj)
        totals[t] = totals.get(t, 0.0) + h
        projects[t].append((proj, h))
    tot_h = sum(totals.values())
    lines = []
    for t, h in sorted(totals.items(), key=lambda kv: -kv[1]):
        if pct > 0.005 and tot_h > 0:
            share = h / tot_h * pct * 100.0
        else:
            share = h / base_hours(wk) * 100.0
        full = "; ".join(f"{p} ({hh:g}h)" for p, hh in projects[t])
        lines.append((int(share + 0.5), t, full))

    if len(lines) > COLLAPSE_ABOVE:
        shown, hidden = lines[:VISIBLE_PROJECTS], lines[VISIBLE_PROJECTS:]
    else:
        shown, hidden = lines, []

    bits = [f'<div class="wk-proj" title="{e(full)}">{p}% {e(t)}</div>'
            for p, t, full in shown]
    bits += [f'<div class="wk-proj wk-proj-extra" title="{e(full)}">{p}% {e(t)}</div>'
             for p, t, full in hidden]
    if hidden:
        n = len(hidden)
        bits.append(f'<button type="button" class="wk-proj wk-proj-more" aria-expanded="false" '
                    f'data-more="+{n} more" data-less="show less" '
                    f'aria-label="Show all {len(lines)} projects for {e(name)}, {e(WL[wk])}">'
                    f'+{n} more</button>')
    tag_html = "".join(bits) if bits else '<div class="wk-proj wk-clients-none">&mdash;</div>'
    return (f'<td class="wk"><div class="wk-cell wk-{st}" title="{tip}">'
            f'<span class="wk-pct">{pct_str(pct)}%</span>{pto_chip}{tag_html}</div></td>')


EXPAND_JS = """<script>
(function () {
  var grid = document.getElementById("staff-grid");
  var btn = document.getElementById("outlook-expand-all");
  if (!grid) return;

  function collapseAllCells() {
    grid.querySelectorAll(".wk-cell.wk-expanded").forEach(function (c) {
      c.classList.remove("wk-expanded");
    });
    grid.querySelectorAll(".wk-proj-more").forEach(function (b) {
      b.setAttribute("aria-expanded", "false");
      b.textContent = b.dataset.more;
    });
  }

  grid.addEventListener("click", function (ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest(".wk-proj-more") : null;
    if (!b) return;
    var cell = b.closest(".wk-cell");
    if (!cell) return;
    var open = cell.classList.toggle("wk-expanded");
    b.setAttribute("aria-expanded", open ? "true" : "false");
    b.textContent = open ? b.dataset.less : b.dataset.more;
  });

  if (!btn) return;
  btn.addEventListener("click", function () {
    var on = grid.classList.toggle("show-all-projects");
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.classList.toggle("outlook-btn-active", on);
    btn.textContent = on ? "Collapse all projects" : "Expand all projects";
    if (!on) collapseAllCells();
  });
})();
</script>"""


def staff_grid():
    by_practice = defaultdict(list)
    for name, p in O.OUTLOOK_STAFF.items():
        by_practice[p["practice"]].append(name)
    head = "".join(f'<th class="wk">{WL[w]}</th>' for w in WEEKS)
    out = ['      <div class="outlook-scroll"><table class="outlook-table staff-grid" id="staff-grid">',
           f'        <thead><tr><th>Consultant</th>{head}</tr></thead>',
           "        <tbody>"]
    ncols = len(WEEKS) + 1
    for pi, practice in enumerate(sorted(by_practice)):
        names = sorted(by_practice[practice])
        out.append(f'        <tr class="outlook-practice-row prac-{pi}"><td colspan="{ncols}">{e(practice)}'
                   f' <span class="count-chip">{len(names)}</span></td></tr>')
        for name in names:
            target = O.OUTLOOK_STAFF[name]["target"]
            badge = ""
            if abs(target - 0.9) > 1e-9:
                badge = f'<span class="target-badge">Target: {pct_str(target)}%</span>'
            effs = []
            for w in WEEKS:
                pct, pto, meas = O.OUTLOOK_STAFF[name]["weeks"][w]
                if meas and pto < 0.99:
                    effs.append(pct / (1.0 - pto) if pto > 0 else pct)
            if effs:
                avg = sum(effs) / len(effs)
                ucls = "util-badge-under" if avg < target - 0.01 else ""
                est = (" &middot; estimated from booked hours, since the source view carries no "
                       "utilization denominator for this consultant") if imputed(name) else ""
                util = (f'<span class="util-badge {ucls}" title="Average scheduled utilization across '
                        f'the 8 weeks, net of PTO{est}">{pct_str(avg)}%'
                        f'{"<i> est.</i>" if imputed(name) else ""}</span>')
            else:
                util = '<span class="util-badge" title="Not measured">n/m</span>'
            cells = "".join(staff_cell(name, w) for w in WEEKS)
            out.append(f'        <tr><td class="grid-name">{e(name)}{util}{badge}</td>{cells}</tr>')
    out.append("        </tbody>")
    out.append("      </table></div>")
    out.append(EXPAND_JS)
    return "\n".join(out)


# ---------------------------------------------------------------- open roles grid

def role_cell(r):
    """Role card: title with the interviewing pill beside it, project, then one chip
    row (stage combined with probability/category, target start, emp/recruiter).
    The recruiting update and possible fits render in a full-width sub-row."""
    ats = r.get("ats")
    pill = ""
    if ats and ats["interviewing"] is not None:
        n = ats["interviewing"]
        cls = "status-good" if n >= 3 else ("status-warning" if n >= 1 else "status-critical")
        pill = f' <span class="interviewing-pill {cls}">{n} interviewing</span>'
    short = CLIENT_SHORT.get(r["client"], r["client"])
    bits = [f'<div class="demand-role">{e(short)}: {e(r["role"])}{pill}</div>']
    proj = r["project"] or r["client"]
    bits.append(f'<div class="demand-proj">{e(proj)}</div>')
    stage_txt = e(r["stage"])
    if r.get("prob") is not None:
        stage_txt += f' &middot; {r["prob"]}% &middot; {e(r["cat"])}'
    chips = [f'<span class="chip chip-stage">{stage_txt}</span>']
    if ats:
        if ats["start"]:
            chips.append(f'<span class="chip">start {e(ats["start"])}</span>')
        if ats.get("days_open") is not None:
            chips.append(f'<span class="chip chip-quiet">open {ats["days_open"]}d</span>')
        chips.append(f'<span class="chip chip-quiet">{e(ats["emp"])} &middot; {e(ats["recruiter"])}</span>')
    elif r.get("hrs"):
        # scheduled demand with nothing open in the ATS - the gap worth naming
        chips.append('<span class="chip chip-norec">no requisition open</span>')
    if r.get("vacated"):
        # This line is not in Salesforce: the hours were booked to a consultant and
        # have been taken off them here. Say so on the page rather than letting it
        # read as ordinary pipeline demand.
        chips.append(f'<span class="chip chip-vacated" title="{e(r.get("note", ""))}">'
                     f'unassigned here, not yet in Salesforce</span>')
    bits.append('<div class="chip-row">' + "".join(chips) + "</div>")
    return "".join(bits)


# Mark, Oct 5 2026: "Skills needed" in the same box as the recruiting update. Named
# technologies are read from the role title and the project name; the discipline (and the
# skills it implies) is read from the role title only, so a project called "ML Liability
# Model" does not turn a DV&A seat into an AI one.
TECH_TERMS = [
    (r"snowflake", "Snowflake"), (r"\bdbt\b", "dbt"), (r"databricks", "Databricks"),
    (r"power\s?bi|powerbi", "Power BI"), (r"tableau", "Tableau"), (r"qlik", "Qlik"),
    (r"sigma", "Sigma"), (r"alteryx", "Alteryx"), (r"\bsql\b", "SQL"), (r"python", "Python"),
    (r"\bazure\b", "Azure"), (r"\baws\b", "AWS"), (r"\bgcp\b|google cloud", "GCP"),
    (r"fabric", "Microsoft Fabric"), (r"collibra", "Collibra"), (r"\bsap\b", "SAP"),
    (r"semantic layer", "Semantic layer design"), (r"\bmdm\b", "MDM"),
    (r"full stack", "Full-stack development"), (r"genai|\bllm", "GenAI / LLM applications"),
]
DISCIPLINE_SKILLS = [
    (r"practice director", ["Practice leadership", "Business development", "Hiring and mentoring"]),
    (r"delivery manager|delivery lead|engagement manager|\bpm\b|project manager|program manager",
     ["Project management", "Agile delivery", "Client and scope management"]),
    (r"solutions? architect|architecture", ["Solution architecture", "Data platform design", "Cloud architecture"]),
    (r"ai engineer|\bai\b|ai/ml|machine learning", ["Python", "GenAI / LLM applications", "AI/ML engineering"]),
    (r"data engineer|data eng\b|\bde\b|\bsr\.? de\b|ingestion|\betl\b|pipeline", ["Data engineering", "SQL", "Python (ETL)"]),
    (r"dv&a|data viz|visuali[sz]ation|dashboard|developer", ["Data visualization", "Dashboard development"]),
    (r"analyst|analytics|reporting", ["SQL", "Data analysis", "Reporting"]),
    (r"data governance|governance|steward", ["Data governance", "Data quality", "Data cataloging"]),
    (r"end user support|platform admin|support", ["Platform administration", "End-user support and training"]),
    (r"marketing", ["Marketing strategy", "Demand generation", "Content and campaigns"]),
    (r"controller|finance|accounting", ["Accounting", "Financial reporting"]),
]


def skills_needed(r):
    ats_title = (r.get("ats") or {}).get("title") or ""
    title = f" {r['role']} {ats_title} ".lower()          # the ATS requisition title helps when the SF role is a placeholder
    proj = f" {r.get('project', '')} ".lower()
    if "no scheduled demand in salesforce" in proj:
        proj = " "
    out = []
    for pat, label in TECH_TERMS:
        if re.search(pat, title) or re.search(pat, proj):
            out.append(label)
    for pat, skills in DISCIPLINE_SKILLS:
        if re.search(pat, title):
            for sk in skills:
                if sk not in out:
                    out.append(sk)
            break
    return ", ".join(out[:7]) if out else "not specified in the role or requisition title"


def role_sub_row(r, ncols):
    """Recruiting update and skills needed, spanning every column, in one box (the
    date prefix from the ATS status-note line is stripped). Every role gets this row;
    a role with no requisition says so (Mark, Oct 5 2026)."""
    ats = r.get("ats")
    if ats:
        txt = re.sub(r"^\s*\d{1,2}/\d{1,2}[.:]?\s*", "", ats["update"])
        upd = f'<b>Recruiting Update:</b> {e(txt)}'
    else:
        upd = '<b>Recruiting Update:</b> <i>no requisition open in the ATS for this role.</i>'
    return (f'        <tr class="demand-sub"><td colspan="{ncols}">'
            f'<div class="demand-update">{upd}'
            f'<div class="demand-skills"><b>Skills needed:</b> {e(skills_needed(r))}</div></div></td></tr>')


def suggestions():
    """Open-role suggestions from current staff, keyed (client, project, role).

    Rendered as a sub-row under each open role (added Sep 14 2026). Degrades to {} with
    a stdout note if the module or its inputs are missing, exactly like the other
    optional sections, so a bad skills file can never fail the weekly build."""
    global _SUGGESTIONS
    if _SUGGESTIONS is None:
        try:
            import build_suggestions
            _SUGGESTIONS = build_suggestions.suggest_all()
        except Exception as ex:
            print(f"  note: open-role suggestions skipped ({ex})")
            _SUGGESTIONS = {}
    return _SUGGESTIONS


_SUGGESTIONS = None


def role_suggest_row(r, ncols):
    """'Suggested from current staff': up to three ranked consultants with the
    evidence behind each. Availability is scored over exactly the weeks the role
    needs, so a name here is someone who actually has the hours free."""
    if r.get("vacated"):
        # Work taken off a consultant here, pending a deal decision - not a role to
        # staff. The matcher would otherwise recommend the very person just removed
        # (it scores them as newly free), and it has no sensible read on a
        # non-delivery title like Controller. Leave these lines without suggestions.
        return None
    sug = suggestions().get((r["client"], r["project"], r["role"]))
    if not sug:
        return None
    cards = []
    for i, s in enumerate(sug["top"], 1):
        why = "".join(f'<span class="fit-why">{e(w)}</span>' for w in s["why"])
        cover = s.get("covers", 0)
        ccls = "fit-cover-full" if cover >= 0.99 else ("fit-cover-part" if cover >= 0.5 else "fit-cover-thin")
        cards.append(
            f'<li class="fit-card"><span class="fit-rank">{i}</span>'
            f'<span class="fit-name">{e(s["name"])}</span>'
            f'<span class="fit-score {ccls}" title="Match score out of 100: availability 40, '
            f'client history 20, skills 25, practice 10, job level 5">{s["score"]:.0f}</span>'
            f'<span class="fit-whys">{why}</span></li>')
    if not cards:
        note = ("No one on the current roster clears the bar for this role &mdash; "
                "it needs to be recruited or the work rescheduled.")
        body = f'<div class="fit-none">{note}</div>'
    else:
        thin = ('<div class="fit-none">Thin bench: only '
                f'{sug["pool"]} on the roster clear the bar for this role.</div>'
                if sug["thin"] else "")
        body = f'<ul class="fit-list">{"".join(cards)}</ul>{thin}'
    return (f'        <tr class="demand-sub fits-row"><td colspan="{ncols}">'
            f'<div class="demand-fits"><b>Suggested from current staff:</b>{body}</div>'
            f"</td></tr>")


def role_key(r):
    """Stable per-role key for the shared comment store (survives weekly rebuilds)."""
    raw = f'{r["client"]}-{r["project"]}-{r["role"]}'.lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", raw)).strip("-")[:120]


def role_comment_row(r, ncols):
    return (f'        <tr class="demand-sub comment-row"><td colspan="{ncols}">'
            f'<textarea class="role-comment" data-rk="{e(role_key(r))}" rows="1" '
            f'placeholder="Add a comment for this role &mdash; shared with everyone who opens the live page" '
            f'aria-label="Comments for {e(r["role"])}"></textarea></td></tr>')


def demand_grid():
    head = "".join(f'<th class="wk">{WL[w]}</th>' for w in WEEKS)
    ncols = len(WEEKS) + 1
    out = ['      <div class="geo-bar">'
           + "".join(f'<button type="button" class="outlook-btn geo-btn{" outlook-btn-active" if g == "all" else ""}" '
                     f'data-geo="{g}">{lbl}</button>' for g, lbl in GEO_LABELS)
           + '<span class="s3-tabs-note">filter by geography &middot; totals update with the filter</span></div>',
           '      <div class="outlook-scroll"><table class="outlook-table demand-grid" id="roles-table">',
           f'        <thead><tr><th>Open role</th>{head}</tr></thead>',
           "        <tbody>"]

    def emit(r, wk_cells):
        sub = role_sub_row(r, ncols)
        out.append(f'        <tr class="demand-main has-sub" data-geo="{r["geo"]}">'
                   f'<td class="col-demand-name">{role_cell(r)}</td>{wk_cells}</tr>')
        if sub:
            out.append(sub.replace('<tr class="demand-sub">',
                                   f'<tr class="demand-sub has-sub" data-geo="{r["geo"]}">'))
        fits = role_suggest_row(r, ncols)
        if fits:
            out.append(fits.replace('<tr class="demand-sub fits-row">',
                                    f'<tr class="demand-sub fits-row has-sub" data-geo="{r["geo"]}">'))
        out.append(role_comment_row(r, ncols).replace(
            '<tr class="demand-sub comment-row">',
            f'<tr class="demand-sub comment-row" data-geo="{r["geo"]}">'))

    for r in O.OPEN_DEMAND:
        wk_cells = []
        for w in WEEKS:
            if w in r["weeks"]:
                h = demand_hours(r, w)
                wk_cells.append(f'<td class="wk"><div class="wk-cell wk-demand" data-h="{h:g}">{h:g}</div></td>')
            else:
                wk_cells.append('<td class="wk"><div class="wk-cell wk-demand-empty" data-h="0">&mdash;</div></td>')
        emit(r, "".join(wk_cells))
    for r in O.INTERNAL_ROLES:
        wk_cells = "".join('<td class="wk"><div class="wk-cell wk-demand-empty" data-h="0">&mdash;</div></td>' for _ in WEEKS)
        emit(r, wk_cells)

    tot_cells = "".join(f'<td class="wk"><div class="wk-cell wk-demand-total">{open_hours(w):,.0f}</div></td>'
                        for w in WEEKS)
    out.append(f'        <tr class="demand-total-row"><td>Total unfilled demand (hrs/wk)</td>{tot_cells}</tr>')
    out.append("        </tbody>")
    out.append("      </table></div>")
    out.append("""<script>
(function () {
  var btns = document.querySelectorAll(".geo-btn");
  function apply(g) {
    btns.forEach(function (b) { b.classList.toggle("outlook-btn-active", b.dataset.geo === g); });
    document.querySelectorAll("#roles-table tr[data-geo]").forEach(function (r) {
      r.hidden = (g !== "all" && r.dataset.geo !== g);
    });
    var tot = [];
    document.querySelectorAll("#roles-table tr.demand-main").forEach(function (r) {
      if (r.hidden) return;
      var cells = r.querySelectorAll("td.wk [data-h]");
      cells.forEach(function (c, i) { tot[i] = (tot[i] || 0) + (parseFloat(c.dataset.h) || 0); });
    });
    document.querySelectorAll("#roles-table .wk-demand-total").forEach(function (c, i) {
      c.textContent = (tot[i] || 0).toLocaleString();
    });
  }
  btns.forEach(function (b) { b.addEventListener("click", function () { apply(b.dataset.geo); }); });
})();
(function () {
  var areas = document.querySelectorAll(".role-comment");
  if (!areas.length) return;
  function grow(a) { a.style.height = "auto"; a.style.height = Math.max(a.scrollHeight, 30) + "px"; }
  areas.forEach(grow);
  function offline() {
    areas.forEach(function (a) {
      a.disabled = true;
      a.placeholder = "Comments work on the live dashboard page on claude.ai - this copy can't save them.";
    });
  }
  if (!(window.claude && typeof window.claude.use === "function")) { offline(); return; }
  window.claude.use("db").then(function (db) {
    if (!db) { offline(); return; }
    areas.forEach(function (a) {
      var ref = db.doc("role_comments/" + a.dataset.rk);
      var timer = null;
      ref.onSnapshot(function (snap) {
        var v = snap.exists ? String((snap.data() || {}).text || "") : "";
        if (document.activeElement !== a && a.value !== v) { a.value = v; grow(a); }
      }, function () {});
      a.addEventListener("input", function () {
        grow(a);
        clearTimeout(timer);
        timer = setTimeout(function () {
          ref.set({ text: a.value, ts: Date.now() }).catch(function () {});
        }, 600);
      });
    });
  }).catch(offline);
})();
</script>""")
    return "\n".join(out)


# ---------------------------------------------------------------- summary table

def summary_table(rows):
    head = "".join(f'<th class="wk">{WL[w]}</th>' for w, *_ in rows)

    def num_row(label, idx, cls=""):
        cells = "".join(f'<td class="wk num">{r[idx]:,.0f}</td>' for r in rows)
        return f'        <tr class="{cls}"><td>{label}</td>{cells}</tr>'
    surplus_cells = []
    for r in rows:
        v = r[6]
        cls = "cap-pos" if v >= 0 else "cap-neg"
        sign = "+" if v >= 0 else "&minus;"
        surplus_cells.append(f'<td class="wk num {cls}">{sign}{abs(v):,.0f}<span class="cap-fte"> '
                             f'({sign}{abs(v) / 40.0:.1f} FTE)</span></td>')
    return "\n".join([
        '      <table class="outlook-table capacity-table">',
        f'        <thead><tr><th>Hours per week</th>{head}</tr></thead>',
        "        <tbody>",
        num_row("Capacity (40 hrs &times; headcount, net of PTO)", 1),
        num_row("Capacity at target utilization", 2, cls="cap-target-row"),
        num_row("Booked on projects", 3),
        num_row("Open roles (unfilled demand)", 4),
        num_row("Total need", 5, cls="cap-need-row"),
        f'        <tr class="cap-gap-row"><td>Surplus / (gap) vs. full capacity</td>{"".join(surplus_cells)}</tr>',
        "        </tbody>",
        "      </table>",
    ])


# ---------------------------------------------------------------- section

def section4(after_outlook=""):
    """after_outlook: extra section HTML to drop in directly below the 8 Week
    Outlook staff grid, before Capacity vs. Need. build_dashboard passes the
    Projects, Roles & Open Demand section here (added Sep 10 2026)."""
    rows = summary_rows()
    n_staff = len(O.OUTLOOK_STAFF)
    n_roles = len(O.OPEN_DEMAND) + len(O.INTERNAL_ROLES)
    controls = """      <div class="outlook-controls">
        <button type="button" class="outlook-btn" id="outlook-expand-all" aria-pressed="false">Expand all projects</button>
        <span class="s3-tabs-note">every project a consultant is booked to that week &middot; or click <b>+n more</b> in a single cell &middot; hover a line for the full project name</span>
      </div>"""
    legend = """      <div class="outlook-legend">
        <span class="legend-item"><span class="swatch" style="background:var(--accent)"></span>Above target</span>
        <span class="legend-item"><span class="swatch" style="background:var(--status-good)"></span>At target</span>
        <span class="legend-item"><span class="swatch" style="background:var(--status-warning)"></span>Below by &le;20 pts</span>
        <span class="legend-item"><span class="swatch" style="background:var(--status-serious)"></span>Below by 20&ndash;50 pts</span>
        <span class="legend-item"><span class="swatch" style="background:var(--status-critical)"></span>Below by &ge;50 pts</span>
        <span class="legend-item"><span class="swatch swatch-pto"></span>Full-week PTO</span>
        <span class="legend-item">Weeks with partial PTO are judged net of PTO and tagged <span class="pto-chip">PTO&nbsp;<i>n</i>d</span></span>
      </div>"""
    outlook = f"""<section class="section4">
  <h2 class="sec-head">8 Week Outlook <span class="section4-range">{n_staff} consultants &times; 8 weeks &middot; weeks of {WL[WEEKS[0]]} &ndash; {WL[WEEKS[-1]]}</span></h2>
{controls}
{legend}
{staff_grid()}
</section>"""

    capacity = f"""<section class="section4 capacity-section">
  <h2 class="sec-head">Capacity vs. Need <span class="section4-range">hours per week</span></h2>
  <textarea class="role-comment section-note" data-rk="section-capacity-vs-need" rows="1"
    placeholder="Add commentary on capacity vs. need &mdash; shared with everyone who opens the live page"
    aria-label="Commentary on capacity vs. need"></textarea>
{capacity_chart(rows)}
  <div class="chart-legend">
    <span class="legend-item"><span class="swatch" style="background:var(--accent)"></span>Booked on projects</span>
    <span class="legend-item"><span class="swatch" style="background:var(--status-warning)"></span>Open roles (unfilled)</span>
    <span class="legend-item"><span class="swatch swatch-capline"></span>Capacity (net of PTO)</span>
    <span class="legend-item"><span class="swatch swatch-capline-target"></span>Capacity at target utilization</span>
  </div>
{summary_table(rows)}
</section>"""

    roles = f"""<section class="section4 roles-section">
  <h2 class="sec-head">Open Roles &amp; Recruiting <span class="section4-range">unfilled demand in hrs/wk &middot; {n_roles} roles</span></h2>
  <div class="s3-tabs-note fits-legend">Suggestions are scored out of 100 &mdash; free hours in the weeks the role needs (40), client history (20), skills matrix (25), practice (10), job level (5). The badge colour is a separate reading: <span class="fit-score fit-cover-full">&nbsp;</span> covers the role&#39;s full hours, <span class="fit-score fit-cover-part">&nbsp;</span> covers half or more, <span class="fit-score fit-cover-thin">&nbsp;</span> covers less than half and would need the work split.</div>
{demand_grid()}
</section>"""

    # Open Roles & Recruiting sits directly under the 8 Week Outlook (Mark, Sep 14 2026):
    # the staffing question and the gap it has to cover read together.
    parts = [outlook, roles]
    if getattr(O, "RECRUITING_WEEK", None):
        parts.append(recruiting_activity())      # reads with the roles, not after capacity
    if after_outlook:
        parts.append(after_outlook)
    parts.append(capacity)
    return "\n\n\n".join(parts)


def recruiting_activity():
    """Week-over-week recruiting summary from O.RECRUITING_WEEK (this week's ATS export
    vs. last week's). The export tracks candidates currently interviewing, not
    interviews conducted - the section says so."""
    R = O.RECRUITING_WEEK
    filled = R["filled"]
    tiles = [
        (f"{R['open_req_count']}", "open requisitions"),
        (f"{R['interviewing_total']}", "candidates interviewing"),
        (f"{len(filled)}", "role filled" if len(filled) == 1 else "roles filled"),
        (f"{R.get('oldest_days', 0)}", "days open, oldest requisition"),
    ]
    # Demand lines with no requisition behind them are the gap this section exists to
    # show: work Salesforce has scheduled that recruiting is not yet hiring against.
    no_req = R.get("no_req") or []
    no_req_block = ""
    if no_req:
        items = "".join(f"<li>{e(x)}</li>" for x in no_req)
        no_req_block = f"""
    <div class="rec-col">
      <h3 class="section4-subhead">Scheduled demand with no requisition</h3>
      <ul class="rec-list">{items}</ul>
      <div class="rec-note">Open demand in Salesforce with nothing open in the ATS &mdash; either
      it is meant to be filled internally, or the requisition has not been raised yet.</div>
    </div>"""
    tiles_html = "".join(f'<div class="rec-stat"><div class="rec-stat-num">{n}</div>'
                         f'<div class="rec-stat-label">{lbl}</div></div>' for n, lbl in tiles)
    filled_rows = "".join(
        f'<li><b>{e(f["hire"])}</b> &mdash; {e(CLIENT_SHORT.get(f["client"], f["client"]))}: {e(f["role"])}'
        f'<div class="rec-item-sub">{e(f["project"])} &middot; {e(f["status"])}</div></li>'
        for f in filled)
    closed_rows = "".join(f"<li>{e(x)}</li>" for x in R["closed_reqs"])
    new_rows = "".join(f"<li>{e(x)}</li>" for x in R["new_reqs"])
    closed_block = (f"""
    <div class="rec-col">
      <h3 class="section4-subhead">Requisitions closed</h3>
      <ul class="rec-list">{closed_rows}</ul>
      <div class="rec-note">{e(R["closed_note"])}</div>
    </div>""" if closed_rows else "")
    as_of = R.get("as_of")
    return f"""<section class="section4 recruiting-section">
  <h2 class="sec-head">Recruiting Activity <span class="section4-range">{
    "ATS export as of " + e(as_of) if as_of else "since last week&#39;s meeting"}</span></h2>
  <div class="rec-stats">
{tiles_html}
  </div>
  <div class="rec-cols">
    <div class="rec-col">
      <h3 class="section4-subhead">Filled</h3>
      <ul class="rec-list">{filled_rows}</ul>
    </div>
    <div class="rec-col">
      <h3 class="section4-subhead">Opened in the last two weeks</h3>
      <ul class="rec-list">{new_rows}</ul>
    </div>{no_req_block}{closed_block}
  </div>
  <div class="rec-note rec-note-bottom">The ATS export records candidates currently in interviews per requisition; the number of interviews conducted is not tracked in the data. {e(R["closed_note"]) if not closed_rows else ""} Compensation fields in the export are never carried into this page.</div>
</section>"""


if __name__ == "__main__":
    with open("section4.html", "w", encoding="utf-8") as fh:
        fh.write(section4())
    for wk, cap, capt, booked, open_h, need, surplus in summary_rows():
        print(f"{WL[wk]:>7}: cap {cap:7.1f}  cap@target {capt:7.1f}  booked {booked:7.1f}  "
              f"open {open_h:5.1f}  need {need:7.1f}  surplus {surplus:+8.1f}")
    print(f"staff={len(O.OUTLOOK_STAFF)} roles={len(O.OPEN_DEMAND) + len(O.INTERNAL_ROLES)}")
