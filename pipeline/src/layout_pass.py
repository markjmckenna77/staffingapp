#!/usr/bin/env python3
"""Layout pass for the weekly rebuild (extracted Sep 21 2026 from the Sep 15 cleanup passes).

Re-applies, on a freshly generated page, the layout decisions Mark made on Sep 15 2026 that
have not yet been folded into the generators:
  - Meeting Log as a single dropdown, moved to the very top (above the agenda)
  - monthly-utilization panel label dropped; org-wide utilization and under-target on one line
  - suggestion-scoring legend dropped; project/stage/recruiter chips off the open-role rows
  - projects-section note dropped; Recruiting Activity compacted; interviewing pills off the
    role rows; no comment box under Capacity vs. Need
Data-independent: nothing here touches numbers.

    python3 layout_pass.py dashboard_artifact.html dashboard_artifact.html
"""
import re
import sys

SRC, OUT = sys.argv[1], sys.argv[2]
src = open(SRC, encoding="utf-8").read()
log = []


def sub1(pattern, repl, label, flags=0, count=1):
    global src
    new, n = re.subn(pattern, repl, src, count=count, flags=flags)
    assert n == count, f"{label}: expected {count} match, got {n}"
    src = new
    log.append(f"  {label}")


# ============================================================ 2. Meeting Log
# The tab row becomes a dropdown. The buttons stay in the DOM (hidden) so the app
# layer's counters and click handling are untouched; the select drives them.
sub1(r'<div class="mlog-tabs" id="mlog-tabs">',
     '<select class="mlog-select mlog-view" id="mlog-view" aria-label="Meeting log view">'
     '<option value="actions">Open actions</option>'
     '<option value="allocs">Proposed allocations</option>'
     '<option value="disc">Needs discussion</option>'
     '<option value="recent">Comments</option>'
     '<option value="changed">What changed</option>'
     '<option value="agenda">Meeting agendas</option></select>'
     '<div class="mlog-tabs" id="mlog-tabs" hidden>',
     "meeting log: tabs replaced by a dropdown")

MLOG_JS = """<script>
/* Meeting Log as a single dropdown (Mark, Sep 15 2026). The original tab buttons
   stay in the DOM but hidden: the select clicks them, so the app layer's counters
   and pane rendering are untouched. Option labels mirror the live counts. */
(function () {
  var sel = document.getElementById("mlog-view");
  var tabs = document.getElementById("mlog-tabs");
  if (!sel || !tabs) return;
  function btn(v) { return tabs.querySelector('.mlog-tab[data-pane="' + v + '"]'); }
  sel.addEventListener("change", function () {
    var b = btn(sel.value);
    if (b) b.click();
  });
  var base = {};
  Array.prototype.forEach.call(sel.options, function (o) { base[o.value] = o.textContent; });
  function sync() {
    Array.prototype.forEach.call(sel.options, function (o) {
      var b = btn(o.value);
      var n = b ? b.querySelector(".n") : null;
      var c = n ? n.textContent.trim() : "";
      o.textContent = base[o.value] + (c ? " (" + c + ")" : "");
    });
  }
  sync();
  setInterval(sync, 1500);
})();
</script>"""

# ...and the whole panel moves above the agenda
m = re.search(r'<section class="mlog" id="meeting-log">.*?</section>\n', src, re.S)
assert m, "meeting log section not found"
mlog = m.group(0)
src = src.replace(mlog, "", 1)
sub1(r'<section class="agenda-panel">', mlog.rstrip("\n") + '\n\n<section class="agenda-panel">',
     "meeting log moved above the agenda")

# ============================================================ 3-4. Summary band
sub1(r'  <div class="panel-label">Monthly utilization.*?</div>\n', "",
     "dropped the monthly-utilization panel label", re.S)

sub1(r'<section class="headline-band">\s*<span class="headline-label">Org-wide utilization</span>\s*'
     r'(<span class="headline-figs">.*?</span>)\s*</section>\s*'
     r'<section class="headline-band under-target-band">\s*'
     r'<span class="headline-label">Consultants under target utilization</span>\s*'
     r'(<span class="headline-figs">.*?</span>)\s*</section>',
     lambda m: ('<section class="headline-band headline-band-merged">'
                '<span class="headline-label">Org-wide utilization</span>' + m.group(1)
                + '<span class="headline-div"></span>'
                + '<span class="headline-label">Under target</span>' + m.group(2)
                + '</section>'),
     "headline bands merged onto one line", re.S)

