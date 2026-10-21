#!/usr/bin/env python3
"""Consultant modal (Mark, Oct 21 2026).

    python3 consultant_modal.py dashboard_artifact.html

Clicking a name in the 8 Week Outlook opens a modal for that consultant with three parts:

  1. Week by week - the next 8 weeks as the Outlook shows them, one row per project, hours per
     week editable. "Apply" sends each changed row to POST /api/allocate {kind: "reshape"}: only
     the weeks that differ from NetSuite are rewritten (trimmed, then re-created as runs).
  2. Allocations in NetSuite - every Resource Allocation of theirs that has not ended, fetched
     live (GET /api/allocate?consultant=...), with start, end and hrs/wk editable and a Remove
     button; Save -> {kind: "update"} (an end before the start, or 0 hrs, deletes the record).
     This is where a date change beyond the 8-week window is made.
  3. Assign - to an open role (the roles on the page, hours and weeks prefilled from its
     demand; fills the generic allocation in NetSuite) or to any other project.

Everything is written through the existing /api/allocate route, approvers only; when NetSuite is
not configured or the viewer is not an approver the modal still shows the grid but the buttons
are off and say why. Needs window.__ctCtx from allocate_layer.py (ROLES, GRID, weekISO, ...).
"""
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "dashboard_artifact.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if 'id="cm-modal"' in s:
    print("already applied"); sys.exit(0)

CSS = """
/* ---- Oct 21 2026 (Mark): consultant modal, opened from the 8 Week Outlook names */
#staff-grid td.grid-name { cursor: pointer; }
#staff-grid td.grid-name:hover { color: var(--accent); text-decoration: underline; text-decoration-style: dotted; }
#staff-grid td.grid-name .cm-tag { display: inline-block; margin-left: 6px; padding: 0 5px; border-radius: 8px; font-size: 9.5px; font-weight: 600;
  background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent); vertical-align: 1px; text-decoration: none; }
#cm-scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.38); z-index: 60; }
#cm-modal { position: fixed; top: 4vh; left: 50%; transform: translateX(-50%); width: min(1080px, 96vw); max-height: 92vh; overflow: auto;
  background: var(--surface-1); color: var(--text-primary); border: 1px solid var(--gridline); border-radius: 12px; box-shadow: 0 18px 50px rgba(0,0,0,0.3);
  z-index: 61; font-size: 12.5px; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
#cm-modal[hidden], #cm-scrim[hidden] { display: none; }
.cm-head { display: flex; align-items: baseline; gap: 12px; padding: 14px 18px 10px; border-bottom: 1px solid var(--gridline); position: sticky; top: 0; background: var(--surface-1); z-index: 2; }
.cm-head h3 { margin: 0; font-size: 17px; font-weight: 700; }
.cm-head .cm-sub { color: var(--text-secondary); font-size: 12px; }
.cm-close { margin-left: auto; background: none; border: 0; font-size: 20px; line-height: 1; cursor: pointer; color: var(--text-secondary); }
.cm-close:hover { color: var(--accent); }
.cm-body { padding: 6px 18px 18px; }
.cm-sec { margin-top: 14px; }
.cm-sec h4 { margin: 0 0 6px; font-size: 11.5px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-secondary); }
.cm-sec .cm-why { font-size: 11.5px; color: var(--text-secondary); margin: 0 0 8px; }
.cm-grid { width: 100%; border-collapse: collapse; }
.cm-grid th, .cm-grid td { padding: 4px 6px; border-bottom: 1px solid var(--gridline); text-align: center; font-variant-numeric: tabular-nums; }
.cm-grid th { font-size: 10.5px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.03em; }
.cm-grid td:first-child, .cm-grid th:first-child { text-align: left; }
.cm-grid td.cm-proj { font-weight: 600; max-width: 300px; }
.cm-grid input[type=number] { width: 54px; padding: 3px 4px; text-align: right; border: 1px solid var(--gridline); border-radius: 5px; background: var(--surface-page); color: var(--text-primary); font: inherit; }
.cm-grid input[type=date] { padding: 3px 4px; border: 1px solid var(--gridline); border-radius: 5px; background: var(--surface-page); color: var(--text-primary); font: inherit; font-size: 11.5px; }
.cm-grid input.cm-changed { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
.cm-grid tr.cm-total td { font-weight: 700; border-bottom: none; }
.cm-grid .cm-pct { color: var(--text-secondary); font-size: 10.5px; }
.cm-row-actions { white-space: nowrap; }
.cm-btn { padding: 5px 11px; border-radius: 6px; border: 1px solid var(--gridline); background: var(--surface-page); color: var(--text-primary); font: inherit; font-size: 12px; cursor: pointer; }
.cm-btn:hover { border-color: var(--accent); color: var(--accent); }
.cm-btn.cm-primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
.cm-btn.cm-primary:hover { color: #fff; filter: brightness(1.08); }
.cm-btn.cm-danger:hover { border-color: var(--status-critical); color: var(--status-critical); }
.cm-btn[disabled] { opacity: 0.5; cursor: default; }
.cm-btn.cm-sm { padding: 2px 8px; font-size: 11px; }
.cm-actions { display: flex; align-items: center; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
.cm-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 8px 12px; align-items: end; }
.cm-form label { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--text-secondary); }
.cm-form input, .cm-form select { padding: 5px 6px; border: 1px solid var(--gridline); border-radius: 6px; background: var(--surface-page); color: var(--text-primary); font: inherit; font-size: 12px; }
.cm-form .cm-wide { grid-column: 1 / -1; }
.cm-status { margin-top: 8px; font-size: 12px; color: var(--text-secondary); min-height: 1.2em; }
.cm-status.cm-err { color: var(--status-critical); }
.cm-status.cm-ok { color: var(--status-good); }
.cm-log { margin: 6px 0 0; padding-left: 18px; font-size: 11.5px; color: var(--text-secondary); }
.cm-note { font-size: 11.5px; color: var(--muted-ink); font-style: italic; }
.cm-muted { color: var(--muted-ink); }
</style>"""
assert "\n</style>" in s
s = s.replace("\n</style>", CSS, 1)

