#!/usr/bin/env python3
"""Recruiting Activity: a "Waiting on background check" list (Mark, Oct 5 2026; layout A chosen over a
table, later that night) + live refresh from Greenhouse via /api/recruiting when the app has a key.

Post-processing pass, runs after allocate_layer.py:

    python3 recruiting_bgcheck.py dashboard_artifact.html ats_YYYY-MM-DD.json [dashboard_artifact.html]

The ATS export has no stage column, so the status is read from the requisition's status-note
log (newest first): the newest note that mentions a background check decides. "pending",
"still", "waiting", "in progress", "not cleared" -> waiting; "cleared", "passed", "came back
clean", "complete" without a pending word -> cleared (not listed). A requisition whose newest
note is silent on the check but had an older "waiting" note is listed with "last mentioned
<date>" so the room can confirm rather than assume. CANDIDATE names come from the Filled column
of the page when the requisition is there, else from NAMES below, else the job title.
"""
import json
import re
import sys

SRC = sys.argv[1]
ATS = sys.argv[2]
OUT = sys.argv[3] if len(sys.argv) > 3 else SRC

BG = re.compile(r"\b(bg|bgv|bgc|background)\b", re.I)
PENDING = re.compile(r"pending|still|waiting|in progress|not (?:yet )?clear|outstanding|awaiting|delay|manual processing", re.I)
CLEARED = re.compile(r"\bclear(?:ed)?\b|\bpassed\b|came back|\bcompleted\b|\bdone\b|\bfinished\b", re.I)
NAMES = {}   # job title -> candidate name, when the page's Filled column does not carry it

s = open(SRC, encoding="utf-8").read()
if 'class="rec-col rec-col-bg"' in s:
    print("already applied"); sys.exit(0)
reqs = json.load(open(ATS, encoding="utf-8"))
if isinstance(reqs, dict):
    reqs = reqs.get("reqs", [])


def esc(t):
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def note_date(note):
    m = re.match(r"\s*(\d{1,2}[/.]\d{1,2})", note or "")
    return m.group(1).replace(".", "/") if m else ""


def bg_status(r):
    """-> (state, note, date) with state in {"waiting", "stale", "cleared", None}."""
    hist = r.get("history") or ([r["update"]] if r.get("update") else [])
    for i, note in enumerate(hist):              # newest first
        if not BG.search(note):
            continue
        pend, clr = PENDING.search(note), CLEARED.search(note)
        if clr and not pend:
            return "cleared", note, note_date(note)
        return ("waiting" if i == 0 else "stale"), note, note_date(note)
    return None, "", ""


# candidate names from the page's Filled column: <li><b>Sai</b> &mdash; New Leaders: Full Stack AI Engineer (contract)
filled = []   # (name, [title words])
m = re.search(r'<h3 class="section4-subhead">Filled</h3>\s*<ul class="rec-list">(.*?)</ul>', s, re.S)
if m:
    for name, title in re.findall(r"<li><b>(.*?)</b> &mdash; (.*?)<", m.group(1)):
        filled.append((name, [t for t in re.findall(r"[a-z]+", title.lower()) if len(t) > 3]))


def candidate(r):
    text = " ".join([r.get("job", "")] + (r.get("history") or [r.get("update", "")]))
    for name, _ in filled:
        first = name.split(" ")[0]
        if len(first) >= 3 and re.search(r"\b" + re.escape(first) + r"\b", text, re.I):
            return name
    key = set(re.findall(r"[a-z]+", (r.get("client", "") + " " + r.get("job", "")).lower()))
    best, score = "", 0
    for name, toks in filled:
        hit = sum(t in key for t in toks)
        if toks and hit >= max(2, len(toks) - 1) and hit > score:
            best, score = name, hit
    return best or NAMES.get(r.get("job", ""), "")


