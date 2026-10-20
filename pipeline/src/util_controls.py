#!/usr/bin/env python3
"""Utilization by Practice: drop the "Expand all practices" button and the note line
("click a practice to see utilization by consultant · monthly value is ... · Oct includes scheduled
weeks through month end"). Mark, Oct 5 2026. Idempotent post-processing pass (run after
allocate_layer.py):

    python3 util_controls.py dashboard_artifact.html [dashboard_artifact.html]
"""
import re
import sys

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if 'id="util-expand-all"' not in s:
    print("already applied"); sys.exit(0)

s, n = re.subn(r'\s*<div class="outlook-controls">\s*<button type="button" class="outlook-btn" id="util-expand-all"[^>]*>[^<]*</button>'
               r'\s*<span class="s3-tabs-note">.*?</span>\s*</div>', "", s, count=1, flags=re.S)
assert n == 1, "util controls block not found"

# the section's script keeps a handle on the button; make it tolerate the button's absence
old1 = '    btn.textContent = allOpen ? "Collapse all practices" : "Expand all practices";'
old2 = '  btn.addEventListener("click", function () {\n    var open = btn.getAttribute("aria-pressed") !== "true";'
assert old1 in s and old2 in s, "util script anchors moved"
s = s.replace(old1, "    if (!btn) return;\n" + old1, 1)
s = s.replace(old2, old2.replace("  btn.addEventListener", "  if (btn) btn.addEventListener"), 1)
assert 'id="util-expand-all"' not in s

open(OUT, "w", encoding="utf-8").write(s)
print(f"util controls removed; wrote {OUT} ({len(s):,} bytes)")
