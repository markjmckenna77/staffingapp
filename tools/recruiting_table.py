#!/usr/bin/env python3
"""Recruiting Activity as one table with stage filters (Mark, Oct 5 2026 - chose layout C).

Post-processing pass, runs LAST in the weekly build (after allocate_layer.py), with the week's
scrubbed ATS JSON:

    python3 recruiting_table.py dashboard_artifact.html ats_YYYY-MM-DD.json [dashboard_artifact.html]

Keeps the section heading and the stat tiles (adds a "waiting on background check" tile) and
replaces the four lists with: filter chips (stage, geography) + one row per requisition
(requisition / candidate, client, stage, interviewing, target start, days open, recruiter, latest
update), background-check rows tinted; then two short lines underneath for scheduled demand with
no requisition and requisitions closed since the previous export (both taken from the lists the
build already rendered, so nothing is recomputed here).

Stage is inferred - the export has no stage column:
  Background check  newest status note mentioning BG/BGV/background and not clearly cleared;
                    "last mentioned <date>" when later notes are silent on it
  Filled / starting the requisition is in the page's Filled list
  Offer / finalist  latest note says offer / moving forward with / plan to hire
  Interviewing      candidates interviewing > 0
  Sourcing          otherwise
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
OFFER = re.compile(r"\boffer\b|moving forward with|plan to hire|verbal accept|accepted", re.I)
STAGES = [("bg", "Background check"), ("filled", "Filled / starting"), ("offer", "Offer / finalist"),
          ("int", "Interviewing"), ("src", "Sourcing")]
GEOS = [("us", "US"), ("india", "India"), ("latam", "LATAM"), ("eu", "EU")]

s = open(SRC, encoding="utf-8").read()
if 'id="rec-table"' in s:
    print("already applied"); sys.exit(0)
reqs = json.load(open(ATS, encoding="utf-8"))
if isinstance(reqs, dict):
    reqs = reqs.get("reqs", [])


def esc(t):
    return str(t if t is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def note_date(note):
    m = re.match(r"\s*(\d{1,2}[/.]\d{1,2})", note or "")
    return m.group(1).replace(".", "/") if m else ""


def geo_of(offices):
    o = (offices or "").lower()
    if "cti" in o or "hyderabad" in o or "india" in o: return "india"
    if "latam" in o: return "latam"
    if "london" in o or "europe" in o or re.search(r"\beu\b", o): return "eu"
    return "us"


# ---- what the build already rendered: the Filled list (names), no-requisition demand, closed reqs
sec0 = s.index('<section class="section4 recruiting-section">'); sec1 = s.index("</section>", sec0)
sec = s[sec0:sec1]
def col(title):
    m = re.search(r'<h3 class="section4-subhead">' + re.escape(title) + r'(?:\s*<span[^>]*>.*?</span>)?</h3>\s*(?:<ul class="rec-list">(.*?)</ul>)?(?:\s*<div class="rec-note">(.*?)</div>)?', sec, re.S)
    return (m.group(1) or "", m.group(2) or "") if m else ("", "")
filled_html, _ = col("Filled")
filled = [(n, [t for t in re.findall(r"[a-z]+", t.lower()) if len(t) > 3])
          for n, t in re.findall(r"<li><b>(.*?)</b> &mdash; (.*?)<", filled_html)]
noreq_html, noreq_note = col("Scheduled demand with no requisition")
closed_html, closed_note = col("Requisitions closed")
noreq = re.findall(r"<li>(.*?)</li>", noreq_html)
closed = re.findall(r"<li>(.*?)</li>", closed_html)


def candidate(r):
    # 1. the candidate's name appears in the requisition title or its status-note log
    text = " ".join([r.get("job", "")] + (r.get("history") or [r.get("update", "")]))
    for name, _ in filled:
        first = name.split(" ")[0]
        if len(first) >= 3 and re.search(r"\b" + re.escape(first) + r"\b", text, re.I):
            return name
    # 2. otherwise nearly every word of the Filled line's title is in the client + job title
    key = set(re.findall(r"[a-z]+", (r.get("client", "") + " " + r.get("job", "")).lower()))
    best, score = "", 0
    for name, toks in filled:
        hit = sum(t in key for t in toks)
        if toks and hit >= max(2, len(toks) - 1) and hit > score:
            best, score = name, hit
    return best


def stage_of(r, who):
    hist = r.get("history") or ([r["update"]] if r.get("update") else [])
    for i, note in enumerate(hist):
        if BG.search(note):
            if CLEARED.search(note) and not PENDING.search(note):
                break
            return "bg", ("" if i == 0 else f"last mentioned {note_date(note)}"), note
    if who:
        return "filled", "", r.get("update", "")
    if OFFER.search(r.get("update", "")):
        return "offer", "", r.get("update", "")
    if (r.get("interviewing") or 0) > 0:
        return "int", "", r.get("update", "")
    return "src", "", r.get("update", "")


rows = []
for r in reqs:
    who = candidate(r)
    k, sub, note = stage_of(r, who)
    rows.append(dict(r, k=k, sub=sub, note=note, who=who, geo=geo_of(r.get("offices"))))
order = {k: i for i, (k, _) in enumerate(STAGES)}
rows.sort(key=lambda r: (order[r["k"]], -(r.get("interviewing") or 0), r.get("days_open") or 0))
counts = {k: sum(r["k"] == k for r in rows) for k, _ in STAGES}
gcounts = {g: sum(r["geo"] == g for r in rows) for g, _ in GEOS}
labels = dict(STAGES)


def tr(r):
    who = f'<div class="rec-who">{esc(r["who"])}</div>' if r["who"] else ""
    stg = f'<span class="rec-stg rec-stg-{r["k"]}">{labels[r["k"]]}</span>' + (f'<div class="rec-sub">{esc(r["sub"])}</div>' if r["sub"] else "")
    start = esc((r.get("start") or "")[:5].rstrip("/"))
    rec = esc((r.get("recruiter") or "").split(" ")[0])
    return (f'<tr data-stage="{r["k"]}" data-geo="{r["geo"]}" class="rec-row{" rec-row-bg" if r["k"] == "bg" else ""}">'
            f'<td class="rec-req"><b>{esc(r["job"])}</b>{who}</td><td>{esc(r.get("client") or "Internal")}</td><td>{stg}</td>'
            f'<td class="num">{r.get("interviewing") or 0}</td><td>{start}</td><td class="num">{esc(r.get("days_open"))}</td>'
            f'<td>{rec}</td><td class="rec-upd">{esc(r["note"])}</td></tr>')


chips = [f'<button type="button" class="rec-chip rec-chip-on" data-stage="all">All <span>{len(rows)}</span></button>']
chips += [f'<button type="button" class="rec-chip" data-stage="{k}">{t} <span>{counts[k]}</span></button>' for k, t in STAGES if counts[k]]
chips.append('<span class="rec-chip-sep"></span>')
chips += [f'<button type="button" class="rec-chip rec-chip-on" data-geo="all">Everywhere</button>']
chips += [f'<button type="button" class="rec-chip" data-geo="{g}">{t} <span>{gcounts[g]}</span></button>' for g, t in GEOS if gcounts[g]]

table = f'''  <div class="rec-filters" id="rec-filters">{"".join(chips)}</div>
  <div class="rec-table-wrap"><table class="rec-table" id="rec-table">
    <thead><tr><th>Requisition</th><th>Client</th><th>Stage</th><th class="num">Interviewing</th><th>Start</th><th class="num">Open</th><th>Recruiter</th><th>Latest update</th></tr></thead>
    <tbody>
{chr(10).join("      " + tr(r) for r in rows)}
      <tr class="rec-empty" hidden><td colspan="8">No requisitions match these filters.</td></tr>
    </tbody>
  </table></div>
  <div class="rec-lines">
    <div class="rec-line"><b>Scheduled demand with no requisition ({len(noreq)})</b> {" &middot; ".join(noreq)}
      <span class="rec-note-inline">{re.sub(r"\\s+", " ", noreq_note).strip()}</span></div>
    <div class="rec-line"><b>Requisitions closed ({len(closed)})</b> {" &middot; ".join(closed) or "none"}
      <span class="rec-note-inline">{re.sub(r"\\s+", " ", closed_note).strip()}</span></div>
  </div>
  <script>
  (function () {{
    var box = document.getElementById("rec-filters"), tbl = document.getElementById("rec-table");
    if (!box || !tbl) return;
    var stage = "all", geo = "all";
    function apply() {{
      var shown = 0;
      Array.prototype.forEach.call(tbl.querySelectorAll("tr.rec-row"), function (tr) {{
        var ok = (stage === "all" || tr.dataset.stage === stage) && (geo === "all" || tr.dataset.geo === geo);
        tr.hidden = !ok; if (ok) shown++;
      }});
      var empty = tbl.querySelector("tr.rec-empty"); if (empty) empty.hidden = shown > 0;
      Array.prototype.forEach.call(box.querySelectorAll(".rec-chip"), function (b) {{
        var on = b.dataset.stage ? b.dataset.stage === stage : b.dataset.geo === geo;
        b.classList.toggle("rec-chip-on", on); b.setAttribute("aria-pressed", on ? "true" : "false");
      }});
    }}
    box.addEventListener("click", function (ev) {{
      var b = ev.target.closest(".rec-chip"); if (!b) return;
      if (b.dataset.stage) stage = b.dataset.stage; else if (b.dataset.geo) geo = b.dataset.geo;
      apply();
    }});
    apply();
  }})();
  </script>
'''

# ---- splice: replace .rec-cols block (and the bg column pass's output if it ran) inside the section
m = re.search(r'  <div class="rec-cols">.*?\n  </div>\n', sec, re.S)
assert m, "rec-cols block not found"
sec = sec[:m.start()] + table + sec[m.end():]
# stat tile for the background-check count (idempotent with the earlier column pass)
if 'rec-stat-bg' not in sec:
    sec = re.sub(r'(<div class="rec-stat"><div class="rec-stat-num">\d+</div><div class="rec-stat-label">roles filled</div></div>)',
                 r'\1' + f'<div class="rec-stat rec-stat-bg"><div class="rec-stat-num">{counts["bg"]}</div><div class="rec-stat-label">waiting on background check</div></div>',
                 sec, count=1)
else:
    sec = re.sub(r'(<div class="rec-stat rec-stat-bg"><div class="rec-stat-num">)\d+', r"\g<1>" + str(counts["bg"]), sec, count=1)
sec = sec.replace('<span class="section4-range">ATS export as of', '<span class="section4-range">every requisition on one line &middot; ATS export as of', 1)
sec = sec.replace("Interviewing counts are candidates currently in interviews per requisition.",
                  "Stage is read from the recruiter&#39;s status notes (the export has no stage column): the newest note that mentions "
                  "a background check decides that stage, and &quot;last mentioned&quot; means later notes are silent on it &mdash; confirm "
                  "in the meeting. Interviewing counts are candidates currently in interviews per requisition.", 1)
s = s[:sec0] + sec + s[sec1:]

CSS = """
/* ---- Oct 5 2026 (Mark): Recruiting Activity as one table with stage filters */
.rec-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 10px; }
.rec-chip { font: 600 11px/1.6 inherit; font-family: inherit; color: var(--text-secondary); background: var(--surface-1);
  border: 1px solid var(--gridline); border-radius: 999px; padding: 1px 10px; cursor: pointer; }