HTML_JS = r"""
<div id="cm-scrim" hidden></div>
<div id="cm-modal" hidden role="dialog" aria-modal="true" aria-labelledby="cm-title">
  <div class="cm-head"><h3 id="cm-title"></h3><span class="cm-sub" id="cm-sub"></span><button type="button" class="cm-close" id="cm-close" aria-label="Close">&times;</button></div>
  <div class="cm-body" id="cm-body"></div>
</div>
<script>
/* Consultant modal (Mark, Oct 21 2026): click a name in the 8 Week Outlook to assign the person to an
   open role or change their allocations - a week, a date range, or an entire allocation - in NetSuite. */
(function () {
  var modal = document.getElementById("cm-modal"), scrim = document.getElementById("cm-scrim");
  var body = document.getElementById("cm-body"), title = document.getElementById("cm-title"), sub = document.getElementById("cm-sub");
  if (!modal) return;
  /* the page's colour variables live on .viz-root, so the modal has to sit inside it */
  var root = document.querySelector(".viz-root") || document.body;
  root.appendChild(scrim); root.appendChild(modal);
  var cur = null;   /* {name, key, row} */

  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined && text !== null) n.textContent = text; return n; }
  function ctx() { return typeof window.__ctCtx === "function" ? window.__ctCtx() : null; }
  function nameOf(td) { var t = ""; Array.prototype.forEach.call(td.childNodes, function (n) { if (n.nodeType === 3) t += n.textContent; }); return t.replace(/\s+/g, " ").trim(); }
  function fmt(h) { return (Math.round(h * 10) / 10).toString(); }
  function status(node, msg, kind) { node.className = "cm-status" + (kind ? " cm-" + kind : ""); node.textContent = msg || ""; }
  function post(payload) {
    return fetch("/api/allocate", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { j.__status = r.status; return j; }); });
  }
  function errText(j) {
    var d = j.detail && typeof j.detail === "object" ? JSON.stringify(j.detail) : (j.detail || "");
    var code = { netsuite_allocation_not_found: "no allocation found", netsuite_employee_not_found: "consultant not found in NetSuite",
      netsuite_project_not_found: "project not found in NetSuite", netsuite_project_ambiguous: "more than one project matches",
      netsuite_not_configured: "NetSuite isn't connected", not_an_approver: "you are not an approver" }[j.error] || j.error || ("HTTP " + j.__status);
    return "NetSuite refused (" + code + ")" + (d ? ": " + String(d).slice(0, 240) : "");
  }
  function tagRow(row, text) {
    if (!row) return;
    var td = row.querySelector("td.grid-name"); if (!td) return;
    var t = td.querySelector(".cm-tag"); if (!t) { t = el("span", "cm-tag"); td.appendChild(t); }
    t.textContent = text; t.title = "Changed in NetSuite from this page; the Outlook updates on the next Fivetran sync and dbt build.";
  }
  function liveState(c) {
    var A = (c && c.ALLOC) || {};
    if (!A.configured) return { ok: false, why: "NetSuite isn't connected to the app yet, so changes can't be written from here." };
    if (!A.approver) return { ok: false, why: "Only approvers can write allocations to NetSuite." };
    return { ok: true, dry: !!A.dryRun, why: A.dryRun ? "Dry run: NetSuite is checked but nothing is written." : "" };
  }

  /* bookings off the grid row's tooltips: {project: {weekLabel: hours}} */
  function booked(row, weeks) {
    var out = {};
    Array.prototype.forEach.call(row.querySelectorAll("td.wk .wk-cell"), function (cell, i) {
      var t = cell.getAttribute("title") || "";
      t.replace(/^[^:]*:\s*/, "").split("; ").forEach(function (bit) {
        var m = /^(.*)\s\(([\d.]+)h\)$/.exec(bit.trim()); if (!m) return;
        out[m[1]] = out[m[1]] || {}; out[m[1]][weeks[i]] = parseFloat(m[2]) || 0;
      });
    });
    return out;
  }

  function projList() {
    if (document.getElementById("cm-proj-list")) return;
    var dl = el("datalist"); dl.id = "cm-proj-list"; var seen = {};
    Array.prototype.forEach.call(document.querySelectorAll("#staff-grid td.wk .wk-cell[title]"), function (cell) {
      (cell.getAttribute("title") || "").replace(/^[^:]*:\s*/, "").split("; ").forEach(function (bit) {
        var m = /^(.*)\s\(([\d.]+)h\)$/.exec(bit.trim()); if (m && !seen[m[1]]) { seen[m[1]] = 1; var o = el("option"); o.value = m[1]; dl.appendChild(o); }
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll(".pj-name"), function (n) { var v = n.textContent.trim(); if (v && !seen[v]) { seen[v] = 1; var o = el("option"); o.value = v; dl.appendChild(o); } });
    root.appendChild(dl);
  }

  function open(name, row) {
    var c = ctx();
    if (!c) return;
    projList();
    cur = { name: name, key: "c:" + c.slug(name), row: row };
    title.textContent = name;
    var badge = row.querySelector(".util-badge"), tgt = row.querySelector(".target-badge");
    sub.textContent = (badge ? "avg " + badge.textContent.trim() + " over the 8 weeks" : "") + (tgt ? " · " + tgt.textContent.trim() : "");
    body.textContent = "";
    var live = liveState(c);
    if (!live.ok || live.why) { var w = el("p", "cm-note", live.why); body.appendChild(w); }
    body.appendChild(weekSection(c, live));
    body.appendChild(nsSection(c, live));
    body.appendChild(assignSection(c, live));
    modal.hidden = false; scrim.hidden = false;
    document.body.style.overflow = "hidden";
  }
  function close() { modal.hidden = true; scrim.hidden = true; document.body.style.overflow = ""; cur = null; }

  /* ---- 1. week by week ------------------------------------------------------------------- */
  function weekSection(c, live) {
    var sec = el("div", "cm-sec");
    sec.appendChild(el("h4", null, "Week by week · next 8 weeks"));
    sec.appendChild(el("p", "cm-why", "Hours per week as the Outlook shows them. Change any cell - set a week to 0 to take them off that week, or type hours into an empty week - then Apply. Only the weeks you change are rewritten in NetSuite."));
    var weeks = c.GRID.weeks, bk = booked(cur.row, weeks), projs = Object.keys(bk).sort();
    var tbl = el("table", "cm-grid"), thead = el("thead"), hr = el("tr");
    hr.appendChild(el("th", null, "Project"));
    weeks.forEach(function (w) { hr.appendChild(el("th", null, w)); });
    hr.appendChild(el("th", null, ""));
    thead.appendChild(hr); tbl.appendChild(thead);
    var tb = el("tbody"); tbl.appendChild(tb);
    var inputs = {};  /* project -> [input] */
    function addRow(pr, hrs) {
      var tr = el("tr"); var td0 = el("td", "cm-proj", pr); td0.title = pr; tr.appendChild(td0);
      inputs[pr] = [];
      weeks.forEach(function (w) {
        var td = el("td"), inp = el("input"); inp.type = "number"; inp.min = "0"; inp.max = "60"; inp.step = "1";
        inp.value = fmt(hrs[w] || 0); inp.dataset.orig = inp.value;
        inp.addEventListener("input", function () { inp.classList.toggle("cm-changed", parseFloat(inp.value || "0") !== parseFloat(inp.dataset.orig)); totals(); });
        td.appendChild(inp); tr.appendChild(td); inputs[pr].push(inp);
      });
      var ta = el("td", "cm-row-actions"), clr = el("button", "cm-btn cm-sm cm-danger", "Clear"); clr.type = "button";
      clr.title = "Set every week to 0 (take them off this project for the 8 weeks)";
      clr.addEventListener("click", function () { inputs[pr].forEach(function (i) { i.value = "0"; i.dispatchEvent(new Event("input")); }); });
      ta.appendChild(clr); tr.appendChild(ta); tb.appendChild(tr);
    }
    projs.forEach(function (pr) { addRow(pr, bk[pr]); });
    var tot = el("tr", "cm-total"); tot.appendChild(el("td", null, "Total")); var totCells = [];
    weeks.forEach(function () { var td = el("td"); totCells.push(td); tot.appendChild(td); }); tot.appendChild(el("td")); tb.appendChild(tot);
    function totals() {
      weeks.forEach(function (w, i) {
        var h = 0; Object.keys(inputs).forEach(function (pr) { h += parseFloat(inputs[pr][i].value || "0") || 0; });
        totCells[i].innerHTML = fmt(h) + ' <span class="cm-pct">' + Math.round(h / 40 * 100) + '%</span>';
      });
    }
    totals();
    sec.appendChild(tbl);
    if (!projs.length) sec.appendChild(el("p", "cm-note", "No bookings in the next 8 weeks. Use Assign below."));
    var addP = el("div", "cm-actions");
    var addIn = el("input"); addIn.placeholder = "add a project row (NetSuite project name)"; addIn.setAttribute("list", "cm-proj-list"); addIn.style.minWidth = "320px"; addIn.className = "cm-proj-add";
    var addB = el("button", "cm-btn cm-sm", "+ Row"); addB.type = "button";
    addB.addEventListener("click", function () { var pr = (addIn.value || "").trim(); if (!pr || inputs[pr]) return; tb.removeChild(tot); addRow(pr, {}); tb.appendChild(tot); addIn.value = ""; });
    addP.appendChild(addIn); addP.appendChild(addB);
    var note = el("input"); note.placeholder = "note (optional)"; note.style.minWidth = "260px"; addP.appendChild(note);
    var apply = el("button", "cm-btn cm-primary", live.ok ? (live.dry ? "Check in NetSuite (dry run)" : "Apply in NetSuite") : "Apply in NetSuite"); apply.type = "button"; apply.disabled = !live.ok;
    var st = el("div", "cm-status"), log = el("ul", "cm-log");
    apply.addEventListener("click", function () {
      var changes = [];
      Object.keys(inputs).forEach(function (pr) {
        var ws = [], changed = false;
        inputs[pr].forEach(function (inp, i) {
          var h = Math.max(0, parseFloat(inp.value || "0") || 0), iso = c.weekISO(i);
          if (h !== parseFloat(inp.dataset.orig)) changed = true;
          ws.push({ week: iso, hours: h });
        });
        if (changed) changes.push({ project: pr, weeks: ws });
      });
      if (!changes.length) { status(st, "Nothing changed.", null); return; }
      apply.disabled = true; status(st, "Writing to NetSuite…", null);
      var i = 0, said = [];
      (function next() {
        if (i >= changes.length) {
          apply.disabled = false; status(st, "Done - " + said.length + " project" + (said.length === 1 ? "" : "s") + " updated. The Outlook picks it up on the next sync.", "ok");
          tagRow(cur.row, live.dry ? "dry run" : "changed in NetSuite");
          c.note(cur.key, (live.dry ? "NetSuite dry run (week by week): " : "Week-by-week change in NetSuite: ") + cur.name + " - " + said.join("; ") + ((note.value || "").trim() ? " - " + note.value.trim() : ""));
          return;
        }
        var ch = changes[i++];
        post({ kind: "reshape", consultant: cur.name, project: ch.project, weeks: ch.weeks, note: (note.value || "").trim(),
               key: cur.key, label: cur.name, author: c.author(), week: c.THIS_WEEK })
        .then(function (j) {
          if (j.ok) {
            var ns = j.netsuite || {}, chg = (ns.changed || []).map(function (x) { return x.week.slice(5) + " " + x.from + "→" + x.to; }).join(", ");
            var line = ch.project + ": " + (chg || "no difference from NetSuite") + (ns.created && ns.created.length ? " · " + ns.created.length + " new allocation" + (ns.created.length === 1 ? "" : "s") : "") + (ns.trimmed && ns.trimmed.length ? " · " + ns.trimmed.length + " trimmed" : "");
            said.push(line); log.appendChild(el("li", null, line));
            inputs[ch.project].forEach(function (inp) { inp.dataset.orig = fmt(parseFloat(inp.value || "0") || 0); inp.classList.remove("cm-changed"); });
            next();
          } else { apply.disabled = false; status(st, ch.project + ": " + errText(j), "err"); }
        }).catch(function () { apply.disabled = false; status(st, "Couldn't reach the app.", "err"); });
      })();
    });
    addP.appendChild(apply); sec.appendChild(addP); sec.appendChild(st); sec.appendChild(log);
    return sec;
  }

  /* ---- 2. allocations in NetSuite ----------------------------------------------------------- */
  function nsSection(c, live) {
    var sec = el("div", "cm-sec");
    sec.appendChild(el("h4", null, "Allocations in NetSuite"));
    sec.appendChild(el("p", "cm-why", "Every allocation of theirs that hasn't ended, straight from NetSuite. Change the dates or hours per week and Save to rewrite the whole allocation (this is where an end date past the 8 weeks is moved), or Remove it."));
    var st = el("div", "cm-status"); var holder = el("div");
    sec.appendChild(holder); sec.appendChild(st);
    if (!live.ok && !((c.ALLOC || {}).configured)) { status(st, "NetSuite isn't connected to the app, so there is nothing to show here.", null); return sec; }
    status(st, "Loading from NetSuite…", null);
    fetch("/api/allocate?consultant=" + encodeURIComponent(cur.name), { credentials: "same-origin" })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { j.__status = r.status; return j; }); })
      .then(function (j) {
        if (!j.ok) { status(st, errText(j), "err"); return; }
        status(st, "", null);
        var rows = j.allocations || [];
        if (!rows.length) { holder.appendChild(el("p", "cm-note", "No current or future allocations in NetSuite for " + (j.employeeName || cur.name) + ".")); return; }
        var tbl = el("table", "cm-grid"), thead = el("thead"), hr = el("tr");
        ["Project", "Start", "End", "Hrs/wk", "Role", ""].forEach(function (h) { hr.appendChild(el("th", null, h)); });
        thead.appendChild(hr); tbl.appendChild(thead); var tb = el("tbody"); tbl.appendChild(tb);
        rows.forEach(function (a) {
          var tr = el("tr"); var td0 = el("td", "cm-proj", a.project); td0.title = "allocation " + a.allocationId; tr.appendChild(td0);
          var sIn = el("input"); sIn.type = "date"; sIn.value = a.startDate; var eIn = el("input"); eIn.type = "date"; eIn.value = a.endDate;
          var hIn = el("input"); hIn.type = "number"; hIn.min = "0"; hIn.max = "60"; hIn.step = "0.5"; hIn.value = fmt(a.hoursPerWeek);
          [sIn, eIn, hIn].forEach(function (inp) { inp.dataset.orig = inp.value; inp.addEventListener("input", function () { inp.classList.toggle("cm-changed", inp.value !== inp.dataset.orig); }); });
          var t1 = el("td"); t1.appendChild(sIn); tr.appendChild(t1); var t2 = el("td"); t2.appendChild(eIn); tr.appendChild(t2);
          var t3 = el("td"); t3.appendChild(hIn); tr.appendChild(t3);
          var t4 = el("td", "cm-muted", a.role || (a.unit === "H" ? a.numberHours + " h total" : a.percentOfTime + "%")); tr.appendChild(t4);
          var ta = el("td", "cm-row-actions");
          var save = el("button", "cm-btn cm-sm cm-primary", "Save"); save.type = "button"; save.disabled = !live.ok;
          var rem = el("button", "cm-btn cm-sm cm-danger", "Remove"); rem.type = "button"; rem.disabled = !live.ok; rem.style.marginLeft = "4px";
          function send(payload, what) {
            save.disabled = rem.disabled = true; status(st, "Writing to NetSuite…", null);
            post(payload).then(function (jj) {
              save.disabled = rem.disabled = false;
              if (jj.ok) {
                var r = jj.netsuite || {};
                var line = a.project + ": " + (r.action === "deleted" ? "allocation " + a.allocationId + " removed" : "now " + r.now.startDate + " to " + r.now.endDate + ", " + r.now.hoursPerWeek + " hrs/wk" + (r.action === "unchanged" ? " (no change)" : ""));
                status(st, (jj.dryRun ? "Dry run OK - " : "Done - ") + line, "ok");
                if (r.action === "deleted" && !jj.dryRun) tr.parentNode.removeChild(tr);
                else [sIn, eIn, hIn].forEach(function (inp) { inp.dataset.orig = inp.value; inp.classList.remove("cm-changed"); });
                tagRow(cur.row, jj.dryRun ? "dry run" : "changed in NetSuite");
                c.note(cur.key, (jj.dryRun ? "NetSuite dry run: " : "Allocation " + what + " in NetSuite: ") + cur.name + " - " + line);
              } else status(st, errText(jj), "err");
            }).catch(function () { save.disabled = rem.disabled = false; status(st, "Couldn't reach the app.", "err"); });
          }
          save.addEventListener("click", function () {
            send({ kind: "update", consultant: cur.name, allocationId: a.allocationId, startDate: sIn.value, endDate: eIn.value, hoursPerWeek: parseFloat(hIn.value || "0"),
                   key: cur.key, label: cur.name, author: c.author(), week: c.THIS_WEEK }, "changed");
          });
          rem.addEventListener("click", function () {
            if (!window.confirm("Remove " + cur.name + " from " + a.project + " (" + a.startDate + " to " + a.endDate + ") in NetSuite?")) return;
            send({ kind: "update", consultant: cur.name, allocationId: a.allocationId, hoursPerWeek: 0, key: cur.key, label: cur.name, author: c.author(), week: c.THIS_WEEK }, "removed");
          });
          ta.appendChild(save); ta.appendChild(rem); tr.appendChild(ta); tb.appendChild(tr);
        });
        holder.appendChild(tbl);
      }).catch(function () { status(st, "Couldn't reach the app to read NetSuite.", "err"); });
    return sec;
  }

  /* ---- 3. assign ------------------------------------------------------------------------- */
  function assignSection(c, live) {
    var sec = el("div", "cm-sec");
    sec.appendChild(el("h4", null, "Assign"));
    sec.appendChild(el("p", "cm-why", "To an open role on this page (hours and weeks prefilled from its demand; the role's generic allocation in NetSuite is filled) or to any other project."));
    var f = el("div", "cm-form");
    function field(label, node) { var l = el("label", null, label); l.appendChild(node); f.appendChild(l); return node; }
    var roleSel = field("Open role", el("select")); var o0 = el("option", null, "Other project (not an open role)"); o0.value = ""; roleSel.appendChild(o0);
    (c.ROLES || []).forEach(function (r) { var o = el("option", null, r.label); o.value = r.key; roleSel.appendChild(o); });
    var proj = field("Project", el("input")); proj.placeholder = "client / project name"; proj.setAttribute("list", "cm-proj-list");
    var hrs = field("Hours / week", el("input")); hrs.type = "number"; hrs.min = "1"; hrs.max = "60"; hrs.step = "1"; hrs.value = "40";
    var from = field("From week", el("select")), thru = field("Through", el("select"));
    c.GRID.weeks.forEach(function (w, i) { var a = el("option", null, w); a.value = String(i); from.appendChild(a); var b = el("option", null, w); b.value = String(i); thru.appendChild(b); });
    thru.value = String(Math.max(0, c.GRID.weeks.length - 1));
    var note = field("Note", el("input")); note.placeholder = "optional"; note.parentNode.className = "cm-wide";
    function roleByKey(k) { for (var i = 0; i < c.ROLES.length; i++) if (c.ROLES[i].key === k) return c.ROLES[i]; return null; }
    roleSel.addEventListener("change", function () {
      var r = roleByKey(roleSel.value);
      if (!r) { proj.removeAttribute("readonly"); if (proj.dataset.auto === "1") proj.value = ""; proj.dataset.auto = ""; return; }
      var rp = c.roleProject(r.label);
      proj.value = (rp && rp.project) || r.project || r.label; proj.setAttribute("readonly", "readonly"); proj.dataset.auto = "1";
      var first = -1, last = -1, h = 0;
      c.GRID.weeks.forEach(function (w, i) { if ((r.hrs[w] || 0) > 0) { if (first < 0) first = i; last = i; h = Math.max(h, r.hrs[w]); } });
      if (first >= 0) { from.value = String(first); thru.value = String(last); }
      if (h) hrs.value = String(Math.round(h));
    });
    sec.appendChild(f);
    var act = el("div", "cm-actions"), st = el("div", "cm-status");
    var go = el("button", "cm-btn cm-primary", live.ok ? (live.dry ? "Check in NetSuite (dry run)" : "Allocate in NetSuite") : "Allocate in NetSuite"); go.type = "button"; go.disabled = !live.ok;
    go.addEventListener("click", function () {
      var pr = (proj.value || "").trim(), h = parseFloat(hrs.value) || 0;
      var i0 = parseInt(from.value, 10), i1 = parseInt(thru.value, 10); if (i1 < i0) { var t = i0; i0 = i1; i1 = t; }
      if (!pr) { proj.focus(); return; } if (!(h > 0)) { hrs.focus(); return; }
      var weeks = []; for (var i = i0; i <= i1; i++) { var w = c.weekISO(i); if (w) weeks.push(w); }
      var r = roleByKey(roleSel.value), rl = r ? r.label : "";
      go.disabled = true; status(st, "Writing to NetSuite…", null);
      post({ consultant: cur.name, project: pr, roleKey: roleSel.value || "", roleLabel: rl, roleTitle: rl ? rl.slice(rl.indexOf(": ") + 2) : "",
             hours: h, weeks: weeks, note: (note.value || "").trim(), key: cur.key, label: cur.name, author: c.author(), week: c.THIS_WEEK, fillOpenRole: !!rl })
      .then(function (j) {
        go.disabled = false;
        if (j.ok) {
          var ns = j.netsuite || {};
          var line = cur.name + " → " + (ns.projectName || pr) + ", " + h + " hrs/wk (" + (ns.percentOfTime || "") + "%), " + ns.startDate + " to " + ns.endDate
            + (ns.allocationId ? " · allocation " + ns.allocationId : "") + (ns.openRole && ns.openRole.action !== "none" ? " · open role " + ns.openRole.action : "");
          status(st, (j.dryRun ? "Dry run OK - " : "Done - ") + line, "ok");
          tagRow(cur.row, j.dryRun ? "dry run" : "changed in NetSuite");
          c.note(cur.key, (j.dryRun ? "NetSuite dry run OK: " : "Allocated in NetSuite: ") + line + ((note.value || "").trim() ? " - " + note.value.trim() : ""));
        } else status(st, errText(j), "err");
      }).catch(function () { go.disabled = false; status(st, "Couldn't reach the app.", "err"); });
    });
    var cm = el("button", "cm-btn", "Comments ✎"); cm.type = "button"; cm.title = "Open this consultant's comment thread";
    cm.addEventListener("click", function () { var k = cur.key; close(); if (c.openDrawer) c.openDrawer(k); });
    act.appendChild(go); act.appendChild(cm); sec.appendChild(act); sec.appendChild(st);
    return sec;
  }

  /* ---- wiring ---------------------------------------------------------------------------- */
  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    if (t.closest("#cm-close") || (t.id === "cm-scrim")) { close(); return; }
    var td = t.closest("#staff-grid td.grid-name");
    if (!td || t.closest(".ct-btn, button, a, input, select")) return;
    var name = nameOf(td); if (!name) return;
    ev.preventDefault();
    open(name, td.closest("tr"));
  });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && !modal.hidden) close(); });
})();
</script>
"""
anchor = "</body>"
if anchor in s:
    s = s.replace(anchor, HTML_JS + anchor, 1)
else:
    s = s.rstrip("\n") + "\n" + HTML_JS
open(OUT, "w", encoding="utf-8").write(s)
print(f"consultant modal: wrote {OUT} ({len(s):,} bytes)")
