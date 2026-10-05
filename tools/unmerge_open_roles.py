#!/usr/bin/env python3
"""Move the open roles out of the 8 Week Outlook into their own "Open Roles & Recruiting"
section directly below it, and drop the Meeting Log and Action Items panels.

Mark, Oct 5 2026: "move the open roles out from the 8 Week Outlook and the recruiting section
along with all of the Open Roles - No Delivery Practice content. Drop the Meeting Log and the
Action Items section from the dashboard."

Runs as a POST-PROCESSING PASS after merge_open_roles.py (which builds the compact role rows,
their click-to-open detail rows and the no-practice band that this pass relocates):

    python3 merge_open_roles.py   dashboard_artifact.html dashboard_artifact.html
    python3 unmerge_open_roles.py dashboard_artifact.html dashboard_artifact.html

Layout after this pass:
  - #staff-grid holds consultants only; the practice rows lose their "+n open" chips and the
    heading loses its open-role count;
  - a new <section id="open-roles"> ("Open Roles & Recruiting") sits where the Recruiting
    Activity section was, holding the geography filter, the suggestion legend, the
    "Expand all open roles" button and a #roles-table with one band per practice, the
    "no delivery practice" band and the unfilled-demand total row; Recruiting Activity
    follows it as the second half of the same section;
  - the Meeting Log (#meeting-log) and Action Items (#action-items) panels are hidden. Their
    markup and scripts stay so the comment drawers, the agenda and the shared store keep
    working; the Meeting Agenda panel is untouched.
Data-independent: it reads whatever rows the build emitted.
"""
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "dashboard_artifact.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC

src = open(SRC, encoding="utf-8").read()
if 'id="roles-table"' in src and 'id="open-roles"' in src:
    print("already unmerged; nothing to do")
    sys.exit(0)
lines = src.split("\n")

GRID_START = next(i for i, l in enumerate(lines) if 'id="staff-grid"' in l)
GRID_TBODY_END = next(i for i in range(GRID_START, len(lines)) if lines[i].strip() == "</tbody>")
OUTLOOK_SEC_START = max(i for i in range(GRID_START) if lines[i].startswith("<section"))
REC_SEC_START = next(i for i, l in enumerate(lines) if 'section4 recruiting-section' in l)
assert OUTLOOK_SEC_START < GRID_START < GRID_TBODY_END < REC_SEC_START

# ------------------------------------------------------------------ pull role rows out
staff, roles, cur_prac, total_row = [], [], None, None
pending_head = None
n_roles = 0
for l in lines[GRID_START:GRID_TBODY_END]:
    s = l.strip()
    if "outlook-practice-row" in s and "prac-open" not in s:
        cur_prac = re.sub(r"<[^>]+>", "", re.sub(r'<span class="count-chip[^"]*">\+\d+ open</span>', "", l))
        cur_prac = re.sub(r"\s*\d+\s*$", "", cur_prac.replace("&amp;", "&")).strip()
        staff.append(re.sub(r' <span class="count-chip pj-chip-open">\+\d+ open</span>', "", l))
    elif 'class="outlook-practice-row prac-open"' in s:
        roles.append(l)                                   # the no-practice band header
        cur_prac = None
    elif 'class="grid-open-head"' in s:
        if cur_prac:
            n = re.search(r'pj-chip-open">(\d+)</span>', s).group(1)
            peak = re.search(r"&middot; ([\d,]+ hrs/wk at peak)", s)
            roles.append('        <tr class="outlook-practice-row"><td colspan="9">' + cur_prac.replace("&", "&amp;")
                         + f' <span class="count-chip pj-chip-open">{n} open</span>'
                         + (f'<span class="goh-note">{peak.group(1)}</span>' if peak else "")
                         + "</td></tr>")
        else:
            roles.append(l.replace(" &middot; click a role for the recruiting update and comments", ""))
    elif 'class="demand-main role-row"' in s:
        roles.append(l); n_roles += 1
    elif "data-role-parent=" in s:
        roles.append(l)
    elif "demand-total-row" in s:
        total_row = l
    else:
        staff.append(l)
assert total_row and n_roles, (n_roles, bool(total_row))
roles.append(total_row)
print(f"moved {n_roles} open roles out of the outlook")

# ------------------------------------------------------------------ outlook head/controls
head = lines[OUTLOOK_SEC_START + 1]
m = re.search(r"&middot; (\d+) open roles &times; 8 weeks &middot; weeks of ([^<]+)</span>", head)
assert m, head
weeks_label = m.group(2)
lines[OUTLOOK_SEC_START + 1] = head.replace(f"&middot; {m.group(1)} open roles &times; 8 weeks", "&times; 8 weeks")

pre = lines[OUTLOOK_SEC_START:GRID_START]
geo_i = next(i for i, l in enumerate(pre) if 'class="geo-bar"' in l)
legend_i = next((i for i, l in enumerate(pre) if 'class="fits-legend"' in l), None)   # dropped in compact builds
geo_bar = pre[geo_i]
fits_legend = pre[legend_i] if legend_i is not None else ""
pre = [l for i, l in enumerate(pre) if i not in (geo_i, legend_i)]
btn_i = next(i for i, l in enumerate(pre) if 'id="outlook-expand-roles"' in l)
expand_btn = pre.pop(btn_i).strip()
# Mark, Oct 5 2026: no explanatory note line under the Outlook controls
pre = [re.sub(r'<span class="s3-tabs-note">.*?</span>', "", l) if "s3-tabs-note" in l else l for l in pre]
pre = [l for l in pre if l.strip() or True]
assert 'outlook-expand-roles' not in "\n".join(pre)

