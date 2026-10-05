#!/usr/bin/env python3
"""Mark, Oct 5 2026 (late):
  - 8 Week Outlook: no "Expand all projects" button (the per-cell "+n more" stays).
  - Open Roles & Recruiting: hover a week cell for the same tooltip the Outlook gives
    ("Oct 5: <role> (40h)"; empty weeks "Oct 5: no demand").
  - Comment mounts: no "No comments yet - click to add one." placeholder (the Add a comment
    button stays), and the section-level comment mount under the Projects, Roles & Open Demand
    heading is removed (the heading's own comment button still opens that thread).
Idempotent post-processing pass, run after allocate_layer.py:

    python3 open_roles_polish.py dashboard_artifact.html [dashboard_artifact.html]
"""
import re
import sys

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
changed = []

# 1. Outlook: drop the Expand-all button (its script already tolerates a missing button)
s, n = re.subn(r'\s*<div class="outlook-controls">\s*<button type="button" class="outlook-btn" id="outlook-expand-all"[^>]*>[^<]*</button>\s*</div>', "", s, count=1)
if n: changed.append("outlook expand-all removed")

# 2. Open Roles: tooltips on the week cells
i0 = s.index('id="roles-table"'); i1 = s.index("</table>", i0)
tbl = s[i0:i1]
weeks = re.findall(r'<th class="wk">([^<]*)</th>', tbl[:tbl.index("</thead>")])
assert len(weeks) == 8, weeks
def add_tips_safe(m):
    row = m.group(0)
    label = re.sub(r"<[^>]+>", "", re.search(r'<span class="role-title">(.*?)</span>', row, re.S).group(1))
    label = re.sub(r"\s+", " ", label).strip().replace('"', "&quot;")
    idx = [0]
    def cell(mm):
        h = float(mm.group(2)); w = weeks[idx[0]] if idx[0] < 8 else ""; idx[0] += 1
        tip = f'{w}: {label} ({h:g}h/wk)' if h > 0 else f'{w}: no demand'
        return f'{mm.group(1)} data-h="{mm.group(2)}" title="{tip}"'
    return re.sub(r'(<div class="wk-cell wk-demand(?:-empty)?") data-h="([0-9.]+)"(?! title=)', cell, row)
tbl2, n_rows = re.subn(r'<tr data-role-id="or\d+"[^>]*>.*?</tr>', add_tips_safe, tbl, flags=re.S)
n_tips = tbl2.count('title="') - tbl.count('title="')
# total row
def total_tip(m):
    idx = [0]
    def cell(mm):
        w = weeks[idx[0]] if idx[0] < 8 else ""; idx[0] += 1
        return f'{mm.group(1)} data-h="{mm.group(2)}" title="{w}: total unfilled demand ({float(mm.group(2)):g}h/wk)"'
    return re.sub(r'(<div class="wk-cell wk-demand-total") data-h="([0-9.]+)"(?! title=)', cell, m.group(0))
tbl2 = re.sub(r'<tr class="demand-total-row"[^>]*>.*?</tr>', total_tip, tbl2, count=1, flags=re.S)
s = s[:i0] + tbl2 + s[i1:]
if n_tips: changed.append(f"{n_tips} role-cell tooltips on {n_rows} roles")

# 3. comment mounts
old = '''      if (!cs.length) {
        m.appendChild(el("div", "ct-mount-empty",
          S.offline ? OFFLINE : "No comments yet - click to add one."));
      } else {'''
if old in s:
    s = s.replace(old, '''      if (!cs.length) {
        if (S.offline) m.appendChild(el("div", "ct-mount-empty", OFFLINE));
      } else {''', 1)
    changed.append("empty-thread placeholder removed")
s, n = re.subn(r'\s*<div class="ct-mount section-note" data-ct-key="s:projects-roles-open-demand"[^>]*></div>', "", s, count=1)
if n: changed.append("projects section comment mount removed")

CSS = """
/* ---- Oct 5 2026 (Mark): empty comment rows are just the button */
#roles-table tr.comment-row .ct-mount:empty { display: none; }
#roles-table tr.comment-row .ct-open { margin-top: 0; }
</style>"""
if "empty comment rows are just the button" not in s:
    s = s.replace("\n</style>", CSS, 1)

open(OUT, "w", encoding="utf-8").write(s)
print("; ".join(changed) or "nothing to do", f"- wrote {OUT} ({len(s):,} bytes)")
