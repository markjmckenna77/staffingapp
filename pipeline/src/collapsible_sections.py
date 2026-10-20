#!/usr/bin/env python3
"""Every section collapses and expands (Mark, Oct 5 2026): click a section heading to fold the
section to its heading; click again to open it. The state is remembered per browser (localStorage)
so a viewer's layout survives the weekly refresh. The heading's comment button still works.
Idempotent post-processing pass, run last:

    python3 collapsible_sections.py dashboard_artifact.html [dashboard_artifact.html]
"""
import sys

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if "sec-collapsed" in s:
    print("already applied"); sys.exit(0)

JS = """
<script>
/* Collapsible sections (Mark, Oct 5 2026). A heading click folds its section; the heading's own
   buttons (comments) are left alone. Remembered per browser under "ct-sec-collapsed". */
(function () {
  var KEY = "ct-sec-collapsed";
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { return {}; } }
  function save(st) { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} }
  function idOf(h) {
    var t = "";
    Array.prototype.forEach.call(h.childNodes, function (n) { if (n.nodeType === 3) t += n.textContent; });
    return t.replace(/\\s+/g, " ").trim().toLowerCase();
  }
  var state = load();
  Array.prototype.forEach.call(document.querySelectorAll("h2.sec-head"), function (h) {
    var box = h.parentNode; if (!box) return;
    var id = idOf(h); if (!id) return;
    h.classList.add("sec-toggle");
    h.setAttribute("role", "button"); h.setAttribute("tabindex", "0");
    var caret = document.createElement("span"); caret.className = "sec-caret"; caret.setAttribute("aria-hidden", "true");
    h.insertBefore(caret, h.firstChild);
    function set(collapsed, persist) {
      box.classList.toggle("sec-collapsed", collapsed);
      h.setAttribute("aria-expanded", collapsed ? "false" : "true");
      if (persist) { if (collapsed) state[id] = 1; else delete state[id]; save(state); }
    }
    set(!!state[id], false);
    h.addEventListener("click", function (ev) {
      if (ev.target && ev.target.closest && ev.target.closest("button, a, input, select, textarea")) return;
      set(!box.classList.contains("sec-collapsed"), true);
    });
    h.addEventListener("keydown", function (ev) {
      if (ev.target !== h) return;
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); set(!box.classList.contains("sec-collapsed"), true); }
    });
  });
})();
</script>"""

CSS = """
/* ---- Oct 5 2026 (Mark): click a section heading to collapse / expand it */
h2.sec-head.sec-toggle { cursor: pointer; user-select: none; }
h2.sec-head.sec-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.sec-caret { display: inline-block; width: 0; height: 0; margin-right: 9px; vertical-align: 2px;
  border-top: 5px solid transparent; border-bottom: 5px solid transparent; border-left: 6px solid currentColor;
  transform: rotate(90deg); transition: transform 0.12s ease; opacity: 0.75; }
.sec-collapsed > h2.sec-head .sec-caret { transform: rotate(0deg); }
.sec-collapsed > :not(h2.sec-head) { display: none !important; }
.sec-collapsed > h2.sec-head { margin-bottom: -18px !important; border-radius: 9px !important; }
.agenda-panel.sec-collapsed > h2.sec-head { margin-bottom: -14px !important; }
</style>"""

# the script goes right before the footer so every heading exists when it runs
anchor = '<footer class="dash-footer">'
assert anchor in s, "footer anchor not found"
s = s.replace(anchor, JS + "\n\n" + anchor, 1)
s = s.replace("\n</style>", CSS, 1)
open(OUT, "w", encoding="utf-8").write(s)
print(f"collapsible sections applied; wrote {OUT} ({len(s):,} bytes)")
