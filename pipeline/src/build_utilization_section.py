#!/usr/bin/env python3
"""Utilization by Practice, YTD - practice x month table with a drill-down to each
consultant (added Sep 17 2026 at Mark's request: "utilization by department by month
YTD with the ability to drill down into each department to see utilization by person").

Reads utilization_data.py (written by make_util_data.py). Two ways to use it:

    python3 build_utilization_section.py in.html out.html
        post-processing pass: inserts the section directly after the Summary panel and
        its CSS at the end of the page's main stylesheet. Idempotent - an existing
        Utilization section is replaced.

    import build_utilization_section as U; U.section_html(); U.CSS
        for a from-scratch build_dashboard.py run.

Colour rule matches the 8 Week Outlook cells: above target (accent), at target (good),
below by <=20 pts (warning), <50 (serious), else critical. Practice targets are the
denominator-weighted average of their consultants' personal targets that month.
"""
from params import UTIL_YEAR
import html
import sys

import utilization_data as U

SECTION_ID = "util-section"
PRAC_INDEX = {"AI Engineering": 0, "Data Management": 1, "Data Viz. & Analytics": 2,
              "Delivery": 3, "Portfolio Mgmt": 4, "Solution Architecture": 5}


def e(s):
    return html.escape(str(s), quote=True)


def pct_str(v):
    return int(v * 100 + 0.5)


def cell_class(v, target):
    if v is None:
        return "wk-na"
    gap = (target - v) * 100.0
    if v > target + 0.005:
        return "wk-above"
    if gap <= 0.5:
        return "wk-at"
    if gap <= 20:
        return "wk-warning"
    if gap < 50:
        return "wk-serious"
    return "wk-critical"


def pct_cell(v, target, est=False, title="", ytd=False, muted=False):
    extra = " util-ytd" if ytd else ""
    if v is None:
        return f'<td class="wk"><div class="wk-cell wk-na util-cell{extra}" title="{e(title)}">&ndash;</div></td>'
    cls = "wk-muted" if muted else cell_class(v, target)
    chip = ('<span class="est-chip" title="Estimated: the source view carries no utilization '
            'denominator for part of this month, so those weeks are booked hours over a '
            '40-hour week net of PTO">est.</span>') if est else ""
    return (f'<td class="wk"><div class="wk-cell {cls} util-cell{extra}" title="{e(title)}">'
            f'<span class="wk-pct">{pct_str(v)}%</span>{chip}</div></td>')


def header_row():
    cells = []
    for m in U.MONTHS:
        tag = ' <span class="util-cur-tag">(scheduled)</span>' if m == U.CURRENT_MONTH else ""
        cells.append(f'<th class="wk">{U.LABELS[m]}{tag}</th>')
    return ('<tr><th class="util-col-name">Practice / consultant</th>' + "".join(cells) +
            '<th class="wk util-ytd-h">YTD</th><th class="util-col-target">Target</th></tr>')


def practice_row(prac):
    idx = PRAC_INDEX.get(prac, 0)
    monthly = U.PRACTICE_MONTHLY[prac]
    tgt = U.PRACTICE_TARGET[prac]
    n = monthly["ytd"][1]
    cells = []
    for m in U.MONTHS:
        v, cnt, b, d = monthly[m]
        cells.append(pct_cell(v, tgt[m], title=f"{prac}, {U.LABELS[m]}: {cnt} consultants measured, "
                                              f"weighted target {pct_str(tgt[m])}%"))
    v = monthly["ytd"][0]
    cells.append(pct_cell(v, tgt["ytd"], ytd=True, title=f"{prac}, year to date"))
    key = e(prac.lower().replace(" ", "-").replace(".", "").replace("&", "and"))
    return (f'<tr class="util-prac-row prac-{idx}" data-prac="{key}" tabindex="0" role="button" '
            f'aria-expanded="false" aria-controls="util-people-{key}">'
            f'<td class="util-name-cell"><span class="pj-caret"></span>'
            f'<span class="util-prac-name">{e(prac)}</span> '
            f'<span class="count-chip">{n} consultants</span></td>'
            + "".join(cells) +
            f'<td class="util-target num">{pct_str(tgt["ytd"])}%</td></tr>')