.rec-chip span { font-weight: 500; color: var(--muted-ink); margin-left: 3px; }
.rec-chip:hover { border-color: var(--accent); color: var(--accent); }
.rec-chip-on, .rec-chip-on:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
.rec-chip-on span { color: rgba(255,255,255,0.8); }
.rec-chip-sep { width: 1px; height: 18px; background: var(--gridline); margin: 0 6px; }
.rec-table-wrap { overflow-x: auto; }
.rec-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.rec-table th { text-align: left; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink);
  padding: 6px 8px; border-bottom: 1px solid var(--gridline); white-space: nowrap; }
.rec-table td { padding: 7px 8px; border-bottom: 1px solid var(--gridline); vertical-align: top; color: var(--text-primary); }
.rec-table th.num, .rec-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.rec-table tr[hidden] { display: none; }
.rec-table tr.rec-row-bg td { background: color-mix(in srgb, var(--status-warning) 9%, transparent); }
.rec-table .rec-req { min-width: 200px; }
.rec-table .rec-who { font-size: 10.5px; color: var(--muted-ink); }
.rec-table .rec-upd { min-width: 260px; color: var(--text-secondary); }
.rec-table .rec-sub { font-size: 10px; color: var(--muted-ink); }
.rec-stg { font-weight: 700; white-space: nowrap; }
.rec-stg-bg { color: var(--status-warning); }
.rec-stg-filled { color: var(--status-good); }
.rec-stg-offer { color: var(--accent); }
.rec-table tr.rec-empty td { color: var(--muted-ink); font-style: italic; text-align: center; }
.rec-lines { margin-top: 12px; display: grid; gap: 6px; font-size: 11.5px; }
.rec-line b { margin-right: 6px; }
.rec-note-inline { display: block; font-size: 10.5px; color: var(--muted-ink); font-style: italic; }
.rec-stat-bg .rec-stat-num { color: var(--status-warning); }
</style>"""
s = s.replace("\n</style>", CSS, 1)

open(OUT, "w", encoding="utf-8").write(s)
print(f"recruiting table: {len(rows)} requisitions - " + ", ".join(f"{labels[k]} {counts[k]}" for k, _ in STAGES if counts[k])
      + f"; {len(noreq)} no-requisition lines, {len(closed)} closed; wrote {OUT} ({len(s):,} bytes)")
