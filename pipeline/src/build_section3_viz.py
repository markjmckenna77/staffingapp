#!/usr/bin/env python3
"""Graphical renderer for Section 3 (August Allocation vs. Actual Hours).

Two horizontal bar charts per view (Mark, Aug 28 final): UNDER-billed hours (who
billed less than allocated, red) and OVER-billed hours (blue), one row per entity,
sorted by hours, bar length on a shared per-chart scale, stacked vertically
(under-billed above over-billed). The By Client Account /
By Consultant views remain tabs. Data shapes match staffing_data.py:
S3_ACCOUNTS = [(name, people, alloc, actual)],
S3_CONSULTANTS = [(name, practice, [(project, alloc, actual)])].
"""
import html


def e(s):
    return html.escape(str(s), quote=True)


PAIRS = None          # set by charts_block: [(consultant, practice, account, alloc, actual)]


def _detail(kind, name):
    """The drill-down under a row (Mark, Oct 20 2026): for an account, every consultant allocated
    to or billing it in the 4 weeks and who did not bill what they were allocated; for a
    consultant, every account they were allocated to or billed and which they did not bill to."""
    if not PAIRS:
        return ""
    if kind == "acct":
        rows = [(n, a, b) for n, _p, cu, a, b in PAIRS if cu == name]
        head = ("Consultant", "Who did not bill what they were allocated on this account")
    else:
        rows = [(cu, a, b) for n, _p, cu, a, b in PAIRS if n == name]
        head = ("Account", "Accounts this consultant did not bill to as allocated")
    if not rows:
        return ""
    rows.sort(key=lambda t: (t[2] - t[1], t[0]))
    lines = []
    for label, a, b in rows:
        d = b - a
        if a > 0 and b <= 0.05:
            cls, tag = "ubd-none", "did not bill"
        elif d < -0.05:
            cls, tag = "ubd-under", f"under by {-d:,.1f}"
        elif d > 0.05:
            cls, tag = "ubd-over", f"over by {d:,.1f}"
        else:
            cls, tag = "ubd-even", "as allocated"
        if a <= 0.05 and b > 0.05:
            tag = "billed with no allocation"
        lines.append(f'<div class="ubd-row {cls}"><span class="ubd-name">{e(label)}</span>'
                     f'<span class="ubd-num">{a:,.1f}</span><span class="ubd-num">{b:,.1f}</span>'
                     f'<span class="ubd-num ubd-delta">{d:+,.1f}</span><span class="ubd-tag">{tag}</span></div>')
    n_miss = sum(1 for _l, a, b in rows if a > 0 and b < a - 0.05)
    return (f'<div class="ub-detail" hidden><div class="ubd-head"><span class="ubd-name">{head[0]}</span>'
            f'<span class="ubd-num">Alloc</span><span class="ubd-num">Actual</span><span class="ubd-num">&Delta;</span>'
            f'<span class="ubd-tag">{head[1]} &middot; {n_miss} of {len(rows)} short</span></div>'
            + "".join(lines) + "</div>")


def _bar_list(items, cls, kind):
    """items = [(label, value, tooltip)] positive, sorted desc. Each row opens its drill-down."""
    mx = max(v for _, v, _ in items) or 1.0
    rows = []
    for name, v, tip in items:
        w = max(v / mx * 100.0, 0.8)
        det = _detail(kind, name)
        btn = ('<button type="button" class="ub-open" aria-expanded="false" title="Show the breakdown">'
               '<span class="pj-caret"></span></button>') if det else '<span class="ub-open-none"></span>'
        rows.append(f'        <div class="ub-row{" ub-has-detail" if det else ""}" title="{e(tip)}">{btn}'
                    f'<span class="ub-name">{e(name)}</span>'
                    f'<div class="ub-track"><div class="ub-bar {cls}" style="width:{w:.1f}%"></div></div>'
                    f'<span class="ub-val">{v:,.1f}</span></div>' + det)
    return "\n".join(rows)