def person_rows(prac):
    key = prac.lower().replace(" ", "-").replace(".", "").replace("&", "and")
    rows = []
    for name, row in U.PEOPLE[prac].items():
        meta = U.META[name]
        target = meta["target"] or 0.9
        cells = []
        for m in U.MONTHS:
            if m in row:
                v, est = row[m]
                cells.append(pct_cell(v, target, est=est, title=f"{name}, {U.LABELS[m]}"))
            else:
                other = U.MOVES.get(name, {}).get(m)
                title = f"{name} was in {other} in {U.LABELS[m]}" if other else f"No schedule row for {name} in {U.LABELS[m]}"
                cells.append(f'<td class="wk"><div class="wk-cell wk-na util-cell" title="{e(title)}">&ndash;</div></td>')
        v, est = row["ytd"]
        cells.append(pct_cell(v, target, est=est, ytd=True, title=f"{name}, year to date in {prac}"))
        level = f'<span class="pj-level">{e(meta["level"])}</span>' if meta.get("level") else ""
        moved = ""
        others = sorted({p for p in U.MOVES.get(name, {}).values() if p != prac})
        if others:
            moved = f'<span class="util-moved" title="Also has months recorded under {e(", ".join(others))}">also {e(", ".join(others))}</span>'
        badge = "" if abs(target - 0.9) < 1e-9 else f'<span class="target-badge">Target: {pct_str(target)}%</span>'
        rows.append(f'<tr class="util-person" data-prac="{e(key)}" hidden>'
                    f'<td class="util-name-cell pj-indent"><span class="pj-person">{e(name)}</span>{level}{badge}{moved}</td>'
                    + "".join(cells) +
                    f'<td class="util-target num">{pct_str(target)}%</td></tr>')
    return "\n".join(rows)


def total_rows():
    a = U.ALL_PRACTICES
    cells = []
    for m in U.MONTHS:
        v, n, b, d = a[m]
        cells.append(pct_cell(v, 0.9, muted=True, title=f"All delivery practices, {U.LABELS[m]}: {n} consultants measured"))
    cells.append(pct_cell(a["ytd"][0], 0.9, ytd=True, muted=True, title="All delivery practices, year to date"))
    r1 = ('<tr class="util-total-row"><td class="util-name-cell">All delivery practices '
          f'<span class="count-chip">{a["ytd"][1]} consultants YTD</span></td>' + "".join(cells) +
          '<td class="util-target num">&ndash;</td></tr>')
    cells = []
    for m in U.MONTHS:
        v = U.ORG_WIDE.get(m)
        cells.append(pct_cell(v, 0.9, muted=True, title=f"Org-wide (Grand Total row, includes contractors), {U.LABELS[m]}"))
    cells.append('<td class="wk"><div class="wk-cell wk-na util-cell util-ytd">&ndash;</div></td>')
    r2 = ('<tr class="util-org-row"><td class="util-name-cell">Org-wide <span class="util-org-note">Summary basis &middot; includes contractors</span></td>'
          + "".join(cells) + '<td class="util-target num">&ndash;</td></tr>')
    return r1 + "\n" + r2


