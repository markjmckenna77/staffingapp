#!/usr/bin/env python3
"""Merge 'Open Roles & Recruiting' into the 8 Week Outlook staff grid.

Mark, Sep 15 2026: "combine the open roles with the 8 week outlook so all Data
Management open roles appear at the bottom of the Data Management section in the
8 week outlook."

Applied surgically to the published Version 32 HTML (the project's data modules
predate Version 31's Ascend unassignment, so regenerating would silently revert
it). The same layout is carried into build_outlook_section.py for Friday's
rebuild.

Layout after this pass:
  - every open role renders as a COMPACT row at the bottom of its practice band
    in #staff-grid, under a small "Open roles" sub-head;
  - the recruiting update, the suggestions and the comment thread move into a
    detail block that opens when the role is clicked (nothing is lost, the grid
    just does not carry it by default);
  - requisitions with no scheduled demand in Salesforce (the SG&A and internal
    searches) and the vacated Controller line go into a final
    "Open roles - no delivery practice" band;
  - the standalone Open Roles & Recruiting section is retired; its geography
    filter, its suggestion legend, its unfilled-demand total row and its scripts
    move into the outlook.

Run it as a POST-PROCESSING PASS on the weekly build:

    python3 build_dashboard.py                 # writes dashboard_artifact.html as usual
    python3 merge_open_roles.py dashboard_artifact.html dashboard_artifact.html

It is data-independent: it reads whatever roles the build emitted, maps each to a
practice by rule, and rewrites the two tables into one. Defaults are the surgical
run of Sep 15 2026 (v32.html -> dashboard_artifact.html).
"""
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "v32.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else "dashboard_artifact.html"

src = open(SRC, encoding="utf-8").read()
lines = src.split("\n")


# ---------------------------------------------------------------- role practice

def practice_of(title, has_hours):
    """Which staff-grid practice band an open role belongs at the bottom of.

    Rule-based rather than a hand-written map so next week's roles land without
    editing. A requisition with no scheduled demand in Salesforce (hrs 0, no week
    cells) never claims a delivery band - those are the practice-director and
    SG&A searches, and Mark asked for them in their own band at the bottom.
    """
    if not has_hours:
        return None
    t = " " + re.sub(r"\s+", " ", title).lower() + " "
    for pattern, practice in [
        (r"dv&a|data viz|visuali[sz]ation|dashboard|analytics|reporting|\bbi\b",
         "Data Viz. & Analytics"),
        (r"data engineer|data engineering|databricks|snowflake|\betl\b|ingestion|"
         r"data governance|data management|data steward|data architect",
         "Data Management"),
        (r"full stack|ai engineer|\bai\b|ai/ml|\bml\b|machine learning|genai",
         "AI Engineering"),
        (r"solutions? architect|architecture", "Solution Architecture"),
        (r"portfolio manage|\bpm\b|project manager|program manager", "Portfolio Mgmt"),
        (r"delivery lead|delivery manage|engagement manager", "Delivery"),
    ]:
        if re.search(pattern, t):
            return practice
    return None


# ---------------------------------------------------------------- extract roles

ROLES_START = next(i for i, l in enumerate(lines) if 'id="roles-table"' in l)
ROLES_SEC_START = next(i for i, l in enumerate(lines) if 'section4 roles-section' in l)
ROLES_SEC_END = next(i for i in range(ROLES_SEC_START, len(lines))
                     if lines[i].strip() == "</section>")

body = lines[ROLES_START + 2:]                     # past <thead> and <tbody>
blocks, total_row, fits_legend, geo_bar = [], None, None, None
for l in body:
    s = l.strip()
    if s.startswith("</tbody>"):
        break
    if 'class="demand-main' in s:
        blocks.append({"main": l, "subs": []})
    elif 'class="demand-sub' in s:
        blocks[-1]["subs"].append(l)
    elif 'demand-total-row' in s:
        total_row = l

fits_legend = next(l for l in lines[ROLES_SEC_START:ROLES_START] if "fits-legend" in l)
geo_bar = next(l for l in lines[ROLES_SEC_START:ROLES_START] if 'class="geo-bar"' in l)

# the two scripts at the tail of the roles section (geo filter + .role-comment
# store binding) - they move into the outlook with the rows they drive
script_start = next(i for i in range(ROLES_START, ROLES_SEC_END) if lines[i].strip() == "<script>")
roles_scripts = "\n".join(lines[script_start:ROLES_SEC_END])
assert roles_scripts.startswith("<script>")
roles_scripts = (roles_scripts
                 .replace('#roles-table tr[data-geo]', '#staff-grid tr[data-geo]')
                 .replace('#roles-table tr.demand-main', '#staff-grid tr.demand-main')
                 .replace('#roles-table .wk-demand-total', '#staff-grid .wk-demand-total')
                 .replace('r.hidden = (g !== "all" && r.dataset.geo !== g);',
                          'r.classList.toggle("geo-off", g !== "all" && r.dataset.geo !== g);')
                 .replace('if (r.hidden) return;',
                          'if (r.classList.contains("geo-off")) return;'))