def _pair(deltas, tips=None, kind="acct"):
    """deltas = [(label, delta_hrs)]; renders under-billed and over-billed bar charts."""
    tips = tips or {}

    def block(items, title_cls, bar_cls, word):
        total = sum(v for _, v in items)
        title_html = f'        <div class="pie-title {title_cls}">{word} &middot; {total:,.1f} hrs</div>'
        if not items:
            return f'      <div class="pie-block">\n{title_html}\n<div class="pie-none">Nothing in this category.</div></div>'
        entries = [(n, v, tips.get(n) or f"{n}: {v:,.1f} hrs ({v / total * 100:.0f}% of {word.lower()} hours)")
                   for n, v in sorted(items, key=lambda t: -t[1])]
        return (f'      <div class="pie-block">\n{title_html}\n        <div class="ub-chart">\n'
                + _bar_list(entries, bar_cls, kind) + "\n        </div>\n      </div>")

    under = [(n, -d) for n, d in deltas if d < -0.05]
    over = [(n, d) for n, d in deltas if d > 0.05]
    left = block(under, "pie-title-under", "ub-under", "Under-billed")
    right = block(over, "pie-title-over", "ub-over", "Over-billed")
    return f'      <div class="pie-pair">\n{left}\n{right}\n      </div>'


def account_chart(accounts):
    return _pair([(name, actual - alloc) for name, _people, alloc, actual in accounts], kind="acct")


def consultant_chart(consultants):
    deltas, tips = [], {}
    for name, _practice, projects in consultants:
        alloc = sum(p[1] for p in projects)
        actual = sum(p[2] for p in projects)
        deltas.append((name, actual - alloc))
        tips[name] = "; ".join(f"{proj}: {a:,.1f} alloc / {b:,.1f} billed ({b - a:+,.1f})"
                               for proj, a, b in sorted(projects, key=lambda p: -abs(p[2] - p[1])))
    return _pair(deltas, tips, kind="cons")


def charts_block(accounts, consultants, pairs=None):
    global PAIRS
    PAIRS = pairs
    return f"""      <div class="s3-tabs" role="tablist">
        <button type="button" class="s3-tab s3-tab-active" data-pane="s3-pane-acct">By Client Account</button>
        <button type="button" class="s3-tab" data-pane="s3-pane-cons">By Consultant</button>
        <span class="s3-tabs-note">bar length = hours of variance vs. allocation &middot; click a row (or the &#9656;) to open it: an account shows who did not bill what they were allocated, a consultant shows the accounts they did not bill to</span>
      </div>
      <div id="s3-pane-acct" class="s3-pane">
{account_chart(accounts)}
      </div>
      <div id="s3-pane-cons" class="s3-pane" hidden>
{consultant_chart(consultants)}
      </div>
<script>
(function () {{
  var tabs = document.querySelectorAll(".s3-tab");
  function show(id) {{
    document.getElementById("s3-pane-acct").hidden = id !== "s3-pane-acct";
    document.getElementById("s3-pane-cons").hidden = id !== "s3-pane-cons";
    tabs.forEach(function (t) {{ t.classList.toggle("s3-tab-active", t.dataset.pane === id); }});
  }}
  tabs.forEach(function (t) {{ t.addEventListener("click", function () {{ show(t.dataset.pane); }}); }});
  /* drill-downs (Mark, Oct 20 2026): a row opens the breakdown beneath it */
  document.querySelectorAll(".section3 .ub-row.ub-has-detail").forEach(function (row) {{
    row.addEventListener("click", function (ev) {{
      var hit = ev.target.closest ? ev.target.closest("button, a, textarea, input") : null;
      if (hit && !hit.classList.contains("ub-open")) return;
      var det = row.nextElementSibling;
      if (!det || !det.classList.contains("ub-detail")) return;
      var open = det.hidden;
      det.hidden = !open;
      row.classList.toggle("ub-row-open", open);
      var b = row.querySelector(".ub-open"); if (b) b.setAttribute("aria-expanded", open ? "true" : "false");
    }});
  }});
}})();
</script>"""


