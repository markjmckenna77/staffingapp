#!/usr/bin/env python3
"""Open Roles & Recruiting restyle (Mark, Oct 21 2026).

Runs after recruiting_roles_format.py and before hide_open_roles.py:

    python3 open_roles_restyle.py dashboard_artifact.html

  1. Each role's title row gets a light-blue band (accent at 11%), so a role reads as a card
     header: title band, then the recruiting update, then the suggestions.
  2. The "Staffing Suggestions and Allocations" line under the update stays (closed by default,
     as before) - an earlier version of this pass folded it into the title; Mark asked for the
     line back the same day.
  3. The recruiting-update callout loses its yellow fill: a neutral grey surface with a
     slate left rule, so the week cells (still amber = unfilled demand) are the only yellow
     in the section.
"""
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "dashboard_artifact.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if "Oct 21 2026 (Mark): Open Roles - blue title bands" in s:
    print("already applied"); sys.exit(0)

i0 = s.index('<section class="section4 roles-section" id="open-roles">')
i1 = s.index("</section>", i0)
sec = s[i0:i1]

# Oct 21 2026 (later that day): the "Staffing Suggestions and Allocations" line stays - Mark only wanted the
# suggestions closed by default, which they already are - so the title is left as plain text and the
# role-more rows are kept. The blue band and the grey update callout are the whole change.
n_title = len(re.findall(r'<tr data-role-id="or\d+"[^>]*class="demand-main role-row"', sec))
n_more = len(re.findall(r'<tr class="role-more"', sec))
if 'class="role-toggle role-head-toggle"' in sec:
    raise SystemExit("page carries the title-toggle variant; rebuild from the generators")
s = s[:i0] + sec + s[i1:]

CSS = """
/* ---- Oct 21 2026 (Mark): Open Roles - blue title bands, grey update callout */
#roles-table tr.role-row td { background: color-mix(in srgb, var(--accent) 11%, transparent); border-bottom: none; }
#roles-table tr.role-row td.col-demand-name { padding: 7px 8px 7px 10px !important; }
#roles-table tr.role-row .demand-role { font-weight: 700; }
#roles-table tr.role-update td { padding-top: 6px !important; }
#roles-table .demand-update { background: color-mix(in srgb, var(--text-primary) 4.5%, transparent);
  border-left: 3px solid color-mix(in srgb, var(--text-secondary) 55%, transparent); }
#roles-table .demand-update b { color: var(--text-primary); }
#roles-table .demand-skills { border-top-color: color-mix(in srgb, var(--text-secondary) 35%, transparent); }
</style>"""
s = s.replace("\n</style>", CSS, 1)

open(OUT, "w", encoding="utf-8").write(s)
print(f"open roles restyle: {n_title} title bands, {n_more} suggestion lines kept; wrote {OUT} ({len(s):,} bytes)")