assert 'geo-off' in roles_scripts and '#roles-table' not in roles_scripts

print(f"roles found: {len(blocks)}")

TITLE_RE = re.compile(r'<div class="demand-role">(.*?)</div>', re.S)
HRS_RE = re.compile(r'data-h="([0-9.]+)"')

for n, b in enumerate(blocks):
    inner = TITLE_RE.search(b["main"]).group(1)
    title = re.sub(r"<[^>]+>", "", inner)
    title = re.sub(r"\s+", " ", title).replace("&amp;", "&").strip()
    hrs = [float(x) for x in HRS_RE.findall(b["main"])]
    assert len(hrs) == 8, (title, hrs)          # one data-h per week, empties carry 0
    b.update(id=f"or{n}", inner=inner, title=title, hours=hrs,
             practice=practice_of(title, sum(hrs) > 0))

for b in blocks:
    print(f"  {b['practice'] or '(no practice)':<24} {b['title'][:72]}  "
          f"[peak {max(b['hours']):g} hrs/wk, {len(b['subs'])} detail rows]")


# ---------------------------------------------------------------- rebuild rows

def detail_kinds(b):
    bits = []
    if any("demand-update" in s for s in b["subs"]):
        bits.append("recruiting update")
    for s in b["subs"]:
        m = re.search(r'class="fit-rank"', s)
        if m:
            n = s.count('class="fit-card"')
            bits.append(f"{n} suggested from staff" if n else "suggestions")
            break
        if "fits-row" in s:
            bits.append("no staff fit")
            break
    bits.append("comments")
    return " &middot; ".join(bits)


def rebuild(b):
    """One open role: a compact main row plus its hidden detail rows."""
    main = b["main"]
    main = main.replace('class="demand-main has-sub"', 'class="demand-main role-row"', 1)
    main = main.replace('class="demand-main"', 'class="demand-main role-row"', 1)
    main = main.replace(' <td class="col-demand-name">', ' <td class="col-demand-name">')
    toggle = (f'<div class="demand-role"><button type="button" class="role-toggle" '
              f'aria-expanded="false" data-role="{b["id"]}">'
              f'<span class="pj-caret"></span><span class="role-title">{b["inner"]}</span>'
              f'</button></div>')
    main = TITLE_RE.sub(lambda m: toggle, main, count=1)
    hint = (f'<div class="role-detail-hint" aria-hidden="true">{detail_kinds(b)}</div>')
    main = main.replace('</div></td>', f'</div>{hint}</td>', 1)
    main = main.replace("<tr ", f'<tr data-role-id="{b["id"]}" ', 1)
    out = [main]
    for s in b["subs"]:
        s = s.replace('class="demand-sub', 'class="role-detail demand-sub', 1)
        s = s.replace("<tr ", f'<tr hidden data-role-parent="{b["id"]}" ', 1)
        out.append(s)
    return out


PRACTICES = ["AI Engineering", "Data Management", "Data Viz. & Analytics",
             "Delivery", "Portfolio Mgmt", "Solution Architecture"]
by_prac = {p: [] for p in PRACTICES}
orphans = []
for b in blocks:
    (by_prac[b["practice"]] if b["practice"] in by_prac else orphans).append(b)


def open_head(practice, roles):
    hrs = max(sum(b["hours"][i] for b in roles) for i in range(8))
    return ('        <tr class="grid-open-head"><td colspan="9">Open roles '
            f'<span class="count-chip pj-chip-open">{len(roles)}</span>'
            f'<span class="goh-note">unfilled demand for {practice}'
            f'{f" &middot; {hrs:,.0f} hrs/wk at peak" if hrs else ""} '
            '&middot; click a role for the recruiting update, suggestions and comments'
            '</span></td></tr>')


# ---------------------------------------------------------------- splice grid

GRID_START = next(i for i, l in enumerate(lines) if 'id="staff-grid"' in l)
GRID_TBODY_END = next(i for i in range(GRID_START, len(lines)) if lines[i].strip() == "</tbody>")

grid = lines[GRID_START:GRID_TBODY_END]
new_grid, cur = [], None


def flush(cur, out):
    if cur and by_prac.get(cur):
        out.append(open_head(cur, by_prac[cur]))
        for b in by_prac[cur]:
            out.extend(rebuild(b))


