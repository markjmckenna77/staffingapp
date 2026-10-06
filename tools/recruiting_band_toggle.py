#!/usr/bin/env python3
"""Recruiting Activity: every band collapses (Mark, Oct 6 2026). Click a band heading (Filled,
Waiting on background check, Opened in the last two weeks, Scheduled demand with no requisition,
Requisitions closed) to fold its roles away; click again to open it. Remembered per browser
(localStorage "ct-rec-band-collapsed") like the section headings. Also tones the section down
(Mark, Oct 6 2026: "too much yellow"): bands and Recruiting Update boxes go neutral with a blue
accent; yellow is kept only as the thin edge on week cells with demand and the "waiting" tag.
Idempotent pass, runs after
recruiting_roles_format.py:

    python3 recruiting_band_toggle.py dashboard.html [dashboard.html]
"""
import re
import sys

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if "rec-band-toggle" in s:
    print("already applied"); sys.exit(0)
assert 'id="rec-table"' in s, "run recruiting_roles_format.py first"

# a caret at the front of every band, and the band row becomes a keyboard-reachable button
n = 0
def band(m):
    global n; n += 1
    return (f'<tr class="grid-open-head rec-band rec-band-toggle" role="button" tabindex="0" aria-expanded="true">'
            f'<td colspan="{m.group(1)}"><span class="pj-caret"></span>')
s = re.sub(r'<tr class="grid-open-head rec-band"><td colspan="(\d+)">', band, s)

JS = """
<script>
/* Recruiting Activity bands collapse (Mark, Oct 6 2026): a band heading hides or shows the rows
   under it, up to the next band. Remembered per browser under "ct-rec-band-collapsed". */
(function () {
  var tbl = document.getElementById("rec-table");
  if (!tbl) return;
  var KEY = "ct-rec-band-collapsed";
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { return {}; } }
  function save(st) { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} }
  function idOf(b) {
    var t = "";
    Array.prototype.forEach.call(b.cells[0].childNodes, function (n) { if (n.nodeType === 3) t += n.textContent; });
    return t.replace(/\\s+/g, " ").trim().toLowerCase();
  }
  function rowsOf(b) {
    var out = [], r = b.nextElementSibling;
    while (r && !r.classList.contains("rec-band")) { out.push(r); r = r.nextElementSibling; }
    return out;
  }
  function set(b, open) {
    b.classList.toggle("rec-band-closed", !open);
    b.setAttribute("aria-expanded", open ? "true" : "false");
    rowsOf(b).forEach(function (r) { r.hidden = !open; });
  }
  var state = load();
  var bands = tbl.querySelectorAll("tr.rec-band-toggle");
  Array.prototype.forEach.call(bands, function (b) {
    if (state[idOf(b)]) set(b, false);
    function flip() {
      var open = b.classList.contains("rec-band-closed");
      set(b, open);
      var st = load(); if (open) delete st[idOf(b)]; else st[idOf(b)] = 1; save(st);
    }
    b.addEventListener("click", flip);
    b.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); flip(); }
    });
  });
})();
</script>"""
j = s.index("</table></div>", s.index('id="rec-table"')) + len("</table></div>")
s = s[:j] + JS + s[j:]

CSS = """
/* ---- Recruiting Activity bands collapse (Mark, Oct 6 2026) */
#rec-table tr.rec-band-toggle { cursor: pointer; user-select: none; }
#rec-table tr.rec-band-toggle:hover td { background: color-mix(in srgb, var(--accent) 12%, var(--surface-1)); }
#rec-table tr.rec-band-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
#rec-table tr.rec-band-toggle .pj-caret { transform: rotate(90deg) translateX(1px); border-left-color: var(--accent); margin-right: 8px; }
#rec-table tr.rec-band-toggle.rec-band-closed .pj-caret { transform: none; border-left-color: var(--muted-ink); }
/* less yellow: neutral bands and update boxes, blue accent */
#rec-table tr.grid-open-head td { background: color-mix(in srgb, var(--accent) 7%, var(--surface-1));
  border-top: 1px solid color-mix(in srgb, var(--accent) 30%, transparent); color: var(--text-secondary); }
#rec-table tr.grid-open-head .count-chip { background: color-mix(in srgb, var(--accent) 16%, var(--surface-1)); color: var(--text-primary); }
#rec-table .demand-update { background: var(--surface-page); border-left: 3px solid color-mix(in srgb, var(--accent) 55%, transparent); }
#rec-table .demand-update b { color: var(--accent); }
#rec-table .demand-skills { border-top: 1px dashed var(--gridline); }
#rec-table .demand-skills b { color: var(--text-secondary); }
#rec-table .wk-cell.wk-demand { background: color-mix(in srgb, var(--muted-ink) 10%, transparent); }
</style>"""
s = s.replace("\n</style>", CSS, 1)
open(OUT, "w", encoding="utf-8").write(s)
print(f"{n} recruiting bands made collapsible; wrote {OUT} ({len(s):,} bytes)")