CSS = """
/* ---------- Section 3 variance charts ---------- */
.s3-pane[hidden] { display: none !important; }
.s3-tabs { display: flex; align-items: center; gap: 6px; margin: 0 0 12px; flex-wrap: wrap; }
.s3-tab { border: 1px solid var(--border); background: var(--surface-page); color: var(--text-secondary); font: inherit; font-size: 12.5px; font-weight: 600; border-radius: 7px; padding: 6px 14px; cursor: pointer; }
.s3-tab:hover { color: var(--text-primary); }
.s3-tab-active { background: var(--accent); border-color: var(--accent); color: #fff; }
.s3-tab-active:hover { color: #fff; }
.s3-tabs-note { font-size: 11px; color: var(--muted-ink); margin-left: 10px; }
.pie-pair { display: block; }
.pie-block { margin-bottom: 20px; }
.pie-block:last-child { margin-bottom: 0; }
.pie-title { font-size: 13px; font-weight: 700; margin: 0 0 8px; }
.pie-title-under { color: var(--diverge-under); }
.pie-title-over { color: var(--diverge-over); }
.pie-none { font-size: 12px; color: var(--muted-ink); font-style: italic; }
.ub-row { display: grid; grid-template-columns: 16px 200px 1fr 58px; gap: 10px; align-items: center; padding: 2.5px 0; border-bottom: 1px solid var(--gridline); }
.ub-row.ub-has-detail { cursor: pointer; }
.ub-row.ub-has-detail:hover .ub-name { color: var(--accent); }
.ub-open { background: none; border: 0; padding: 0; margin: 0; width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; color: var(--muted-ink); }
.ub-open .pj-caret { display: inline-block; width: 0; height: 0; border-top: 4.5px solid transparent; border-bottom: 4.5px solid transparent; border-left: 5.5px solid currentColor; transition: transform 0.12s ease; }
.ub-row-open .ub-open .pj-caret { transform: rotate(90deg); }
.ub-detail { margin: 2px 0 8px 26px; padding: 4px 10px 6px; border-left: 2px solid var(--border); font-size: 11.5px; }
.ubd-head, .ubd-row { display: grid; grid-template-columns: minmax(160px, 1.3fr) 60px 60px 60px 1fr; gap: 10px; align-items: center; padding: 2px 0; }
.ubd-head { color: var(--muted-ink); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.03em; border-bottom: 1px solid var(--gridline); margin-bottom: 2px; }
.ubd-head .ubd-tag { text-transform: none; letter-spacing: 0; }
.ubd-num { text-align: right; font-variant-numeric: tabular-nums; }
.ubd-row .ubd-delta { font-weight: 700; }
.ubd-tag { color: var(--muted-ink); }
.ubd-none .ubd-name, .ubd-none .ubd-delta, .ubd-none .ubd-tag { color: var(--diverge-under); font-weight: 700; }
.ubd-under .ubd-delta, .ubd-under .ubd-tag { color: var(--diverge-under); }
.ubd-over .ubd-delta, .ubd-over .ubd-tag { color: var(--diverge-over); }
@media (max-width: 760px) { .ubd-head, .ubd-row { grid-template-columns: 1.3fr 50px 50px 50px; } .ubd-tag { grid-column: 1 / -1; } }
.ub-row:last-child { border-bottom: none; }
.ub-name { font-size: 11.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ub-track { position: relative; height: 13px; background: var(--surface-page); border-radius: 3px; }
.ub-bar { position: absolute; left: 0; top: 1px; bottom: 1px; border-radius: 3px; }
.ub-under { background: var(--diverge-under); opacity: 0.85; }
.ub-over { background: var(--diverge-over); opacity: 0.85; }
.ub-val { font-size: 11.5px; font-weight: 700; text-align: right; font-variant-numeric: tabular-nums; color: var(--text-secondary); }
@media (max-width: 760px) { .ub-row { grid-template-columns: 14px 130px 1fr 52px; } }
"""