items, n_wait, n_stale = [], 0, 0
for r in reqs:
    state, note, date = bg_status(r)
    if state not in ("waiting", "stale"):
        continue
    who = candidate(r)
    label = (f"<b>{esc(who)}</b> &mdash; " if who else "") + esc(r.get("job", ""))
    start = f" &middot; target start {esc(r['start'])}" if r.get("start") else ""
    tag = ('<span class="bg-tag bg-tag-wait">waiting</span>' if state == "waiting"
           else f'<span class="bg-tag bg-tag-stale">last mentioned {esc(date)}</span>')
    sub = esc(note) + start + (f" &middot; {esc(r['recruiter'])}" if r.get("recruiter") else "")
    items.append(f"<li>{label} {tag}<div class=\"rec-item-sub\">{sub}</div></li>")
    n_wait += state == "waiting"; n_stale += state == "stale"

body = ("<ul class=\"rec-list\" id=\"rec-bg-list\">" + "".join(items) + "</ul>") if items else \
       '<div class="rec-note" id="rec-bg-list">No requisition is waiting on a background check in this export.</div>'
col = f'''    <div class="rec-col rec-col-bg">
      <h3 class="section4-subhead">Waiting on background check <span class="count-chip">{len(items)}</span></h3>
      {body}
      <div class="rec-note">Read from the recruiter&#39;s status notes (the export has no stage column): the newest note that
      mentions the check decides. &quot;Last mentioned&quot; means later notes are silent on it &mdash; confirm in the meeting.</div>
    </div>
'''
anchor = '    <div class="rec-col">\n      <h3 class="section4-subhead">Opened in the last two weeks</h3>'
assert anchor in s, "Opened-in-the-last-two-weeks column not found"
s = s.replace(anchor, col + anchor, 1)

# a stat tile beside the existing four
tile = (f'<div class="rec-stat rec-stat-bg"><div class="rec-stat-num">{len(items)}</div>'
        f'<div class="rec-stat-label">waiting on background check</div></div>')
s = re.sub(r'(<div class="rec-stat"><div class="rec-stat-num">\d+</div><div class="rec-stat-label">roles filled</div></div>)',
           r"\1" + tile, s, count=1)

CSS = """
/* ---- Oct 5 2026 (Mark): Waiting on background check */
.rec-col-bg .section4-subhead .count-chip { margin-left: 6px; vertical-align: 1px; }
.bg-tag { display: inline-block; margin-left: 6px; padding: 0 7px; border-radius: 999px; font-size: 10px; font-weight: 700;
  line-height: 16px; vertical-align: 1px; text-transform: uppercase; letter-spacing: 0.03em; }
.bg-tag-wait { background: color-mix(in srgb, var(--status-warning) 18%, transparent); color: var(--status-warning);
  border: 1px solid color-mix(in srgb, var(--status-warning) 50%, transparent); }
.bg-tag-stale { background: color-mix(in srgb, var(--muted-ink) 14%, transparent); color: var(--muted-ink);
  border: 1px solid color-mix(in srgb, var(--muted-ink) 40%, transparent); text-transform: none; letter-spacing: 0; }
.rec-stat-bg .rec-stat-num { color: var(--status-warning); }
</style>"""
s = s.replace("\n</style>", CSS, 1)