for l in grid:
    if "outlook-practice-row" in l:
        flush(cur, new_grid)
        # practice name = the header text before its count chip (the header row carries a fold
        # button and, from Oct 20 2026, a hidden "+n contractors" chip after the count)
        cur = re.sub(r'<span class="count-chip.*$', "", l)
        cur = re.sub(r"<[^>]+>", "", cur).replace("&amp;", "&").strip()
        cur = re.sub(r"\s*\d+\s*$", "", cur).strip()
        n = len(by_prac.get(cur, []))
        if n:
            l = l.replace("</td></tr>",
                          f' <span class="count-chip pj-chip-open">+{n} open</span></td></tr>')
        new_grid.append(l)
    else:
        new_grid.append(l)
flush(cur, new_grid)

assert all(p in PRACTICES for p in by_prac), by_prac.keys()
placed = sum(len(v) for v in by_prac.values())
print(f"placed in practice bands: {placed}; in the no-practice band: {len(orphans)}")

if orphans:
    new_grid.append('        <tr class="outlook-practice-row prac-open"><td colspan="9">'
                    'Open roles &mdash; no delivery practice '
                    f'<span class="count-chip">{len(orphans)}</span></td></tr>')
    new_grid.append('        <tr class="grid-open-head"><td colspan="9">Open roles '
                    f'<span class="count-chip pj-chip-open">{len(orphans)}</span>'
                    '<span class="goh-note">requisitions with no scheduled demand in Salesforce '
                    '(practice-director and SG&amp;A searches)'
                    + (' and work vacated from a non-delivery role'
                       if any(b.get("vacated") or "(vacated)" in b["title"] for b in orphans) else "")
                    + ' &middot; click a role for the recruiting update and comments'
                    '</span></td></tr>')
    for b in orphans:
        new_grid.extend(rebuild(b))

new_grid.append(total_row)

# ---------------------------------------------------------------- section head

_hm = re.search(r'  <h2 class="sec-head">8 Week Outlook <span class="section4-range">(\d+) consultants '
                r'&times; 8 weeks &middot; weeks of ([^<]+)</span></h2>', src)
assert _hm, "heading moved"
head_old = _hm.group(0)
head_new = (f'  <h2 class="sec-head">8 Week Outlook <span class="section4-range">{_hm.group(1)} consultants '
            f'&middot; {len(blocks)} open roles &times; 8 weeks &middot; weeks of {_hm.group(2)}</span></h2>')

controls_old = ('        <span class="s3-tabs-note">every project a consultant is booked to that '
                'week &middot; or click <b>+n more</b> in a single cell &middot; hover a line for '
                'the full project name</span>')
assert controls_old in src
controls_new = ('        <button type="button" class="outlook-btn" id="outlook-expand-roles" '
                'aria-pressed="false">Expand all open roles</button>\n'
                '        <span class="s3-tabs-note">open roles sit at the bottom of their practice '
                '&middot; click a role for the recruiting update, suggestions and comments '
                '&middot; <b>+n more</b> opens a single week cell</span>')

# ---------------------------------------------------------------- assemble

out = []
out.extend(lines[:GRID_START])
out.extend(new_grid)
out.extend(lines[GRID_TBODY_END:ROLES_SEC_START])
out = "\n".join(out)

# the outlook section now carries the geography filter, the suggestion legend and
# the two scripts the roles table used to own
out = out.replace(head_old, head_new, 1)
out = out.replace(controls_old, controls_new, 1)
out = out.replace('      <div class="outlook-scroll"><table class="outlook-table staff-grid"',
                  geo_bar.replace("filter by geography", "filter open roles by geography")
                  + "\n" + fits_legend
                  + '\n      <div class="outlook-scroll"><table class="outlook-table staff-grid"',
                  1)
TAIL = "</script>\n</section>"
assert out.index(TAIL) > out.index('id="staff-grid"'), "outlook tail anchor is not the outlook's"

rest = "\n".join(lines[ROLES_SEC_END + 1:])
out = out + "\n" + rest

# --------------------------------------------------- app layer now reads the grid
before = out
out = out.replace("#roles-table tr[hidden] { display: none !important; }",
                  "#staff-grid tr[hidden] { display: none !important; }", 1)
out = out.replace('    var tbl = $("roles-table");', '    var tbl = $("staff-grid");', 1)
out = out.replace('    var rtbl = document.getElementById("roles-table");',
                  '    var rtbl = document.getElementById("staff-grid");', 1)
assert out != before and "roles-table" not in out, "app-layer lookups not rewired"

# ---------------------------------------------------------------- css + js