def section_html():
    body = []
    for prac in U.PRACTICES:
        body.append(practice_row(prac))
        body.append(person_rows(prac))
    body.append(total_rows())
    first, last = U.LABELS[U.MONTHS[0]], U.LABELS[U.MONTHS[-1]]
    n_people = U.ALL_PRACTICES["ytd"][1]
    return f'''<section class="section4 util-section" id="{SECTION_ID}">
  <h2 class="sec-head">Utilization by Practice <span class="section4-range">{first}&ndash;{last} {UTIL_YEAR} YTD &middot; {len(U.PRACTICES)} practices &middot; {n_people} consultants &middot; employees</span></h2>
  <div class="outlook-controls">
    <button type="button" class="outlook-btn" id="util-expand-all" aria-pressed="false">Expand all practices</button>
    <span class="s3-tabs-note">click a practice to see utilization by consultant &middot; monthly value is billable hours over the utilization denominator &middot; <b>{last}</b> includes scheduled weeks through month end</span>
  </div>
  <div class="util-scroll">
  <table class="outlook-table util-table" id="util-table">
    <thead>{header_row()}</thead>
    <tbody>
{chr(10).join(body)}
    </tbody>
  </table>
  </div>
</section>
<script>
(function () {{
  var table = document.getElementById("util-table");
  if (!table) return;
  var btn = document.getElementById("util-expand-all");
  function setOpen(row, open) {{
    var key = row.getAttribute("data-prac");
    row.classList.toggle("pj-open", open);
    row.setAttribute("aria-expanded", open ? "true" : "false");
    table.querySelectorAll('tr.util-person[data-prac="' + key + '"]').forEach(function (tr) {{
      if (open) tr.removeAttribute("hidden"); else tr.setAttribute("hidden", "");
    }});
  }}
  function syncBtn() {{
    var rows = table.querySelectorAll("tr.util-prac-row");
    var allOpen = Array.prototype.every.call(rows, function (r) {{ return r.classList.contains("pj-open"); }});
    btn.textContent = allOpen ? "Collapse all practices" : "Expand all practices";
    btn.setAttribute("aria-pressed", allOpen ? "true" : "false");
    btn.classList.toggle("outlook-btn-active", allOpen);
  }}
  table.querySelectorAll("tr.util-prac-row").forEach(function (row) {{
    row.addEventListener("click", function (ev) {{
      if (ev.target.closest("button, a, input, select, textarea")) return;
      setOpen(row, !row.classList.contains("pj-open")); syncBtn();
    }});
    row.addEventListener("keydown", function (ev) {{
      if (ev.key === "Enter" || ev.key === " ") {{ ev.preventDefault(); setOpen(row, !row.classList.contains("pj-open")); syncBtn(); }}
    }});
  }});
  btn.addEventListener("click", function () {{
    var open = btn.getAttribute("aria-pressed") !== "true";
    table.querySelectorAll("tr.util-prac-row").forEach(function (r) {{ setOpen(r, open); }});
    syncBtn();
  }});
}})();
</script>'''


