#!/usr/bin/env python3
"""Cleartelligence Staffing Dashboard generator.

Writes two files:
  dashboard.html           - standalone document (doctype/html/head/body) for download
  dashboard_artifact.html  - stripped fragment (title/style/body content) for the Artifact tool

Display conventions (reverse-engineered from the published dashboard and kept stable):
  * Monthly utilization per consultant = SUM(hrs_billable) / SUM(hrs_util_denom) over the month.
  * Trend bars: viewBox 260x96, baseline y=72, 50px = one full "scale" unit where
    scale = max(1.0, max monthly value). Target dash line drawn at the raw target_utilization.
  * Bar / pill colour by percentage-point gap to target: <=0 good, <=20 warning,
    <50 serious, else critical.
  * Allocation % for the current week = allocated_billable_hours / 40, rounded.
  * Section 3 FTE variance = |delta hours| / (40 hrs/wk x number of weeks in the rolling window).
  * Standing exclusions (apply to the Section 1 cohort and the outlook roster):
    Ankitha Thirakala; Riddhima Shukla (dropped at Mark's request, Aug 28 2026).
    These names must never appear in the published HTML - generator docstrings and
    the run logs only.
  * The standalone Open Roles & Recruiting section was RETIRED Aug 28 2026 - its
    content is merged into the outlook's open-roles table (see outlook_data.OPEN_DEMAND
    'ats' fields and INTERNAL_ROLES).
  * Section 4 (8-Week Outlook, added Aug 28 2026) is rendered by build_outlook_section.py
    from outlook_data.py; its CSS lives in dashboard_style.css. See
    claude/outlook_data_2026-09-09.py for the data shapes and the run log for the queries.
"""
import csv
import html
import re
from collections import defaultdict

import staffing_data as D
import params as P
import build_section3_viz as S3V  # Section 3 charts (added Aug 28 2026)
import agenda_section as AGENDA  # shared Meeting Agenda (added Aug 28 2026; needs capabilities={'db': {}} at publish)

TITLE = "Cleartelligence Staffing Dashboard"


def adjustment_banner():
    """Names any manual unassignment applied in make_data, so nobody reads an adjusted
    grid as raw Salesforce. Built from the data, so it disappears by itself the week
    the adjustment is no longer being made. It also states what is NOT adjusted: the
    monthly utilization figures in Summary come from a separate monthly pull and still
    count the hours."""
    import outlook_data as _O
    vac = [r for r in _O.OPEN_DEMAND if r.get("vacated")]
    if not vac:
        return ""
    names = sorted({r["vacated"] for r in vac})
    who = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
    proj = vac[0]["project"]
    note = vac[0].get("note", "")
    return (f'\n  <div class="dash-adjust"><b>Manual adjustment, this build only.</b> '
            f'{html.escape(who)} are shown as no longer assigned to '
            f'{html.escape(proj)} ({html.escape(note)}). Their hours move from booked to '
            f'unfilled: the 8 Week Outlook, the capacity table and Open Roles &amp; '
            f'Recruiting are all computed that way, and total need is unchanged. The '
            f'monthly utilization and under-target figures in Summary come from a '
            f'separate monthly source and still count these hours.</div>')
ARTIFACT_URL = "https://claude.ai/code/artifact/7d219223-52bb-4a5c-bb5d-24f9e373b3d8"

PRACTICE_ORDER = ["AI Engineering", "Data Management", "Data Viz. & Analytics",
                  "Delivery", "Portfolio Mgmt", "Solution Architecture"]