CSS = """
/* ---- open roles merged into the outlook grid (Mark, Sep 15 2026) ---------- */
#staff-grid tr[hidden] { display: none !important; }
.geo-off { display: none !important; }
tr.prac-open td { --prac: #b26a00; }
tr.grid-open-head td {
  background: color-mix(in srgb, var(--status-warning) 10%, var(--surface-1));
  border-top: 1px solid color-mix(in srgb, var(--status-warning) 45%, transparent);
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.03em;
  font-weight: 700; color: var(--text-secondary); padding: 4px 8px 4px 22px !important;
}
.goh-note { text-transform: none; letter-spacing: 0; font-weight: 500;
  font-size: 10.5px; color: var(--muted-ink); margin-left: 8px; }
tr.role-row td { border-bottom: 1px solid var(--gridline); }
tr.role-row td.col-demand-name { padding-left: 22px !important; }
tr.role-row.role-open td { border-bottom: none; }
button.role-toggle { display: block; width: 100%; text-align: left; background: none;
  border: none; padding: 0; font: inherit; cursor: pointer; color: var(--text-primary); }
button.role-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px;
  border-radius: 4px; }
.role-title { font-weight: 700; font-size: 12.5px; text-decoration: underline;
  text-decoration-color: var(--gridline); text-underline-offset: 2px; }
button.role-toggle:hover .role-title { text-decoration-color: var(--accent); color: var(--accent); }
tr.role-row.role-open .pj-caret { transform: rotate(90deg) translateX(1px);
  border-left-color: var(--accent); }
.role-detail-hint { font-size: 10px; color: var(--muted-ink); margin-top: 3px; font-style: italic; }
tr.role-row.role-open .role-detail-hint { visibility: hidden; }
tr.role-detail td { padding-left: 30px !important; }
/* Open-role hours read like the staff cells beside them (Mark, Sep 15 2026): the same
   box, the same bold figure, and a small caption line where a staff cell carries its
   project lines - so the two halves of a practice band line up rather than reading as
   two different tables. The empty-week caption is hidden rather than dropped, or the
   rows would sit at different heights. */
#staff-grid .wk-cell.wk-demand,
#staff-grid .wk-cell.wk-demand-empty,
#staff-grid .wk-cell.wk-demand-total {
  min-width: 78px; padding: 3px 4px 2px; border-radius: 6px;
  font-weight: 700; font-size: 12px; font-variant-numeric: tabular-nums;
}
#staff-grid .wk-cell.wk-demand { box-shadow: inset 3px 0 0 var(--status-warning); }
#staff-grid .wk-cell.wk-demand::after,
#staff-grid .wk-cell.wk-demand-empty::after {
  content: "hrs/wk"; display: block; font-size: 9px; line-height: 1.35;
  font-weight: 400; color: var(--text-secondary);
}
#staff-grid .wk-cell.wk-demand-empty::after { visibility: hidden; }
</style>"""

JS = """<script>
/* Open roles live at the bottom of their practice band; each one opens in place
   (Mark, Sep 15 2026). Detail rows carry [hidden] and data-role-parent. */
(function () {
  var grid = document.getElementById("staff-grid");
  var all = document.getElementById("outlook-expand-roles");
  if (!grid) return;

  function details(id) {
    return grid.querySelectorAll('tr[data-role-parent="' + id + '"]');
  }
  function setOpen(row, open) {
    var id = row.dataset.roleId;
    row.classList.toggle("role-open", open);
    var b = row.querySelector(".role-toggle");
    if (b) b.setAttribute("aria-expanded", open ? "true" : "false");
    Array.prototype.forEach.call(details(id), function (d) { d.hidden = !open; });
  }
  function rows() { return grid.querySelectorAll("tr.role-row"); }

  grid.addEventListener("click", function (ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest(".role-toggle") : null;
    if (!b) return;
    var row = b.closest("tr.role-row");
    if (!row) return;
    setOpen(row, !row.classList.contains("role-open"));
    syncBtn();
  });

  function syncBtn() {
    if (!all) return;
    var rs = rows(), open = 0;
    Array.prototype.forEach.call(rs, function (r) {
      if (r.classList.contains("role-open")) open++;
    });
    var on = rs.length > 0 && open === rs.length;
    all.setAttribute("aria-pressed", on ? "true" : "false");
    all.classList.toggle("outlook-btn-active", on);
    all.textContent = on ? "Collapse all open roles" : "Expand all open roles";
  }

  if (all) {
    all.addEventListener("click", function () {
      var rs = rows(), open = 0;
      Array.prototype.forEach.call(rs, function (r) {
        if (r.classList.contains("role-open")) open++;
      });
      var want = open < rs.length;
      Array.prototype.forEach.call(rs, function (r) { setOpen(r, want); });
      syncBtn();
    });
  }
})();
</script>"""

out = out.replace("\n</style>", CSS, 1)
out = out.replace(TAIL, "</script>\n" + roles_scripts + "\n" + JS + "\n</section>", 1)
assert "outlook-expand-roles" in out and "role-toggle" in out and "geo-off" in out

open(OUT, "w", encoding="utf-8").write(out)
print(f"wrote {OUT}  ({len(out):,} bytes, was {len(src):,})")