# ============================================================ 5. fits legend
sub1(r'  <div class="s3-tabs-note fits-legend">.*?</div>\n', "", "dropped the suggestion legend", re.S)

# ============================================================ 6. role-row chips
n_proj = len(re.findall(r'(<tr[^>]*class="demand-main role-row".*?)<div class="demand-proj">', src, re.S))
src = re.sub(r'(<tr[^>]*class="demand-main role-row"(?:(?!</tr>).)*?)'
             r'<div class="demand-proj">((?:(?!</div>).)*)</div>'
             r'(?:<div class="chip-row">(?:(?!</div></td>).)*</div>)?',
             lambda m: m.group(1), src, flags=re.S)
log.append(f"  dropped the project/stage/recruiter block from {n_proj} open-role rows")

# ============================================================ 7-8. notes + compaction
sub1(r'<span class="s3-tabs-note">every client rolls up its projects.*?</span>\n', "",
     "dropped the projects-section note", re.S)

sub1(r'<div class="rec-note rec-note-bottom">.*?</div>',
     '<div class="rec-note rec-note-bottom">Interviewing counts are candidates currently in '
     'interviews per requisition. A requisition is listed as closed when it was in the previous '
     'export and is absent from this one. Compensation fields are never carried into this page.</div>',
     "recruiting activity: note shortened", re.S)

CSS = """
/* ---- Sep 15 2026 compaction pass ---------------------------------------- */
.headline-band-merged { padding: 8px 18px; gap: 8px; font-size: 14px; }
.headline-band-merged .headline-figs { font-size: 14px; }
.headline-div { display: inline-block; width: 1px; height: 13px; background: var(--gridline);
  margin: 0 6px; vertical-align: -1px; }
.summary-panel { padding: 14px 20px 6px; }
.mlog { padding: 10px 16px 12px; }
.mlog-view { font-weight: 600; }
.rec-stats { gap: 8px; margin: 0 0 10px; }
.rec-stat { flex: 1 1 110px; padding: 6px 10px; }
.rec-stat-num { font-size: 19px; }
.rec-stat-label { font-size: 10.5px; }
.recruiting-section .section4-subhead { margin: 6px 0 4px; font-size: 11px; }
.recruiting-section .rec-list { font-size: 11.5px; padding-left: 16px; }
.recruiting-section .rec-list li { margin-bottom: 2px; }
.recruiting-section .rec-cols { gap: 18px; }
.recruiting-section .rec-note { font-size: 10.5px; margin-top: 4px; }
.recruiting-section { padding-bottom: 14px; }
tr.role-row td.col-demand-name { padding-top: 5px !important; padding-bottom: 5px !important; }
</style>"""
src = src.replace("\n</style>", CSS, 1)
src = src.replace("</script>\n</section>\n\n\n<section class=\"section4 projects-section\">",
                  "</script>\n</section>\n\n\n<section class=\"section4 projects-section\">", 1)
src = (src.replace("</body></html>", MLOG_JS + "\n</body></html>", 1) if "</body></html>" in src else src.rstrip("\n") + "\n" + MLOG_JS + "\n")
assert "mlog-view" in src


# ---- 1. the interviewing pill on every open-role row
pills = len(re.findall(r'<span class="interviewing-pill[^"]*">\d+ interviewing</span>', src))
src = re.sub(r'\s*<span class="interviewing-pill[^"]*">\d+ interviewing</span>', "", src)

# ...and the count trailing the role name in the comment-thread labels
labels = len(re.findall(r'(data-ct-label="[^"]*?|aria-label="Comments for [^"]*?) \d+ interviewing"', src))
src = re.sub(r'(data-ct-label="[^"]*?|aria-label="Comments for [^"]*?) \d+ interviewing"',
             r'\1"', src)

# ---- 2. the shared comment box under Capacity vs. Need
m = re.search(r'\n  <div class="ct-mount section-note" data-ct-key="s:capacity-vs-need".*?</div>', src, re.S)
assert m, "capacity comment mount not found"
src = src.replace(m.group(0), "", 1)


open(OUT, "w", encoding="utf-8").write(src)
print("\n".join(log))
print(f"removed {pills} interviewing pills, {labels} counts from thread labels, and the Capacity vs. Need comment box")
print(f"wrote {OUT} ({len(src):,} bytes)")
