#!/usr/bin/env python3
"""Open Roles layout, Mark Oct 5 2026:
  "Drop expand all open roles. Don't show the practice headers. Reformat the table so it shows
   the title of the role as it does now, then the recruiting update right under it. Then nestle
   the staffing suggestions on a 3rd line underneath it, but I have to click on that content to
   appear."

Post-processing pass that runs AFTER unmerge_open_roles.py:

    python3 flatten_open_roles.py dashboard_artifact.html dashboard_artifact.html

Per role in #roles-table:
  row 1  title (plain, no toggle) + the week hours cells, as before
  row 2  Recruiting Update - always visible (a "no requisition open in the ATS" line when the
         role has no ATS match, so every role reads the same way)
  row 3  "Staffing suggestions & comments" - a toggle; the suggestion and comment rows stay
         hidden under it until clicked
No practice band rows, no "Open roles - no delivery practice" header (those requisitions simply
come last, titled "Internal: ..." / "<client>: ..."), no Expand-all button. The total row stays.
"""
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "dashboard_artifact.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if 'class="role-more"' in s:
    print("already flattened"); sys.exit(0)

start = s.index('id="roles-table"')
tb0 = s.index("<tbody>", start) + len("<tbody>")
tb1 = s.index("</tbody>", tb0)
body = s[tb0:tb1]
rows = re.findall(r"[ \t]*<tr[^>]*>.*?</tr>", body, re.S)
assert "".join(r.strip() for r in rows) == re.sub(r"\s+(?=<tr)|\s+$", "", body).replace("\n", "") or True

out, n_roles, n_synth = [], 0, 0
roles = {}            # id -> {"main":..., "update":..., "rest":[...], "geo":...}
order = []
total_row = None
for r in rows:
    if "outlook-practice-row" in r or 'class="grid-open-head"' in r:
        continue                                   # no headers of any kind
    if "demand-total-row" in r:
        total_row = r; continue
    m = re.search(r'data-role-id="(or\d+)"', r)
    if m:
        rid = m.group(1); order.append(rid)
        geo = re.search(r'data-geo="([^"]*)"', r)
        roles[rid] = {"main": r, "update": None, "rest": [], "geo": geo.group(1) if geo else ""}
        continue
    m = re.search(r'data-role-parent="(or\d+)"', r)
    if m:
        rid = m.group(1)
        if "demand-update" in r and roles[rid]["update"] is None:
            roles[rid]["update"] = r
        else:
            roles[rid]["rest"].append(r)
        continue
    out.append(r)                                  # anything else (should be nothing)
assert total_row and roles, (bool(total_row), len(roles))

def plain_title(main):
    # <button class="role-toggle" ...><span class="pj-caret"></span><span class="role-title">X</span></button> -> <span class="role-title">X</span>
    main = re.sub(r'<button type="button" class="role-toggle"[^>]*><span class="pj-caret"></span>(<span class="role-title">.*?</span>)</button>',
                  r"\1", main, count=1, flags=re.S)
    main = re.sub(r'<div class="role-detail-hint"[^>]*>.*?</div>', "", main, count=1, flags=re.S)
    return main

for rid in order:
    ro = roles[rid]
    out.append(plain_title(ro["main"]))
    upd = ro["update"]
    if upd:
        upd = upd.replace(" hidden", "", 1).replace(f' data-role-parent="{rid}"', "", 1)
        upd = upd.replace('class="role-detail demand-sub', 'class="role-update demand-sub', 1)
    else:
        n_synth += 1
        upd = (f'        <tr class="role-update demand-sub" data-geo="{ro["geo"]}"><td colspan="9">'
               '<div class="demand-update demand-update-none"><b>Recruiting Update:</b> no requisition open in the ATS '
               'for this role.</div></td></tr>')
    out.append(upd)
    if ro["rest"]:
        kinds = []
        if any("fits-row" in x for x in ro["rest"]): kinds.append("staffing suggestions")
        if any("comment-row" in x for x in ro["rest"]): kinds.append("comments")
        label = " &amp; ".join(kinds) if kinds else "details"
        label = label[0].upper() + label[1:]
        out.append(f'        <tr class="role-more" data-role-more="{rid}" data-geo="{ro["geo"]}"><td colspan="9">'
                   f'<button type="button" class="role-toggle" aria-expanded="false" data-role="{rid}">'
                   f'<span class="pj-caret"></span>{label}</button></td></tr>')
        out.extend(ro["rest"])
    n_roles += 1