thead = next(l for l in lines[GRID_START:GRID_TBODY_END] if "<thead>" in l)
thead = thead[thead.index("<thead>"):thead.index("</thead>") + 8].replace("<th>Consultant</th>", "<th>Open role</th>", 1)

# ------------------------------------------------------------------ new section
new_section = [
    '<section class="section4 roles-section" id="open-roles">',
    f'  <h2 class="sec-head">Open Roles &amp; Recruiting <span class="section4-range">{n_roles} open roles '
    f'&times; 8 weeks &middot; weeks of {weeks_label}</span></h2>',
    '      <div class="outlook-controls">',
    f'        {expand_btn}',
    '        <span class="s3-tabs-note">unfilled demand by practice, hours per week &middot; click a role for the '
    'recruiting update, suggestions and comments &middot; requisitions with no scheduled Salesforce demand '
    'sit in the last band</span>',
    '      </div>',
    geo_bar,
] + ([fits_legend] if fits_legend else []) + [
    '      <div class="outlook-scroll"><table class="outlook-table staff-grid" id="roles-table">',
    thead,
    "<tbody>",
] + roles + ["</tbody></table></div>", "</section>", ""]

# the geography-filter / role-comment script and the role-toggle script sit at the tail of the
# outlook section; they must run after the new table exists, so they move into the new section
tail = lines[GRID_TBODY_END:REC_SEC_START]
blocks, cur = [], None
for i, l in enumerate(tail):
    if l.strip() == "<script>":
        cur = [i]
    elif l.strip() == "</script>" and cur:
        cur.append(i); blocks.append(cur); cur = None
moving = [(a, b) for a, b in blocks
          if any(k in "\n".join(tail[a:b + 1]) for k in ("tr[data-geo]", "outlook-expand-roles"))]
assert len(moving) == 2, moving
moved_scripts = []
for a, b in moving:
    moved_scripts.extend(tail[a:b + 1])
drop = {i for a, b in moving for i in range(a, b + 1)}
tail = [l for i, l in enumerate(tail) if i not in drop]
new_section = new_section[:-2] + moved_scripts + new_section[-2:]

out_lines = (lines[:OUTLOOK_SEC_START] + pre + staff + tail + new_section + lines[REC_SEC_START:])
out = "\n".join(out_lines)

# ------------------------------------------------------------------ rewire scripts and css
def swap(old, new, count=1):
    global out
    assert out.count(old) >= 1, old
    out = out.replace(old, new, count)

swap('#staff-grid tr[data-geo]', '#roles-table tr[data-geo]')
swap('#staff-grid tr.demand-main', '#roles-table tr.demand-main')
swap('#staff-grid .wk-demand-total', '#roles-table .wk-demand-total')
swap('    var tbl = $("staff-grid");', '    var tbl = $("roles-table");')
swap('    var rtbl = document.getElementById("staff-grid");', '    var rtbl = document.getElementById("roles-table");')
# the role toggle script: the one that also looks up #outlook-expand-roles
swap('  var grid = document.getElementById("staff-grid");\n  var all = document.getElementById("outlook-expand-roles");',
     '  var grid = document.getElementById("roles-table");\n  var all = document.getElementById("outlook-expand-roles");')
swap('#staff-grid .wk-cell.wk-demand,\n#staff-grid .wk-cell.wk-demand-empty,\n#staff-grid .wk-cell.wk-demand-total {',
     '#roles-table .wk-cell.wk-demand,\n#roles-table .wk-cell.wk-demand-empty,\n#roles-table .wk-cell.wk-demand-total {')
swap('#staff-grid .wk-cell.wk-demand { box-shadow', '#roles-table .wk-cell.wk-demand { box-shadow')
swap('#staff-grid .wk-cell.wk-demand::after,\n#staff-grid .wk-cell.wk-demand-empty::after {',
     '#roles-table .wk-cell.wk-demand::after,\n#roles-table .wk-cell.wk-demand-empty::after {')
swap('#staff-grid .wk-cell.wk-demand-empty::after { visibility: hidden; }',
     '#roles-table .wk-cell.wk-demand-empty::after { visibility: hidden; }')
swap('#staff-grid tr[hidden] { display: none !important; }',
     '#staff-grid tr[hidden], #roles-table tr[hidden] { display: none !important; }')
swap('.outlook-scroll:has(> #staff-grid) { overflow-x: clip; }\n#staff-grid thead th {',
     '.outlook-scroll:has(> #staff-grid), .outlook-scroll:has(> #roles-table) { overflow-x: clip; }\n'
     '#staff-grid thead th, #roles-table thead th {')

CSS = """
/* ---- Oct 5 2026 (Mark): open roles back out of the 8 Week Outlook into their own section;
   Meeting Log and Action Items panels retired (markup kept for the drawers and the store). */
#meeting-log, #action-items { display: none !important; }
#open-roles .outlook-scroll { margin-top: 6px; }
#roles-table tr.outlook-practice-row td .goh-note { text-transform: none; letter-spacing: 0;
  font-weight: 500; font-size: 10.5px; color: var(--muted-ink); margin-left: 8px; }
</style>"""
out = out.replace("\n</style>", CSS, 1)

assert out.count('id="roles-table"') == 1 and out.count('id="staff-grid"') == 1
assert 'role-row' not in "\n".join(staff) and 'demand-total-row' not in "\n".join(staff)
open(OUT, "w", encoding="utf-8").write(out)
print(f"wrote {OUT}  ({len(out):,} bytes, was {len(src):,})")