# ---- live refresh from Greenhouse (GET /api/recruiting; silently keeps the export data when absent)
LIVE_JS = """
<script>
/* Recruiting Activity, live from Greenhouse (Mark, Oct 5 2026). The build writes this section from
   the weekly export; when the app can reach Greenhouse, /api/recruiting answers with the same shape
   and the tiles, the background-check list and the "opened in the last two weeks" list re-render. */
(function () {
  var sec = document.querySelector("section.recruiting-section");
  if (!sec || typeof fetch !== "function") return;
  var BG = /\\b(bg|bgv|bgc|background)\\b/i;
  var PEND = /pending|still|waiting|in progress|not (?:yet )?clear|outstanding|awaiting|delay|manual processing/i;
  var CLR = /\\bclear(?:ed)?\\b|\\bpassed\\b|came back|\\bcompleted\\b|\\bdone\\b|\\bfinished\\b/i;
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[c]; }); }
  function noteDate(n) { var m = /^\\s*(\\d{1,2}[\\/.]\\d{1,2})/.exec(n || ""); return m ? m[1].replace(".", "/") : ""; }
  function bgStatus(r) {
    var hist = (r.history && r.history.length) ? r.history : (r.update ? [r.update] : []);
    for (var i = 0; i < hist.length; i++) {
      var n = hist[i]; if (!BG.test(n)) continue;
      if (CLR.test(n) && !PEND.test(n)) return null;
      return { state: i === 0 ? "waiting" : "stale", note: n, date: noteDate(n) };
    }
    return null;
  }
  var filled = [];
  Array.prototype.forEach.call(sec.querySelectorAll(".rec-col .rec-list li b"), function (b) {
    var h = b.parentNode.parentNode.previousElementSibling;
    if (h && /^Filled/.test(h.textContent)) filled.push(b.textContent.trim());
  });
  function who(r) {
    var text = [r.job].concat(r.history || [r.update || ""]).join(" ");
    for (var i = 0; i < filled.length; i++) {
      var first = filled[i].split(" ")[0];
      if (first.length >= 3 && new RegExp("\\\\b" + first.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&") + "\\\\b", "i").test(text)) return filled[i];
    }
    return "";
  }
  function setTile(label, n) {
    Array.prototype.forEach.call(sec.querySelectorAll(".rec-stat"), function (t) {
      var l = t.querySelector(".rec-stat-label"), v = t.querySelector(".rec-stat-num");
      if (l && v && l.textContent.trim().indexOf(label) === 0) v.textContent = String(n);
    });
  }
  fetch("/api/recruiting", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
    if (!j || !j.reqs || !j.reqs.length) return;
    var reqs = j.reqs, items = [], nWait = 0, totalInt = 0, oldest = 0, now = Date.now();
    var opened = [];
    reqs.forEach(function (r) {
      totalInt += r.interviewing || 0; oldest = Math.max(oldest, r.days_open || 0);
      if (r.opened && (now - Date.parse(r.opened)) <= 14 * 86400000) opened.push(r.job);
      var st = bgStatus(r); if (!st) return;
      var w = who(r); if (st.state === "waiting") nWait++;
      items.push("<li>" + (w ? "<b>" + esc(w) + "</b> &mdash; " : "") + esc(r.job) + " " +
        (st.state === "waiting" ? '<span class="bg-tag bg-tag-wait">waiting</span>' : '<span class="bg-tag bg-tag-stale">last mentioned ' + esc(st.date) + "</span>") +
        '<div class="rec-item-sub">' + esc(st.note) + (r.start ? " &middot; target start " + esc(r.start) : "") + (r.recruiter ? " &middot; " + esc(r.recruiter) : "") + "</div></li>");
    });
    var list = document.getElementById("rec-bg-list");
    if (list) {
      var ul = document.createElement(items.length ? "ul" : "div");
      ul.id = "rec-bg-list"; ul.className = items.length ? "rec-list" : "rec-note";
      ul.innerHTML = items.length ? items.join("") : "No requisition is waiting on a background check in Greenhouse.";
      list.parentNode.replaceChild(ul, list);
      var chip = sec.querySelector(".rec-col-bg .count-chip"); if (chip) chip.textContent = String(items.length);
    }
    Array.prototype.forEach.call(sec.querySelectorAll(".rec-col"), function (c) {
      var h = c.querySelector(".section4-subhead"), u = c.querySelector(".rec-list");
      if (h && u && /^Opened in the last two weeks/.test(h.textContent)) u.innerHTML = opened.length ? opened.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") : "<li>none</li>";
    });
    setTile("open requisitions", reqs.length); setTile("candidates interviewing", totalInt);
    setTile("waiting on background check", items.length); setTile("days open", oldest);
    var range = sec.querySelector(".sec-head .section4-range");
    if (range) range.innerHTML = "live from Greenhouse &middot; as of " + esc((j.cachedAt || j.asOf || "").slice(0, 16).replace("T", " ")) + " UTC";
  }).catch(function () {});
})();
</script>"""
j = s.rfind("</section>", 0, s.index('class="section4 projects-section"'))
s = s[:j] + LIVE_JS + "\n" + s[j:]

open(OUT, "w", encoding="utf-8").write(s)
print(f"background-check column: {len(items)} listed ({n_wait} waiting, {n_stale} last-mentioned); wrote {OUT} ({len(s):,} bytes)")