MONTH_NAME = {"08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}


def e(s):
    return html.escape(str(s), quote=True)


def pct_str(v):
    """Round-half-up to a whole percent."""
    return int(v * 100 + 0.5)


def ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def short_date(mdy):
    """'09/21/2026' -> 'Sep 21' (matches the published convention)."""
    try:
        mm, dd, _yy = mdy.split("/")
        return f"{MONTH_NAME.get(mm, mm)} {int(dd)}"
    except Exception:
        return mdy


def status_class(value, target):
    """Percentage-point gap to target -> status token."""
    gap = (target - value) * 100.0
    if gap <= 0:
        return "good"
    if gap <= 20:
        return "warning"
    if gap < 50:
        return "serious"
    return "critical"


# ---------------------------------------------------------------- charts

ORG_TARGET = 0.90   # the firm-wide utilization target the Outlook's cell colours are judged against


def org_status(v, target=ORG_TARGET):
    """Same bands as the 8 Week Outlook cells (build_outlook_section.cell_status): above the
    target by more than 1.5 pts = accent blue; within a point = green; below by up to 20 pts =
    yellow; 20-50 = orange; 50+ = red. The chart reads with the rest of the page that way."""
    if v > target + 0.015:
        return "above"
    if v >= target - 0.01:
        return "at"
    gap = (target - v) * 100.0
    return "warning" if gap <= 20 else ("serious" if gap < 50 else "critical")


STATUS_FILL = {"above": "var(--accent)", "at": "var(--status-good)", "warning": "var(--status-warning)",
               "serious": "var(--status-serious)", "critical": "var(--status-critical)"}


def thin_months():
    """Forecast months whose bookings are still being entered: the figure is less than 60% of
    the month before it. Jan '27 read 42% on Oct 20 2026 for exactly that reason. Returns a set
    of indexes into ORG_MONTHLY."""
    out = set()
    for i in range(D.ORG_THIS_IDX + 1, len(D.ORG_MONTHLY)):
        prev = D.ORG_MONTHLY[i - 1][1]
        if prev and D.ORG_MONTHLY[i][1] < 0.6 * prev:
            out.add(i)
    return out


def projection():
    """Projected close for the current month, from how earlier months moved between this point
    in the month and their close (Mark, Oct 20 2026: "what typically happens from mid month to the
    end of the month?"). ORG_HISTORY holds [run date, month id, value] for every run; for each
    closed month with history we interpolate what it read on the same day-of-month as today and
    take the median gap to its final value. Returns None until there is at least one such month."""
    import datetime as _dt
    hist = getattr(P, "ORG_HISTORY", None)
    build = getattr(P, "BUILD_DATE", None)
    if not hist or not build:
        return None
    today = _dt.date.fromisoformat(build)
    cur_mid = f"{today.year}{today.month:02d}"
    day = today.day
    finals = {}
    # final values: ORG_MONTHLY's past months (labels like "Sep '26" -> month id)
    for lab, v in D.ORG_MONTHLY[:D.ORG_THIS_IDX]:
        d = _dt.datetime.strptime(lab, "%b '%y")
        finals[f"{d.year}{d.month:02d}"] = v
    by_month = defaultdict(list)
    for run, mid, v in hist:
        by_month[mid].append((_dt.date.fromisoformat(run), float(v)))
    drifts, mid_drifts = [], []

    def at_day(obs, mid, d):
        """What the month read on day d (linear between the nearest runs; the first run if d is
        earlier than any run but within 7 days of it)."""
        y, m = int(mid[:4]), int(mid[4:])
        try:
            when = _dt.date(y, m, min(d, 28))
        except ValueError:
            return None
        obs = sorted(obs)
        before = [o for o in obs if o[0] <= when]
        after = [o for o in obs if o[0] > when]
        if before and after:
            (d0, v0), (d1, v1) = before[-1], after[0]
            span = (d1 - d0).days or 1
            return v0 + (v1 - v0) * (when - d0).days / span
        if before:
            return before[-1][1]
        if after and (after[0][0] - when).days <= 7:
            return after[0][1]
        return None

    basis = []
    for mid, obs in by_month.items():
        if mid >= cur_mid or mid not in finals:
            continue
        # only runs made inside that month count as "in-month" readings
        inm = [(d, v) for d, v in obs if f"{d.year}{d.month:02d}" == mid]
        if not inm:
            continue
        v_day = at_day(inm, mid, day)
        if v_day is None:
            continue
        drifts.append(finals[mid] - v_day)
        basis.append((mid, v_day, finals[mid]))
        v_mid = at_day(inm, mid, 15)
        if v_mid is not None:
            mid_drifts.append(finals[mid] - v_mid)
    if not drifts:
        return None
    drifts.sort()
    med = drifts[len(drifts) // 2] if len(drifts) % 2 else (drifts[len(drifts) // 2 - 1] + drifts[len(drifts) // 2]) / 2
    cur = D.ORG_MONTHLY[D.ORG_THIS_IDX][1]
    names = {m: _dt.date(int(m[:4]), int(m[4:]), 1).strftime("%b") for m in finals}
    parts = [f"{names[m]} read {v * 100:.1f}% on day {day} and closed at {fv * 100:.1f}% ({(fv - v) * 100:+.1f} pts)"
             for m, v, fv in sorted(basis)]
    mid_txt = ""
    if mid_drifts:
        mid_drifts.sort()
        mm = mid_drifts[len(mid_drifts) // 2]
        mid_txt = (f" From mid-month (day 15) to close the typical move is {mm * 100:+.1f} pts, so the figure "
                   f"{'drifts down' if mm < 0 else 'firms up'} as timesheets and PTO are entered.")
    note = (f"Projected close for this month: {pct_str(cur + med)}%, from the median move between day {day} "
            f"and month end in {len(drifts)} earlier month{'s' if len(drifts) != 1 else ''} with history "
            f"({'; '.join(parts)}).{mid_txt} The basis grows every week the refresh runs.")
    return {"value": cur + med, "drift": med, "mid_drift": (mid_drifts[len(mid_drifts) // 2] if mid_drifts else None),
            "n": len(drifts), "note": note, "day": day, "parts": parts}


def projection_why():
    """A visible explanation of the projected month close (Mark, Oct 21 2026: "add an explanation of
    why utilization is projected to drop"). What today's figure is made of (closed weeks are billed
    hours, the weeks ahead are scheduled hours), how the two halves of this month compare
    (ORG_WEEKS: closed vs scheduled utilization, and the PTO each carries), and the arithmetic
    (how the months with history moved from this day-of-month to their close). "" when there is
    no projection."""
    import datetime as _dt
    proj = projection()
    if not proj:
        return ""
    this_label, cur = D.ORG_MONTHLY[D.ORG_THIS_IDX]
    month = this_label[:3]
    drift = proj["drift"] * 100.0
    direction = "lower than" if drift < -0.05 else ("higher than" if drift > 0.05 else "about the same as")

    # this month so far: closed weeks (Friday already past) against the weeks still ahead
    evidence = ""
    build = getattr(P, "BUILD_DATE", None)
    wk = [w for w in getattr(D, "ORG_WEEKS", []) if w[2] > 0]
    if build and wk:
        today = _dt.date.fromisoformat(build)
        closed = [w for w in wk if _dt.date.fromisoformat(w[0]) + _dt.timedelta(days=4) < today]
        ahead = [w for w in wk if w not in closed]
        def agg(ws):
            b, d, p = (sum(w[i] for w in ws) for i in (1, 2, 3))
            return (b / d if d else 0.0), (p / d if d else 0.0)
        if closed and ahead:
            cu, cp = agg(closed); au, ap = agg(ahead)
            lab = lambda ws: " and ".join(_dt.date.fromisoformat(w[0]).strftime("%b %-d") for w in ws) if len(ws) <= 2 \
                else f"{_dt.date.fromisoformat(ws[0][0]).strftime('%b %-d')} to {_dt.date.fromisoformat(ws[-1][0]).strftime('%b %-d')}"
            evidence = (f" This month so far: the closed weeks (of {lab(closed)}) billed {pct_str(cu)}% of available hours, "
                        f"while the weeks still ahead (of {lab(ahead)}) are scheduled at {pct_str(au)}%; the closed weeks carry "
                        f"{cp * 100:.0f}% of their hours as time off against {ap * 100:.0f}% in the weeks ahead - time off is "
                        f"entered as it is taken, so the scheduled weeks have not absorbed theirs yet.")
    t = getattr(D, "S3_TOTAL", None) or {}
    s3 = ""
    if t.get("alloc"):
        diff = t["actual"] - t["alloc"]
        pct = diff / t["alloc"] * 100.0
        n_under = sum(1 for c in getattr(D, "S3_CONSULTANTS", []) if sum(p[2] for p in c[2]) < sum(p[1] for p in c[2]))
        s3 = (f" (Project allocations are not the gap: over the last 4 complete weeks the team billed {t['actual']:,.0f} of "
              f"{t['alloc']:,.0f} allocated hours, {pct:+.0f}%, with {n_under} of {t.get('people', 0)} employees under their "
              f"allocation - see Allocation vs Actual.)" if diff >= 0 else
              f" Over the last 4 complete weeks the team also billed {t['actual']:,.0f} of {t['alloc']:,.0f} allocated hours "
              f"({pct:+.0f}%), {n_under} of {t.get('people', 0)} employees under their allocation - see Allocation vs Actual.")
    history = "; ".join(proj.get("parts", []))
    mid = proj.get("mid_drift")
    mid_txt = f" From mid-month the typical move is {mid * 100:+.1f} pts." if mid is not None else ""
    why = (f"<b>Why {month} is projected to close {direction} today's {cur * 100:.1f}%.</b> The {month} figure mixes two "
           f"things: the weeks already closed count hours actually billed, while the rest of the month still counts "
           f"scheduled hours. Scheduled hours run high - PTO and sick days are entered after the fact, projects wind "
           f"down or pause, and late timesheets sit at zero until filed - so the figure drifts as each week closes."
           f"{evidence}{s3} The projection applies how earlier months moved from day {proj['day']} to their close"
           f"{': ' + history if history else ''}; the median move is {drift:+.1f} pts, so {month} is projected to close "
           f"near {proj['value'] * 100:.1f}%.{mid_txt} The basis grows every week the refresh runs.")
    return f'  <p class="proj-why">{why}</p>\n'


def org_chart():
    lo, hi = 0.55, 1.05
    n = len(D.ORG_MONTHLY)
    step = (1044.0 - 40.0) / max(1, n - 1)
    xs = [round(40.0 + i * step, 1) for i in range(n)]

    def y_of(v):
        frac = (v - lo) / (hi - lo)
        frac = max(0.0, min(1.0, frac))
        return round(120.0 - frac * 98.0, 1)

    pts = [(xs[i], y_of(v)) for i, (_, v) in enumerate(D.ORG_MONTHLY)]
    ti = D.ORG_THIS_IDX
    thin = thin_months()
    proj = projection()
    out = [
        '  <svg class="monthly-util-chart" viewBox="0 0 1080 148" role="img" '
        f'aria-label="Monthly utilization trend, {n} months">',
    ]
    for gv in (0.6, 0.7, 0.8, 0.9, 1.0):
        gy = y_of(gv)
        cls = "util-grid util-grid-target" if abs(gv - ORG_TARGET) < 1e-9 else "util-grid"
        out.append(f'    <line x1="36" y1="{gy}" x2="1044" y2="{gy}" class="{cls}"/>'
                   f'<text x="30" y="{gy + 3.5}" class="util-axis-label" text-anchor="end">{int(gv * 100)}%</text>')
    out.append('    <line x1="36" y1="124" x2="1044" y2="124" class="util-axis"/>')
    out.append("    " + "".join(f'<line x1="{x}" y1="124" x2="{x}" y2="129" class="util-axis"/>' for x in xs))
    out.append(f'    <line x1="{xs[ti]}" y1="16.0" x2="{xs[ti]}" y2="120.0" class="month-this-guide"/>'
               f'<text x="{xs[ti]}" y="12.0" class="month-this-tag" text-anchor="middle">This month</text>')
    # one segment per month pair, coloured by the status of the month it leads into (same bands as
    # the Outlook cells); solid up to this month, dashed into the forecast
    segs = []
    for i in range(1, n):
        (x0, y0), (x1, y1) = pts[i - 1], pts[i]
        st = org_status(D.ORG_MONTHLY[i][1])
        dash = ' stroke-dasharray="5,4"' if i > ti else ""
        faint = ' opacity="0.35"' if i in thin else ""
        segs.append(f'<line x1="{x0}" y1="{y0}" x2="{x1}" y2="{y1}" class="util-seg" '
                    f'stroke="{STATUS_FILL[st]}"{dash}{faint}/>')
    out.append("    " + "".join(segs))
    dots = []
    for i, (x, y) in enumerate(pts):
        st = org_status(D.ORG_MONTHLY[i][1])
        fill = STATUS_FILL[st]
        title = f'<title>{e(D.ORG_MONTHLY[i][0])}: {D.ORG_MONTHLY[i][1] * 100:.1f}% ({st.replace("warning", "below target by up to 20 pts").replace("serious", "below target by 20-50 pts").replace("critical", "below target by 50+ pts").replace("above", "above target").replace("at", "at target")})</title>'
        if i < ti:
            dots.append(f'<circle class="dot-past" cx="{x}" cy="{y}" r="4" fill="{fill}">{title}</circle>')
        elif i == ti:
            dots.append(f'<circle class="dot-current" cx="{x}" cy="{y}" r="6" fill="{fill}">{title}</circle>')
        else:
            faint = ' opacity="0.45"' if i in thin else ""
            dots.append(f'<circle class="dot-forecast" cx="{x}" cy="{y}" r="5" fill="var(--surface-1)" stroke="{fill}"{faint}>{title}</circle>')
    if proj:
        px, py = xs[ti], y_of(proj["value"])
        dots.append(f'<g class="util-proj"><title>{e(proj["note"])}</title>'
                    f'<line x1="{px}" y1="{pts[ti][1]}" x2="{px}" y2="{py}" class="util-proj-link"/>'
                    f'<path d="M{px - 6},{py} L{px},{py - 6} L{px + 6},{py} L{px},{py + 6} Z" class="util-proj-mark" '
                    f'fill="var(--surface-1)" stroke="{STATUS_FILL[org_status(proj["value"])]}"/></g>')
    out.append("    " + "".join(dots))
    labels = []
    for i, ((label, v), (x, y)) in enumerate(zip(D.ORG_MONTHLY, pts)):
        bold = "font-weight:700;" if i == ti else ""
        lab_y = round(y - 11, 1)
        if proj and i == ti and y_of(proj["value"]) < y:
            lab_y = round(y + 18, 1)          # projection sits above the point; keep the value label clear of it
        labels.append(
            f'<text x="{x}" y="{lab_y}" class="util-pt-label" style="{bold}" '
            f'text-anchor="middle">{pct_str(v)}%</text>'
            f'<text x="{x}" y="141.0" class="util-mo-label" style="{bold}" '
            f'text-anchor="middle">{e(label)}{" *" if i in thin else ""}</text>')
        if proj and i == ti:
            ly = round(y_of(proj["value"]) - 10, 1) if y_of(proj["value"]) < y else round(y_of(proj["value"]) + 16, 1)
            labels.append(f'<text x="{x}" y="{ly}" class="util-proj-label" text-anchor="middle">proj. {proj["value"] * 100:.1f}%</text>')
    out.append("    " + "".join(labels))
    out.append("  </svg>")
    return "\n".join(out)


def trend_bars(person):
    name = person["name"]
    target = person["target"]
    vals = [(D.MONTH_LABELS[m], person["pct"].get(m), bool(person["pto"].get(m)))
            for m in D.MONTHS]
    vals = [(lab, v, p) for lab, v, p in vals if v is not None]
    scale = max([1.0] + [v for _, v, _ in vals])
    ty = round(72.0 - 50.0 * (target / scale), 1)
    out = [f'          <svg class="trend-bars" viewBox="0 0 260 96" role="img" '
           f'aria-label="Monthly utilization trend for {e(name)}">',
           f'  <line x1="30.0" y1="{ty}" x2="230.0" y2="{ty}" class="target-dash-line"/>']
    parts = []
    for i, (lab, v, has_pto) in enumerate(vals):
        cx = 58.0 + 72.0 * i
        x = 36.0 + 72.0 * i
        h = max(1.0, 50.0 * v / scale)
        y = round(72.0 - h, 1)
        lab_y = round(y - 3.0, 1)
        fill = f"var(--status-{status_class(v, target)})"
        future = i > 0
        extra = (' stroke-dasharray="3,3" stroke="var(--muted-ink)" stroke-width="1" '
                 'fill-opacity="0.55"') if future else ""
        if has_pto:
            parts.append(f'<text x="{cx}" y="{round(lab_y - 11.0, 1)}" class="bar-pto-tag" '
                         f'text-anchor="middle">PTO</text>')
        parts.append(f'<text x="{cx}" y="{lab_y}" class="bar-val-label" text-anchor="middle">'
                     f'{pct_str(v)}%</text>')
        parts.append(f'<rect x="{x}" y="{y}" width="44" height="{round(h, 1)}" fill="{fill}" '
                     f'rx="4"{extra}/>')
        parts.append(f'<text x="{cx}" y="88.0" class="bar-mo-label" text-anchor="middle">{lab}</text>')
    out.append("  " + "".join(parts))
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- section 1

def pto_note(person):
    chunks = []
    for m in D.MONTHS:
        weeks = sorted(person["pto"].get(m) or [])
        if not weeks:
            continue
        names = ", ".join(f"{MONTH_NAME[w[:2]]} {ordinal(w[3:])}" for w in weeks)
        chunks.append(f"{D.MONTH_LABELS[m]} (week of {names})")
    if not chunks:
        return ""
    return f'          <div class="pto-note">PTO affected: {e("; ".join(chunks))}</div>'


def alloc_cell(person):
    allocs = D.ALLOCATIONS.get(person["name"])
    if allocs:
        if len(allocs) == 1:
            p, proj = allocs[0]
            return f'          <div class="alloc-single">{int(p)}%: {e(proj)}</div>'
        items = "".join(f"<li>{int(p)}%: {e(proj)}</li>" for p, proj in allocs)
        return f'          <ul class="alloc-list">{items}</ul>'
    cur = D.THIS_WEEK[5:7] + "-" + D.THIS_WEEK[8:10]
    if cur in (person["pto"].get(D.MONTHS[0]) or []):
        return '          <div class="alloc-empty">On PTO this week</div>'
    return '          <div class="alloc-empty">No active assignment</div>'


def cons_row(person):
    months = [(m, person["pct"][m]) for m in D.MONTHS if person["pct"].get(m) is not None]
    cur_m, cur_v = months[0]
    under = [v for _, v in months if v < person["target"]]
    low = min(v for _, v in months)
    badge = ""
    if abs(person["target"] - 0.9) > 1e-9:
        badge = f'<span class="target-badge">Target: {pct_str(person["target"])}%</span>'
    return f"""      <div class="cons-row">
        <div class="col-name">
          <div class="cons-name">{e(person["name"])}</div>
          <span class="status-pill status-{status_class(cur_v, person["target"])}">{pct_str(cur_v)}% in {D.MONTH_LABELS[cur_m]}</span>
          {badge}
          <div class="status-subline">{len(under)} of {len(months)} months under target &middot; low {pct_str(low)}%</div>
{pto_note(person)}
        </div>
        <div class="col-trend">
{trend_bars(person)}
        </div>
        <div class="col-alloc">
{alloc_cell(person)}
        </div>
        <div class="col-comment">
          <textarea class="comment-box" placeholder="Notes / questions" aria-label="Notes / questions for {e(person["name"])}"></textarea>
        </div>
      </div>"""


def section1():
    """RETIRED Aug 28 2026 (evening): Mark dropped this section - the outlook's
    staff schedule replaces it. Kept for reference; no longer called by build()."""
    by_practice = defaultdict(list)
    for p in D.COHORT:
        by_practice[p["practice"]].append(p)
    groups = []
    for practice in PRACTICE_ORDER:
        people = sorted(by_practice.get(practice, []), key=lambda p: p["name"])
        if not people:
            continue
        rows = "\n".join(cons_row(p) for p in people)
        groups.append(f"""    <div class="practice-group">
      <h3 class="practice-heading">{e(practice)}</h3>
      <div class="cons-table-head">
        <span>Name</span><span>Monthly trend</span><span>Allocations for this week</span><span>Notes / questions</span>
      </div>

{rows}
    </div>""")
    return f"""<section class="section1">
  <h2>Section 1 &mdash; Consultants under utilization target, next 2 months</h2>

{chr(10).join(groups)}
</section>"""


# ---------------------------------------------------------------- section 2 fits

TOKEN_RE = re.compile(r"[a-z0-9+#&]+")


def load_skills():
    """name -> {skill_name: (rating, years)} for cohort members only."""
    wanted = {}
    for p in D.COHORT:
        wanted[p["name"]] = p["name"]
        wanted[re.sub(r"\s+", " ", p["name"]).strip()] = p["name"]
    out = defaultdict(dict)
    with open(D.SKILLS_CSV, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            nm = (row.get("Name") or "").strip()
            key = wanted.get(nm) or wanted.get(re.sub(r"\s+", " ", nm))
            if not key:
                continue
            skill = (row.get("Technology/Skill") or "").strip()
            try:
                rating = float(row.get("Skill Rating") or 0)
            except ValueError:
                rating = 0.0
            try:
                years = float(row.get("Years Experience") or 0)
            except ValueError:
                years = 0.0
            if skill:
                prev = out[key].get(skill)
                if prev is None or rating > prev[0]:
                    out[key][skill] = (rating, years)
    return out


def low_month(person):
    months = [(m, person["pct"][m]) for m in D.MONTHS if person["pct"].get(m) is not None]
    m, v = min(months, key=lambda t: t[1])
    return D.MONTH_LABELS[m], v


def fits_for(role, skills_by_person):
    """Score cohort members against the role's named skills; return top 2."""
    scored = []
    for p in D.COHORT:
        sk = skills_by_person.get(p["name"], {})
        matched = []
        total = 0.0
        for want in role["skills"]:
            got = sk.get(want)
            if got and got[0] >= 3:
                matched.append((want, got[0]))
                total += got[0]
        if len(matched) >= 2:
            matched.sort(key=lambda t: -t[1])
            scored.append((total, len(matched), p, [m[0] for m in matched[:3]]))
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]["name"]))
    return scored[:2]


# ---------------------------------------------------------------- section 4 (8-week outlook)

def outlook_section():
    """Section 4, the 8-Week Outlook (staff-by-week grid, open-role weekly demand,
    capacity vs. need). Rendered by build_outlook_section.py from outlook_data.py."""
    try:
        import build_outlook_section
        return build_outlook_section.section4(after_outlook=projects_section())
    except Exception as ex:
        print(f"  note: 8-week outlook section skipped ({ex})")
        return ""


def projects_section():
    """Projects, Roles & Open Demand - the project-first view of the same 8 weeks
    (added Sep 10 2026). Rendered by build_projects_section.py from outlook_data.py
    plus projects_meta.py (consultant titles / job levels, project PM and stage).
    Sits directly after the 8 Week Outlook staff grid."""
    try:
        import build_projects_section
        return build_projects_section.section_projects()
    except Exception as ex:
        print(f"  note: projects & roles section skipped ({ex})")
        return ""


# ---------------------------------------------------------------- section 3

def delta_cell(delta, cls_extra="num "):
    if delta < -0.05:
        cls, txt = "delta-under", f"{delta:.1f}"
    elif delta > 0.05:
        cls, txt = "delta-over", f"+{delta:.1f}"
    else:
        cls, txt = "", f"+{abs(delta):.1f}"
    return f'<td class="{cls_extra}delta {cls}">{txt}</td>'



def s3_weeks_phrase():
    wks = [w[0] for w in getattr(D, "S3_WEEKS", [])]
    if not wks:
        return "in the window"
    from params import S3_YEAR
    return ", ".join(wks[:-1]) + " and " + wks[-1] + f" {S3_YEAR}"


def ats_asof_phrase():
    try:
        import outlook_data as _O
        rw = getattr(_O, "RECRUITING_WEEK", None)
        return f" of {rw['as_of']}" if rw else ""
    except Exception:
        return ""


def section3():
    t = D.S3_TOTAL
    delta = t["actual"] - t["alloc"]
    billed = pct_str(t["actual"] / t["alloc"]) if t["alloc"] else 0
    n_wk = len(getattr(D, "S3_WEEKS", [])) or 4
    fte = abs(delta) / (40.0 * n_wk)
    dcls = "delta-under" if delta < 0 else "delta-over"
    dsign = "" if delta < 0 else "+"
    # Rolling last-4-complete-weeks view (Mark, Sep 16 2026): one chip per week.
    chips = []
    for label, a, ac in getattr(D, "S3_WEEKS", []):
        d = ac - a
        chips.append(f'    <span class="chg {"chg-down" if d < 0 else "chg-up"}" '
                     f'title="Week of {label}: {a:,.1f} hrs allocated, {ac:,.1f} hrs actual">'
                     f'<b class="chg-b">{label}</b> {ac:,.0f}/{a:,.0f} hrs &middot; {"" if d < 0 else "+"}{d:.1f}</span>')
    weeks_html = ('  <div class="chg-list s3-weeks">\n' + "\n".join(chips) + "\n  </div>\n") if chips else ""

    return f"""<section class="section3">
  <h2 class="sec-head">Allocation vs Actual Hours for the Last 4-weeks</h2>

  <div class="section3-summary">
    <span class="headline-label">Total &middot; {t["people"]} employees</span>
    <span class="headline-figs">
      <span class="headline-fig">{t["alloc"]:,.1f} hrs allocated</span>
      <span class="headline-sep">&middot;</span>
      <span class="headline-fig">{t["actual"]:,.1f} hrs actual</span>
      <span class="headline-sep">&middot;</span>
      <span class="headline-fig delta {dcls}">{dsign}{delta:.1f} hrs ({billed}% billed)</span>
      <span class="headline-sep">&middot;</span>
      <span class="headline-fig">&asymp;{fte:.1f} FTEs variance <span class="headline-fc-tag">(basis: 40 hrs/wk &times; {n_wk} wks)</span></span>
    </span>
  </div>
{weeks_html}
{S3V.charts_block(D.S3_ACCOUNTS, D.S3_CONSULTANTS, getattr(D, "S3_PAIRS", None))}
</section>"""


# ---------------------------------------------------------------- headline bands

def headline_bands():
    this_label, this_v = D.ORG_MONTHLY[D.ORG_THIS_IDX]
    fc = D.ORG_MONTHLY[D.ORG_THIS_IDX + 1:D.ORG_THIS_IDX + 4]     # three months out (Mark, Oct 20 2026)
    thin = thin_months()
    proj = projection()
    figs = [f'<span class="headline-fig headline-current">{pct_str(this_v)}% {this_label[:3]}</span>']
    if proj:
        figs.append(f'<span class="headline-fig headline-proj" title="{e(proj["note"])}">'
                    f'proj. close {proj["value"] * 100:.1f}%</span>')
    for k, (lab, v) in enumerate(fc):
        tag = ' <span class="headline-fc-tag">(bookings still filling in)</span>' if (D.ORG_THIS_IDX + 1 + k) in thin else ""
        figs.append(f'<span class="headline-fig headline-forecast">{pct_str(v)}% {lab[:3]}{tag}</span>')
    figs[-1] = figs[-1].replace("</span>", ' <span class="headline-fc-tag">(forecast)</span></span>', 1) if "fc-tag" not in figs[-1] else figs[-1]
    band1 = f"""<section class="headline-band">
  <span class="headline-label">Org-wide utilization</span>
  <span class="headline-figs">
    {'<span class="headline-sep">·</span>'.join(figs)}
  </span>
</section>"""

    counts = []
    for m in getattr(D, "COHORT_MONTHS", D.MONTHS[:3]):
        n = sum(1 for p in D.COHORT
                if p["pct"].get(m) is not None and p["pct"][m] < p["target"])
        counts.append((D.MONTH_LABELS[m], n))
    band2 = f"""<section class="headline-band under-target-band">
  <span class="headline-label">Consultants under target utilization</span>
  <span class="headline-figs">
    <span class="headline-fig headline-current">{counts[0][1]} {counts[0][0]}</span>
    <span class="headline-sep">&middot;</span>
    <span class="headline-fig headline-forecast">{counts[1][1]} {counts[1][0]}</span>
    <span class="headline-sep">&middot;</span>
    <span class="headline-fig headline-forecast">{counts[2][1]} {counts[2][0]} <span class="headline-fc-tag">(forecast)</span></span>
  </span>
</section>"""
    return band1, band2


# Mark, Oct 20 2026: the "Generated ..." footer is no longer rendered (kept for reference).
FOOTER_RETIRED = """<footer class="dash-footer">
  <p>Generated {gen} for the {meeting} staffing meeting. Consultant utilization and PTO: <code>CONS_WEEKLY_AVAILABILITY</code>; allocations for this week: <code>CONS_CONSULTANT_PROJECT_DETAIL</code>; Allocation vs. actual hours for the last 4 weeks: <code>CONS_PROJECT_TIME</code> (weekly grain, the four complete weeks beginning {s3weeks} &mdash; ending with last week; employees only, contractors and internal projects excluded). The current week is excluded because its timesheets are still being submitted; the four weeks shown are closed, though late timesheet entry can still move the most recent week. The consultants-under-target headline band counts Direct-relationship consultants flagged under target (<code>FLAG_UNDER_TARGET</code>) in each month of the three-month window (current-week roster and standing exclusions applied); monthly figures are billable hours over the utilization denominator for that month. The headline band and monthly utilization chart read from the <code>Grand Total</code> practice row (org-wide, includes employees and contractors) and do not reconcile with the staff schedule, which is scoped to the named delivery practices (employees only) &mdash; a known upstream data-population difference, not a bug. The 8-Week Outlook section covers the Direct-relationship employee consultants with schedule rows in its 8-week window (standing exclusions applied): weekly percentages are scheduled billable time over the utilization denominator from <code>CONS_WEEKLY_AVAILABILITY</code>, colored against each consultant's target judged net of scheduled PTO; per-week project assignments and booked hours come from <code>CONS_CONSULTANT_PROJECT_DETAIL</code>. Where <code>CONS_WEEKLY_AVAILABILITY</code> carries no utilization denominator for a consultant who is nonetheless on the roster with booked work, the percentage is estimated as booked hours over a 40-hour week net of PTO and tagged <b>est.</b> &mdash; those consultants previously read as &quot;n/m&quot; in every week, which made an upstream data gap look like an absence. Each week cell lists every project that consultant is booked to that week, shown as a share of their scheduled time; cells with more than three projects show the largest two and hide the rest behind a &quot;+n more&quot; link &mdash; click it, or use &quot;Expand all projects&quot; at the top of the section, to see the full list. The Projects, Roles &amp; Open Demand section is the same 8 weeks read project-first: click any project to expand the consultants assigned to it (with their title and job level from <code>CONS_CONSULTANT</code>) and its unfilled roles. Its cells are allocated billable hours per week rather than percentages, so each project row is the sum of its expanded lines and the bottom row reconciles with the &quot;Booked on projects&quot; and &quot;Open roles&quot; rows of the capacity table; project manager, status and opportunity stage come from <code>CONS_CONSULTANT_PROJECT_DETAIL</code>. Contractor and overhead projects are not shown, since the roster is employees only, and internal or SG&amp;A requisitions (the practice-director, marketing and delivery-lead searches, and any client requisition Salesforce has not scheduled) are listed in Open Roles &amp; Recruiting rather than here, because they carry no project and no scheduled demand. Open-role demand comes from <code>CONS_OPEN_DEMAND</code> (pulled the same day &mdash; this view moves intraday), whose hours are per day and are shown as hours per week (&times;5 days). Capacity assumes a 40-hour week per consultant minus scheduled PTO, with holiday-shortened weeks on a 32-hour base (open-role demand in those weeks is likewise 4 days); the "at target utilization" row scales each consultant's PTO-adjusted hours by their personal utilization target &mdash; the billable hours the org plans for rather than the physical maximum (the surplus/gap row is measured against full capacity). Need = booked hours plus unfilled open-role demand, including pre-SOW pipeline roles at the Salesforce stages and probabilities shown &mdash; the gap is therefore the worst case if every deal lands and no role is filled; it shrinks as deals slip or roles are filled. Recruiting detail on each open role (interviewing counts, target start dates, recruiter and the latest status note) comes from the ATS all-jobs status export{ats_asof}; its compensation columns are dropped at read time and any pay language is scrubbed from the notes before they reach this page. Each open role carries up to three suggestions from current staff, scored out of 100 on five signals: free hours in exactly the weeks that role needs (40 points &mdash; a 40-hour week less scheduled PTO less hours already booked), billable hours for that client over the last twelve months from <code>CONS_PROJECT_TIME</code> (20), skill ratings from the Skills Matrix 2025 consolidation on the technologies named in the role title (25), practice against the discipline the role names (10) and job level against the seniority it names (5). Geography is a filter rather than a score, so a US role never suggests CTI staff or the reverse, and a role only suggests its own discipline unless someone clears the bar on the named technologies anyway. Seven of the consultants on the roster have no skills-matrix entry and say so in place of a skills line; the matrix itself dates from November 2025, so treat the skill ratings as the weakest of the five signals. A role showing fewer than three names, or none, is a genuine bench result &mdash; it needs recruiting or rescheduling, not a wider search. The Meeting Agenda list is shared: it lives in this page&#39;s data store on claude.ai, is visible live to everyone who opens the page, and survives the weekly data refresh; a downloaded copy cannot reach it.</p>
</footer>"""


def css():
    with open("dashboard_style.css", encoding="utf-8") as fh:
        return fh.read()


def build():
    skills_by_person = load_skills()
    band1, band2 = headline_bands()
    ADJ_BANNER = adjustment_banner()
    body = f"""<div class="viz-root">
  <div class="dash-title">{TITLE}</div>
  <div class="dash-subtitle">Consultant data as of week of {D.THIS_WEEK}</div>
{ADJ_BANNER}

{AGENDA.AGENDA_HTML}

<section class="summary-panel">
  <h2 class="sec-head">Summary</h2>

{band1}
{band2}
<section class="monthly-util-panel">
  <div class="panel-label">Monthly utilization &middot; last 6 months, this month, next 3 months &mdash; org-wide (includes employees and contractors) &middot; coloured against the {int(ORG_TARGET * 100)}% target like the Outlook cells{" &middot; * bookings for that month are still being entered" if thin_months() else ""}</div>
{org_chart()}
  <div class="chart-legend">
    <span class="legend-item"><span class="legend-dot"></span>Actual</span>
    <span class="legend-item"><span class="legend-dot-open"></span>Forecast</span>
    {'<span class="legend-item"><span class="legend-diamond"></span>Projected close (hover for the basis)</span>' if projection() else ''}
    <span class="legend-item"><span class="swatch" style="background:var(--accent)"></span>Above target</span>
    <span class="legend-item"><span class="swatch" style="background:var(--status-good)"></span>At target</span>
    <span class="legend-item"><span class="swatch" style="background:var(--status-warning)"></span>Below by &le;20 pts</span>
    <span class="legend-item"><span class="swatch" style="background:var(--status-serious)"></span>Below by 20&ndash;50 pts</span>
    <span class="legend-item"><span class="swatch" style="background:var(--status-critical)"></span>Below by &ge;50 pts</span>
  </div>
{projection_why()}</section>
</section>


{outlook_section()}


{section3()}


<footer class="dash-footer"></footer>

</div>

{AGENDA.AGENDA_JS}"""

    fragment = f"<title>{TITLE}</title>\n<style>\n{css()}</style>\n\n{body}"
    with open("dashboard_artifact.html", "w", encoding="utf-8") as fh:
        fh.write(fragment)

    full = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'<title>{TITLE}</title>\n<style>\nbody {{ margin: 0; padding: 0; }}\n'
            f'{css()}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n')
    with open("dashboard.html", "w", encoding="utf-8") as fh:
        fh.write(full)

    print(f"cohort={len(D.COHORT)} roles={len(D.OPEN_ROLES)} "
          f"s3_people={len(D.S3_CONSULTANTS)} accounts={len(D.S3_ACCOUNTS)}")
    for p in D.COHORT:
        if p["name"] not in skills_by_person:
            print(f"  note: no skills-matrix entry for {p['name']}")


if __name__ == "__main__":
    build()