CSS = """
/* ================= Utilization by Practice (YTD) ============================ */
.util-scroll { overflow-x: auto; }
table.util-table th.util-col-name { min-width: 250px; }
table.util-table th.wk, table.util-table td.wk { padding-left: 2px; padding-right: 2px; }
.util-cur-tag { font-size: 9px; font-weight: 600; text-transform: none; letter-spacing: 0; color: var(--muted-ink); display: block; line-height: 1; }
.util-cell { min-width: 58px; padding: 5px 4px; }
.util-cell.util-ytd { font-size: 13px; }
.util-cell.util-ytd .wk-pct { font-size: 13px; }
.util-ytd-h { border-left: 2px solid var(--baseline); }
table.util-table td.wk:has(.util-ytd) { border-left: 2px solid var(--baseline); }
.util-col-target, .util-target { text-align: right; font-size: 11.5px; color: var(--text-secondary); padding-right: 8px !important; white-space: nowrap; }
tr.util-prac-row { cursor: pointer; }
tr.util-prac-row td { background: var(--surface-page); border-top: 1px solid var(--baseline); padding-top: 6px; padding-bottom: 6px; }
tr.util-prac-row td:first-child { border-left: 4px solid var(--prac, var(--gridline)); }
tr[class*="prac-"].util-prac-row td:first-child { background: color-mix(in srgb, var(--prac) 14%, var(--surface-1)); }
.util-prac-name { font-weight: 700; font-size: 12.5px; color: var(--prac, var(--text-primary)); text-decoration: underline; text-decoration-color: var(--gridline); text-underline-offset: 2px; }
tr.util-prac-row:hover .util-prac-name { text-decoration-color: var(--accent); }
tr.util-prac-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
tr.util-prac-row .count-chip { margin-left: 6px; }
tr.util-person td { border-bottom: none; padding-top: 2px; padding-bottom: 2px; }
tr.util-person:has(+ tr.util-prac-row) td, tr.util-person:has(+ tr.util-total-row) td { border-bottom: 1px solid var(--gridline); }
tr.util-person .target-badge { margin-left: 6px; }
.util-moved { display: inline-block; font-size: 9.5px; color: var(--muted-ink); margin-left: 6px; font-style: italic; cursor: help; }
tr.util-total-row td { font-weight: 700; background: var(--surface-page); border-top: 2px solid var(--baseline); padding-top: 6px; padding-bottom: 6px; }
tr.util-org-row td { color: var(--text-secondary); padding-top: 4px; padding-bottom: 6px; }
.util-org-note { font-size: 10px; font-weight: 600; color: var(--muted-ink); margin-left: 6px; text-transform: uppercase; letter-spacing: 0.03em; }
.wk-muted { background: color-mix(in srgb, var(--muted-ink) 12%, transparent); box-shadow: inset 3px 0 0 var(--baseline); }
.wk-na.util-cell { color: var(--muted-ink); padding: 6px 4px; }
#util-table tr[hidden] { display: none !important; }
"""

FOOTER_NOTE = (" The Utilization by Practice table is year to date from <code>CONS_WEEKLY_AVAILABILITY</code>: "
               "each month is billable hours over the utilization denominator summed across the month&#39;s weeks, "
               "per consultant and per practice (Direct-relationship employees, standing exclusions applied, "
               "AI/ML and AI/ML/AppDev rows folded into AI Engineering); a consultant who changed practice during "
               "the year counts toward the practice recorded for each month, so their row appears under each. "
               "Practice cells are coloured against the denominator-weighted average of their consultants&#39; "
               "targets. The current month includes scheduled weeks through month end, the same basis as the "
               "Summary headline. The org-wide row is the <code>Grand Total</code> practice row the Summary uses, "
               "which includes contractors and therefore does not reconcile with the employee-only rows above it.")


def inject(page):
    """Insert (or replace) the section at the bottom of the page (above the footer) and append the CSS to
    the main stylesheet. Works on the published page and on the artifact fragment."""
    import re
    # remove a previous copy
    page = re.sub(r'<section class="section4 util-section" id="%s">.*?</section>\s*<script>\(function \(\) \{\s*var table = document\.getElementById\("util-table"\).*?</script>\n?' % SECTION_ID,
                  "", page, flags=re.S)
    if "Utilization by Practice (YTD)" not in page:
        # main stylesheet = the one that contains .viz-root tokens
        i = page.find(".viz-root {")
        j = page.find("</style>", max(i, 0))
        assert j > 0, "no stylesheet to append the utilization CSS to"
        page = page[:j] + CSS + page[j:]
    # At the bottom of the page, above the footer (Mark, Sep 21 2026 - it sat directly under
    # Summary from Sep 17 to Sep 21).
    j = page.find('<footer class="dash-footer">')
    assert j > 0, "footer not found"
    page = page[:j] + section_html() + "\n\n" + page[j:]
    if FOOTER_NOTE.strip() not in page:
        k = page.find("</p>\n</footer>")
        if k > 0:
            page = page[:k] + FOOTER_NOTE + page[k:]
    return page


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as fh:
        page = fh.read()
    page = inject(page)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {dst}: {len(U.PRACTICES)} practices, "
          f"{sum(len(v) for v in U.PEOPLE.values())} consultant rows")
