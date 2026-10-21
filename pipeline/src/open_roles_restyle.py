#!/usr/bin/env python3
"""Open Roles & Recruiting restyle (Mark, Oct 21 2026).

Runs after recruiting_roles_format.py and before hide_open_roles.py:

    python3 open_roles_restyle.py dashboard_artifact.html

  1. Each role's title row gets a light-blue band (accent at 11%), so a role reads as a card
     header: title band, then the recruiting update, then the suggestions.
  2. The title itself is the click target for the staffing suggestions: the separate
     "Staffing Suggestions and Allocations" line is gone, the title carries the caret and a
     small "suggestions & allocations" hint that disappears once the role is open. The
     suggestion rows stay hidden until the title is clicked (the Oct 5 toggle script keys
     off .role-toggle[data-role], which the title button now is).
  3. The recruiting-update callout loses its yellow fill: a neutral grey surface with a
     slate left rule, so the week cells (still amber = unfilled demand) are the only yellow
     in the section.
"""
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "dashboard_artifact.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if 'class="role-toggle role-head-toggle"' in s:
    print("already applied"); sys.exit(0)

i0 = s.index('<section class="section4 roles-section" id="open-roles">')
i1 = s.index("</section>", i0)
sec = s[i0:i1]

# 1+2. the title becomes the toggle (for roles that have a suggestions line); the role-more line goes
with_more = set(re.findall(r'<tr class="role-more" data-role-more="(or\d+)"', sec))
n_title = 0
def title_btn(m):
    global n_title
    rid = m.group(1)
    if rid not in with_more:
        return m.group(0)
    n_title += 1
    return (f'{m.group(0)[:m.start(2) - m.start(0)]}'
            f'<button type="button" class="role-toggle role-head-toggle" aria-expanded="false" data-role="{rid}">'
            f'<span class="pj-caret"></span><span class="role-text">{m.group(2)}'
            f'<span class="role-hint">suggestions &amp; allocations</span></span></button>')
sec = re.sub(r'<tr data-role-id="(or\d+)"[^>]*class="demand-main role-row"[^>]*><td class="col-demand-name"><div class="demand-role">'
             r'(<span class="role-title">.*?</span>)', title_btn, sec, flags=re.S)
n_more = len(re.findall(r'\s*<tr class="role-more"[^>]*>.*?</tr>', sec, flags=re.S))
sec = re.sub(r'\s*<tr class="role-more"[^>]*>.*?</tr>', "", sec, flags=re.S)
assert n_title and n_title == n_more, (n_title, n_more)

s = s[:i0] + sec + s[i1:]

CSS = """
/* ---- Oct 21 2026 (Mark): Open Roles - blue title bands, title opens the suggestions, grey update callout */
#roles-table tr.role-row td { background: color-mix(in srgb, var(--accent) 11%, transparent); border-bottom: none; }
#roles-table tr.role-row td.col-demand-name { padding: 7px 8px 7px 10px !important; }
#roles-table tr.role-row .demand-role { font-weight: 700; }
#roles-table button.role-toggle.role-head-toggle { display: inline-flex; align-items: flex-start; gap: 7px; width: auto;
  background: none; border: 0; padding: 0; margin: 0; font: inherit; color: inherit; cursor: pointer; text-align: left; }
#roles-table button.role-toggle.role-head-toggle .pj-caret { flex: none; margin-top: 4px; }
#roles-table button.role-toggle.role-head-toggle .role-text { display: flex; flex-direction: column; gap: 1px; }
#roles-table button.role-toggle.role-head-toggle .role-title { text-decoration: none; }
#roles-table button.role-toggle.role-head-toggle:hover .role-title { color: var(--accent); }
#roles-table button.role-toggle.role-head-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
#roles-table .role-hint { font-size: 10.5px; font-weight: 500; color: var(--muted-ink); }
#roles-table tr.role-row.role-open .role-hint { visibility: hidden; }
#roles-table tr.role-row.role-open .pj-caret { transform: rotate(90deg) translateX(1px); border-left-color: var(--accent); }
#roles-table tr.role-update td { padding-top: 6px !important; }
#roles-table .demand-update { background: color-mix(in srgb, var(--text-primary) 4.5%, transparent);
  border-left: 3px solid color-mix(in srgb, var(--text-secondary) 55%, transparent); }
#roles-table .demand-update b { color: var(--text-primary); }
#roles-table .demand-skills { border-top-color: color-mix(in srgb, var(--text-secondary) 35%, transparent); }
#roles-table tr.role-detail:last-of-type td { border-bottom: 1px solid var(--gridline); }
#roles-table tr.role-update td { border-bottom: 1px solid var(--gridline); }
#roles-table tr.role-detail td { border-bottom: 1px solid var(--gridline); }
</style>"""
s = s.replace("\n</style>", CSS, 1)

open(OUT, "w", encoding="utf-8").write(s)
print(f"open roles restyle: {n_title} title bands, {n_more} suggestion lines folded into the titles; wrote {OUT} ({len(s):,} bytes)")
