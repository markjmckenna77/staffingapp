#!/usr/bin/env python3
"""Final pass of the weekly rebuild (added Sep 21 2026).

The generators and the post-processing passes each append their own CSS to whatever
stylesheet they find, and the project's dashboard_style.css was a 214-byte stub until
Sep 21, so a fresh build ends up with a patchwork <style>. This pass:

  1. replaces the page's first <style> block with dashboard_style.css - the complete,
     de-duplicated stylesheet recovered from the live Version 39 page (it already
     contains the app-layer, merged-roles, Sep 15 compaction and utilization rules);
  2. asserts exactly one Utilization by Practice section and one copy of its script
     (running build_utilization_section.py twice leaves an orphan whose duplicate click
     handler toggles every practice open and shut again);
  3. writes the artifact fragment and a standalone dashboard.html for delivery.

    python3 finalize_page.py dashboard_artifact.html
"""
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "dashboard_artifact.html"
CSS = open("dashboard_style.css", encoding="utf-8").read()

s = open(SRC, encoding="utf-8").read()

# 1. stylesheet
blocks = list(re.finditer(r"<style[^>]*>(.*?)</style>", s, re.S))
assert blocks, "no <style> block"
b = blocks[0]
s = s[:b.start()] + "<style>" + CSS + "</style>" + s[b.end():]

# 2. utilization section / script must be single
util_tag = '<section class="section4 util-section"'
util_js = re.compile(r'\n?<script>\n\(function \(\) \{\n  var table = document\.getElementById\("util-table"\);.*?\n\}\)\(\);\n</script>', re.S)
assert s.count(util_tag) == 1, f"{s.count(util_tag)} utilization sections"
js = list(util_js.finditer(s))
if len(js) > 1:
    end = s.find("</section>", s.find(util_tag)) + len("</section>")
    keep = min(js, key=lambda m: abs(m.start() - end))
    for m in sorted((x for x in js if x is not keep), key=lambda m: -m.start()):
        s = s[:m.start()] + s[m.end():]
    print(f"removed {len(js) - 1} orphaned utilization script(s)")
assert len(util_js.findall(s)) == 1, "utilization script count"
# stray CSS text outside any <style> (symptom of the pre-Sep-21 util pass on a stub stylesheet)
assert "/* ================= Utilization by Practice (YTD)" not in re.sub(r"<style[^>]*>.*?</style>", "", s, flags=re.S), "stray CSS outside <style>"

open(SRC, "w", encoding="utf-8").write(s)

# 3. standalone document
k = s.find("</style>") + len("</style>")
doc = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
       + s[:k] + "\n</head>\n<body>\n" + s[k:] + "\n</body>\n</html>\n")
open("dashboard.html", "w", encoding="utf-8").write(doc)
print(f"wrote {SRC} ({len(s):,} bytes) and dashboard.html ({len(doc):,} bytes)")