out.append(total_row)

s = s[:tb0] + "\n" + "\n".join(x.rstrip("\n") for x in out) + "\n" + s[tb1:]

# ---- controls: no expand-all, new note
s = re.sub(r'\s*<button type="button" class="outlook-btn" id="outlook-expand-roles"[^>]*>[^<]*</button>', "", s, count=1)
# Mark, Oct 5 2026: no note line and no geography filter in Open Roles & Recruiting
i0 = s.index('<section class="section4 roles-section" id="open-roles">'); i1 = s.index("</section>", i0)
sec = s[i0:i1]
sec = re.sub(r'\s*<span class="s3-tabs-note">.*?</span>', "", sec, count=1, flags=re.S)
sec = re.sub(r'\s*<div class="geo-bar">.*?</div>\n', "\n", sec, count=1, flags=re.S)
s = s[:i0] + sec + s[i1:]
assert 'class="geo-bar"' not in s[i0:s.index("</section>", i0)]
assert 'id="outlook-expand-roles"' not in s

# ---- toggle script: replace the band-era one (it keyed off tr.role-row and the expand-all button)
i0 = s.index("/* Open roles live at the bottom of their practice band")
i0 = s.rfind("<script>", 0, i0); i1 = s.index("</script>", i0) + len("</script>")
JS = """<script>
/* Open roles (Mark, Oct 5 2026): title, recruiting update, then a "Staffing suggestions &
   comments" line that opens the suggestion and comment rows in place. */
(function () {
  var tbl = document.getElementById("roles-table");
  if (!tbl) return;
  tbl.addEventListener("click", function (ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest(".role-toggle") : null;
    if (!b) return;
    var id = b.dataset.role, open = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", open ? "true" : "false");
    var more = b.closest("tr"); if (more) more.classList.toggle("role-open", open);
    var main = tbl.querySelector('tr[data-role-id="' + id + '"]'); if (main) main.classList.toggle("role-open", open);
    Array.prototype.forEach.call(tbl.querySelectorAll('tr[data-role-parent="' + id + '"]'), function (d) { d.hidden = !open; });
  });
})();
</script>"""
s = s[:i0] + JS + s[i1:]

CSS = """
/* ---- Oct 5 2026 (Mark): flat open-roles list - title / recruiting update / click-to-open line */
#roles-table tr.role-row td { border-bottom: none; }
#roles-table tr.role-row td.col-demand-name { padding-left: 8px !important; }
#roles-table tr.role-update td { padding: 0 8px 4px 22px !important; border-bottom: none; }
#roles-table tr.role-update .demand-update { margin: 0; }
#roles-table .demand-update-none { color: var(--muted-ink); font-style: italic; }
#roles-table .demand-skills { margin-top: 3px; padding-top: 3px; border-top: 1px dashed color-mix(in srgb, var(--status-warning) 45%, transparent); }
#roles-table tr.role-more td { padding: 0 8px 8px 22px !important; border-bottom: 1px solid var(--gridline); }
#roles-table tr.role-more button.role-toggle { display: inline-flex; align-items: center; gap: 6px; width: auto;
  font-size: 11.5px; font-weight: 600; color: var(--accent); }
#roles-table tr.role-more.role-open .pj-caret { transform: rotate(90deg) translateX(1px); border-left-color: var(--accent); }
#roles-table tr.role-detail td { padding-left: 30px !important; }
#roles-table tr.role-detail.comment-row td { border-bottom: 1px solid var(--gridline); padding-bottom: 8px !important; }
#roles-table .role-title { text-decoration: none; }
</style>"""
s = s.replace("\n</style>", CSS, 1)

open(OUT, "w", encoding="utf-8").write(s)
print(f"flattened {n_roles} roles ({n_synth} with no ATS requisition); wrote {OUT} ({len(s):,} bytes)")
