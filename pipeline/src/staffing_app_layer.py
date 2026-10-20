#!/usr/bin/env python3
"""Collaboration layer for the Cleartelligence Staffing Dashboard.

Turns the published dashboard into a working app on top of the artifact `db`
capability. Everything here is additive: the generated dashboard HTML is
unchanged except for small mount points (see inject_app_layer.py / the
build_dashboard.py hooks), so a weekly data refresh carries this along without
touching any of the chart or table code.

What it adds
------------
* Threaded comments, kept forever, on four kinds of subject:
    consultant (staff grid rows + Section 3 by-consultant bars)
    role       (each open requisition)
    account    (each client in the August variance charts)
    section    (each section heading)
  Every comment carries author, timestamp, the meeting week it was written in,
  and a status (note / watching / action needed / resolved). The thread view
  groups by meeting week and can be filtered to one week.
* Action items with an owner and a due date, promoted from a comment or added
  directly. Open items carry forward week to week and are listed in the
  Meeting Log panel.
* Proposed allocations: assign a consultant to an open role or to any project,
  hrs/week over a week range, from inside a thread. Proposed assignments show
  as a pending overlay in the 8 Week Outlook, adjust the Capacity vs. Need
  table, and queue for entry in Salesforce (with a CSV export). They are marked
  pending until someone marks them entered.
* Week-over-week change flags: each published build snapshots its own figures
  (read out of the rendered DOM, so no extra data plumbing) into the store, and
  the page diffs the current build against the most recent earlier snapshot.

Data model (artifact db store)
------------------------------
  threads/<key>       { label, kind, comments: [ {id,text,author,ts,week,status} ],
                        seeded, updated }
  actions/<id>        { text, owner, due, done, doneTs, key, label, week, author, ts }
  allocations/<id>    { consultant, project, client, roleKey, hours, weeks[],
                        status: proposed|entered|declined, note, author, ts, key }
  snapshots/<week>    { week, gen, ts, head{}, staff{}, roles{}, accounts{} }
  agenda_archive/<wk> { week, items: [ {text, done, order, ts} ], archivedTs, source }
                      - the Meeting Agenda as it stood at the end of that week's meeting,
                        filed by the weekly refresh (Mark, Sep 21 2026) so every meeting
                        leaves a record in the log
  role_comments/<rk>  (legacy, pre-Sep-10 single-textarea comments) - read once
                      per role and seeded into that role's thread as its first
                      comment, then left alone.

Subject keys are stable across weekly rebuilds: c:<slug name>, r:<role slug as
already emitted by build_outlook_section.role_key>, a:<slug account>, s:<id>.

Publish with capabilities={"db": {}} (unchanged from before - no new capability
is required, and none is declared, so the stored contract pin carries forward).
Viewer identity: the artifact `user` capability is not available to this
account, so the author name is asked for once and kept in that browser's
localStorage.
"""

APP_CSS = """
/* ================= staffing app layer: comments, actions, allocations ====== */
.mlog-agenda-list { margin: 4px 0 10px; padding-left: 26px; font-size: 12.5px; }
.mlog-agenda-item { margin: 2px 0; }
.mlog-agenda-mark { display: inline-block; width: 16px; color: var(--muted-ink); font-weight: 700; }
.mlog-agenda-done .mlog-agenda-text { color: var(--muted-ink); text-decoration: line-through; }
.ct-btn {
  display: inline-flex; align-items: center; gap: 3px; vertical-align: 1px;
  background: none; border: 1px solid var(--gridline); border-radius: 10px;
  color: var(--muted-ink); cursor: pointer; font: inherit; font-size: 10px;
  font-weight: 700; line-height: 1.6; padding: 0 6px; margin-left: 6px;
}
.ct-btn:hover { border-color: var(--accent); color: var(--accent); }
.ct-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.ct-btn-ico { font-size: 10px; font-weight: 400; }
.ct-btn.ct-has { border-color: var(--accent); color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent); }
.ct-btn.ct-st-watch { border-color: var(--status-warning); color: var(--text-primary);
  background: color-mix(in srgb, var(--status-warning) 22%, transparent); }
.ct-btn.ct-st-action { border-color: var(--status-critical); color: #fff;
  background: var(--status-critical); }
.ct-btn.ct-st-resolved { border-color: var(--status-good); color: var(--status-good);
  background: color-mix(in srgb, var(--status-good) 12%, transparent); }
.sec-head .ct-btn { font-size: 11px; vertical-align: 2px; }
.ub-row .ct-btn { margin-left: 4px; }
.ub-row { grid-template-columns: 16px 200px 1fr 58px auto; }
@media (max-width: 760px) { .ub-row { grid-template-columns: 14px 130px 1fr 52px auto; } }

/* ---- inline thread mount (open roles + capacity commentary) ---- */
.ct-mount { border: 1px dashed var(--gridline); border-radius: 7px; padding: 5px 9px 6px;
  background: var(--surface-page); }
.ct-mount-empty { color: var(--muted-ink); font-size: 11.5px; font-style: italic; }
.ct-mount-line { font-size: 11.5px; color: var(--text-primary); margin-bottom: 2px; }
.ct-mount-line:last-child { margin-bottom: 0; }
.ct-mount-meta { color: var(--muted-ink); font-size: 10.5px; font-style: normal; }
.ct-mount button.ct-open { background: none; border: none; padding: 0; margin-top: 3px;
  font: inherit; font-size: 11px; font-weight: 600; color: var(--accent); cursor: pointer;
  text-decoration: underline; text-underline-offset: 2px; }
.section-note.ct-mount { margin: 0 0 12px; }

/* ---- proposed allocation overlay ---- */
.wk-proj-prop { color: var(--accent); font-weight: 700; font-style: italic; }
.wk-cell.wk-prop { box-shadow: inset 3px 0 0 var(--accent), 0 0 0 1px var(--accent) inset; }
.prop-chip { display: inline-block; font-size: 10px; font-weight: 700; border-radius: 9px;
  padding: 1px 8px; margin: 3px 4px 0 0; white-space: nowrap;
  background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent);
  border: 1px dashed var(--accent); }
tr.cap-prop-row td { color: var(--accent); font-weight: 600; }
tr.cap-prop-gap-row td { font-weight: 700; background: var(--surface-page); }
.cap-prop-note { font-size: 11px; color: var(--muted-ink); margin-top: 6px; font-style: italic; }

/* ================= meeting log panel ====================================== */
.mlog { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 18px 16px; margin-bottom: 16px; }
.mlog [hidden] { display: none !important; }
.mlog .sec-head { margin: -14px -18px 12px !important; padding: 9px 18px; }
.mlog-sub { font-size: 11.5px; font-weight: 500; color: var(--muted-ink); margin-left: 8px; }
.mlog-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.mlog-tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.mlog-tab { border: 1px solid var(--border); background: var(--surface-page);
  color: var(--text-secondary); font: inherit; font-size: 12.5px; font-weight: 600;
  border-radius: 7px; padding: 5px 12px; cursor: pointer; }
.mlog-tab:hover { color: var(--text-primary); }
.mlog-tab-active { background: var(--accent); border-color: var(--accent); color: #fff; }
.mlog-tab-active:hover { color: #fff; }
.mlog-tab .n { font-variant-numeric: tabular-nums; opacity: 0.8; }
.mlog-spacer { flex: 1 1 auto; }
.mlog-who { font-size: 11.5px; color: var(--muted-ink); display: inline-flex; align-items: center; gap: 5px; }
.mlog-who input { border: 1px solid var(--border); border-radius: 6px; background: var(--surface-page);
  color: var(--text-primary); font: inherit; font-size: 11.5px; padding: 3px 7px; width: 130px; }
.mlog-select { border: 1px solid var(--border); border-radius: 6px; background: var(--surface-page);
  color: var(--text-primary); font: inherit; font-size: 12px; padding: 4px 8px; }
.mlog-pane { font-size: 12.5px; }
.mlog-empty { color: var(--muted-ink); font-style: italic; font-size: 12.5px; padding: 4px 0 2px; }
.mlog-row { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0;
  border-bottom: 1px solid var(--gridline); }
.mlog-row:last-child { border-bottom: none; }
.mlog-row-main { flex: 1 1 auto; min-width: 0; }
.mlog-row-title { font-size: 12.5px; }
.mlog-row-sub { font-size: 11px; color: var(--muted-ink); margin-top: 1px; }
.mlog-row-side { flex: 0 0 auto; display: flex; gap: 5px; align-items: center; }
.mlog-link { background: none; border: none; padding: 0; font: inherit; font-size: 11px;
  font-weight: 600; color: var(--accent); cursor: pointer; text-decoration: underline;
  text-underline-offset: 2px; }
.mlog-danger { color: var(--diverge-under); }
.mlog-sm { border: 1px solid var(--border); border-radius: 6px; background: var(--surface-page);
  color: var(--text-secondary); font: inherit; font-size: 11px; font-weight: 600;
  padding: 2px 8px; cursor: pointer; }
.mlog-sm:hover { color: var(--text-primary); border-color: var(--accent); }
.mlog-done .mlog-row-title { text-decoration: line-through; color: var(--muted-ink); }
.subject-tag { display: inline-block; font-size: 10px; font-weight: 700; border-radius: 4px;
  padding: 0 5px; background: var(--gridline); color: var(--text-secondary); margin-right: 5px;
  vertical-align: 1px; }
.due-chip { font-size: 10.5px; font-weight: 700; border-radius: 4px; padding: 0 5px;
  background: var(--gridline); color: var(--text-secondary); }
.due-late { background: color-mix(in srgb, var(--status-critical) 20%, transparent);
  color: var(--diverge-under); }
.due-soon { background: color-mix(in srgb, var(--status-warning) 26%, transparent);
  color: var(--text-primary); }
.chg-list { display: flex; flex-wrap: wrap; gap: 6px; }
.chg { font-size: 11.5px; border-radius: 7px; padding: 3px 9px; border: 1px solid var(--border);
  background: var(--surface-page); }
.chg-up { border-color: color-mix(in srgb, var(--status-good) 45%, transparent);
  background: color-mix(in srgb, var(--status-good) 10%, transparent); }
.chg-down { border-color: color-mix(in srgb, var(--status-critical) 45%, transparent);
  background: color-mix(in srgb, var(--status-critical) 10%, transparent); }
.chg-new { border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: color-mix(in srgb, var(--accent) 10%, transparent); }
.chg-b { font-weight: 700; }
.mlog-group-head { font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--muted-ink); font-weight: 700; margin: 10px 0 3px; }
.mlog-group-head:first-child { margin-top: 2px; }

/* ================= drawer ================================================= */
.ct-scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.12); z-index: 60;
  pointer-events: none; }  /* separation only - the page stays clickable while a thread is open */
.ct-drawer { position: fixed; top: 0; right: 0; bottom: 0; width: 430px; max-width: 94vw;
  background: var(--surface-1); border-left: 1px solid var(--border); z-index: 61;
  display: flex; flex-direction: column; box-shadow: -8px 0 28px rgba(0,0,0,0.16);
  color: var(--text-primary); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.ct-drawer [hidden] { display: none !important; }
/* the drawer and scrim set display themselves, so the UA [hidden] rule loses without this */
.ct-drawer[hidden], .ct-scrim[hidden] { display: none !important; }
.ct-dr-head { padding: 12px 16px 10px; border-bottom: 1px solid var(--gridline); }
.ct-dr-kind { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted-ink); font-weight: 700; }
.ct-dr-title { font-size: 15px; font-weight: 700; margin-top: 1px; padding-right: 26px; }
.ct-dr-close { position: absolute; top: 9px; right: 12px; background: none; border: none;
  font-size: 20px; line-height: 1; color: var(--muted-ink); cursor: pointer; padding: 2px 6px; }
.ct-dr-close:hover { color: var(--text-primary); }
.ct-dr-tools { display: flex; gap: 6px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
.ct-dr-body { flex: 1 1 auto; overflow-y: auto; padding: 10px 16px 14px; }
.ct-dr-foot { border-top: 1px solid var(--gridline); padding: 10px 16px 12px;
  background: var(--surface-page); }
.ct-cmt { padding: 7px 0; border-bottom: 1px solid var(--gridline); }
.ct-cmt:last-child { border-bottom: none; }
.ct-cmt-meta { font-size: 10.5px; color: var(--muted-ink); margin-bottom: 2px; }
.ct-cmt-author { font-weight: 700; color: var(--text-secondary); }
.ct-cmt-text { font-size: 12.5px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }
.ct-st { display: inline-block; font-size: 9.5px; font-weight: 700; border-radius: 4px;
  padding: 0 5px; text-transform: uppercase; letter-spacing: 0.03em; margin-left: 5px; }
.ct-st-note-b { background: var(--gridline); color: var(--text-secondary); }
.ct-st-watch-b { background: color-mix(in srgb, var(--status-warning) 30%, transparent); color: var(--text-primary); }
.ct-st-action-b { background: var(--status-critical); color: #fff; }
.ct-st-resolved-b { background: color-mix(in srgb, var(--status-good) 18%, transparent); color: var(--status-good); }
.ct-wk-head { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted-ink); font-weight: 700; margin: 12px 0 2px;
  border-top: 1px solid var(--gridline); padding-top: 8px; }
.ct-wk-head:first-child { margin-top: 0; border-top: none; padding-top: 0; }
.ct-more { background: none; border: none; padding: 6px 0 0; font: inherit; font-size: 11.5px;
  font-weight: 600; color: var(--accent); cursor: pointer; text-decoration: underline;
  text-underline-offset: 2px; }
.ct-compose textarea { width: 100%; min-height: 54px; resize: vertical; border: 1px solid var(--border);
  border-radius: 7px; background: var(--surface-1); color: var(--text-primary); font: inherit;
  font-size: 12.5px; padding: 6px 8px; box-sizing: border-box; }
.ct-compose-row { display: flex; gap: 6px; align-items: center; margin-top: 7px; flex-wrap: wrap; }
.ct-primary { border: 1px solid var(--accent); border-radius: 7px; background: var(--accent);
  color: #fff; font: inherit; font-size: 12.5px; font-weight: 700; padding: 6px 14px; cursor: pointer; }
.ct-primary:hover { filter: brightness(1.08); }
.ct-primary:disabled { opacity: 0.45; cursor: default; filter: none; }
.ct-ghost { border: 1px solid var(--border); border-radius: 7px; background: var(--surface-1);
  color: var(--text-secondary); font: inherit; font-size: 12px; font-weight: 600;
  padding: 6px 12px; cursor: pointer; }
.ct-ghost:hover { color: var(--text-primary); border-color: var(--accent); }
.ct-form { border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px 11px;
  margin-top: 9px; background: var(--surface-1); }
.ct-form h4 { font-size: 12px; margin: 0 0 7px; text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--text-secondary); }
.ct-field { display: flex; align-items: center; gap: 7px; margin-bottom: 6px; }
.ct-field label { font-size: 11px; color: var(--muted-ink); font-weight: 600; flex: 0 0 88px; }
.ct-field input, .ct-field select, .ct-field textarea { flex: 1 1 auto; min-width: 0;
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface-page);
  color: var(--text-primary); font: inherit; font-size: 12px; padding: 4px 7px; }
.ct-field-note { font-size: 10.5px; color: var(--muted-ink); margin: -2px 0 7px 95px; }
.ct-hint { font-size: 11px; color: var(--muted-ink); margin-top: 6px; line-height: 1.45; }
.ct-err { font-size: 11.5px; color: var(--diverge-under); margin-top: 6px; }
.ct-offline { font-size: 11.5px; color: var(--muted-ink); font-style: italic; }
.ct-export { width: 100%; height: 150px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px; border: 1px solid var(--border); border-radius: 7px; padding: 7px;
  background: var(--surface-page); color: var(--text-primary); box-sizing: border-box; }
@media (max-width: 620px) { .ct-drawer { width: 100vw; } }
"""


APP_HTML = """<section class="mlog" id="meeting-log">
  <h2 class="sec-head">Meeting Log <span class="mlog-sub">shared &mdash; comment history, action items and proposed allocations, kept week over week</span></h2>
  <div class="mlog-bar">
    <div class="mlog-tabs" id="mlog-tabs">
      <button type="button" class="mlog-tab mlog-tab-active" data-pane="actions">Open actions <span class="n" id="n-actions">0</span></button>
      <button type="button" class="mlog-tab" data-pane="allocs">Proposed allocations <span class="n" id="n-allocs">0</span></button>
      <button type="button" class="mlog-tab" data-pane="disc">Needs discussion <span class="n" id="n-disc">0</span></button>
      <button type="button" class="mlog-tab" data-pane="recent">Comments <span class="n" id="n-recent">0</span></button>
      <button type="button" class="mlog-tab" data-pane="changed">What changed</button>
      <button type="button" class="mlog-tab" data-pane="agenda">Meeting agendas <span class="n" id="n-agenda">0</span></button>
    </div>
    <span class="mlog-spacer"></span>
    <select class="mlog-select" id="mlog-week" aria-label="Filter by meeting week"><option value="all">All weeks</option></select>
    <span class="mlog-who">Commenting as <input id="mlog-author" type="text" maxlength="40" placeholder="your name" aria-label="Your name"></span>
  </div>
  <div class="mlog-pane" id="mlog-pane"><div class="mlog-empty">Loading the shared meeting log&hellip;</div></div>
</section>"""


APP_JS = r"""<script>
(function () {
  "use strict";

  /* ------------------------------------------------------------------ util */
  var OFFLINE = "The meeting log lives on the live dashboard page on claude.ai - this copy can't reach it.";
  var STATUSES = [["note", "Note"], ["watch", "Watching"], ["action", "Action needed"], ["resolved", "Resolved"]];
  var STATUS_LABEL = {};
  STATUSES.forEach(function (s) { STATUS_LABEL[s[0]] = s[1]; });
  var MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt !== undefined && txt !== null) n.textContent = txt;
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function slug(s) {
    return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/-+/g, "-")
      .replace(/^-|-$/g, "").slice(0, 110) || "x";
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function isoOf(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function mondayISO(d) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var off = (x.getDay() + 6) % 7;              /* Mon = 0 */
    x.setDate(x.getDate() - off);
    return isoOf(x);
  }
  function weekLabel(iso) {
    var p = String(iso || "").split("-");
    if (p.length !== 3) return "unknown week";
    return MON[parseInt(p[1], 10) - 1] + " " + parseInt(p[2], 10);
  }
  function weekLabelLong(iso) {
    var p = String(iso || "").split("-");
    if (p.length !== 3) return "unknown week";
    return "Week of " + MON[parseInt(p[1], 10) - 1] + " " + parseInt(p[2], 10) + ", " + p[0];
  }
  function stamp(ts) {
    var d = new Date(ts || 0);
    var h = d.getHours(), ap = h >= 12 ? "pm" : "am";
    h = h % 12; if (!h) h = 12;
    return MON[d.getMonth()] + " " + d.getDate() + ", " + h + ":" + pad(d.getMinutes()) + ap;
  }
  function uid() {
    return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
  }
  var THIS_WEEK = mondayISO(new Date());

  /* ----------------------------------------------------------------- state */
  var S = {
    db: null, ready: false, offline: false,
    author: "",
    threads: {},          /* key -> {label, kind, comments[]} */
    actions: [],
    allocs: [],
    snaps: {},
    agendas: {},          /* week -> {week, items[]} archived agendas */
    subjects: {},         /* key -> {label, kind} from the DOM */
    week: "all",
    tab: "actions",
    openKey: null
  };
  try { S.author = window.localStorage.getItem("ct.author") || ""; } catch (e) { S.author = ""; }

  /* --------------------------------------------------- subject registry ---- */
  /* Mount points and buttons are emitted by the generator with data-ct-key /
     data-ct-kind / data-ct-label. Section 3 bar rows and the staff grid get
     their buttons wired here so the generator stays untouched. */
  function registerSubject(key, kind, label) {
    if (!S.subjects[key]) S.subjects[key] = { label: label, kind: kind };
    return S.subjects[key];
  }
  function subjectLabel(key) {
    var s = S.subjects[key];
    if (s) return s.label;
    var t = S.threads[key];
    return (t && t.label) || key;
  }
  function subjectKind(key) {
    var s = S.subjects[key];
    if (s) return s.kind;
    var t = S.threads[key];
    return (t && t.kind) || "note";
  }

  function makeBtn(key, kind, label) {
    registerSubject(key, kind, label);
    var b = el("button", "ct-btn");
    b.type = "button";
    b.dataset.ctKey = key;
    b.title = "Comments and history - " + label;
    b.setAttribute("aria-label", "Comments for " + label);
    var ico = el("span", "ct-btn-ico", "✎");
    var cnt = el("span", "ct-count", "");
    b.appendChild(ico); b.appendChild(cnt);
    b.addEventListener("click", function (ev) {
      ev.stopPropagation();
      ev.preventDefault();
      openDrawer(key);
    });
    return b;
  }

  function wireExistingButtons() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-ct-key]"), function (n) {
      if (n.classList.contains("ct-btn")) return;      /* already wired below */
      registerSubject(n.dataset.ctKey, n.dataset.ctKind || "note", n.dataset.ctLabel || n.dataset.ctKey);
    });
  }

  /* staff grid: one button per consultant row */
  var GRID = { names: [], weeks: [], rowByName: {} };
  function wireStaffGrid() {
    var grid = $("staff-grid");
    if (!grid) return;
    var ths = grid.querySelectorAll("thead th.wk");
    Array.prototype.forEach.call(ths, function (th) { GRID.weeks.push(th.textContent.trim()); });
    Array.prototype.forEach.call(grid.querySelectorAll("tbody tr"), function (tr) {
      var nameCell = tr.querySelector("td.grid-name");
      if (!nameCell) return;
      var name = "";
      Array.prototype.forEach.call(nameCell.childNodes, function (n) {
        if (n.nodeType === 3) name += n.textContent;
      });
      name = name.trim();
      if (!name) return;
      var key = "c:" + slug(name);
      GRID.names.push(name);
      GRID.rowByName[name] = tr;
      nameCell.appendChild(makeBtn(key, "consultant", name));
    });
  }

  /* Section 3 bars: accounts pane -> account subjects, consultants pane ->
     the same consultant thread as the staff grid row. */
  function wireVarianceRows() {
    ["s3-pane-acct", "s3-pane-cons"].forEach(function (id) {
      var pane = $(id);
      if (!pane) return;
      var isAcct = id === "s3-pane-acct";
      Array.prototype.forEach.call(pane.querySelectorAll(".ub-row"), function (row) {
        var nm = row.querySelector(".ub-name");
        if (!nm) return;
        var label = nm.textContent.trim();
        if (!label) return;
        var key = (isAcct ? "a:" : "c:") + slug(label);
        row.appendChild(makeBtn(key, isAcct ? "account" : "consultant", label));
      });
    });
  }

  /* project rows in the Projects, Roles & Open Demand grid */
  function wireProjectRows() {
    var tbl = document.getElementById("projects-table");
    if (!tbl) return;
    Array.prototype.forEach.call(tbl.querySelectorAll("tr.pj-row"), function (tr) {
      var nm = tr.querySelector(".pj-name");
      if (!nm) return;
      var label = nm.textContent.trim();
      if (!label) return;
      var key = "p:" + slug(tr.dataset.pj || label);
      var host = tr.querySelector(".chip-row") || tr.querySelector("td");
      host.appendChild(makeBtn(key, "project", label));
    });
  }

  /* section headings */
  function wireSectionHeads() {
    Array.prototype.forEach.call(document.querySelectorAll(".sec-head"), function (h) {
      if (h.closest("#meeting-log")) return;
      var label = "";
      Array.prototype.forEach.call(h.childNodes, function (n) {
        if (n.nodeType === 3) label += n.textContent;
      });
      label = label.trim().replace(/\s+/g, " ");
      if (!label) return;
      h.appendChild(makeBtn("s:" + slug(label), "section", label));
    });
  }

  /* inline mounts (open roles, capacity commentary) */
  function wireMounts() {
    Array.prototype.forEach.call(document.querySelectorAll(".ct-mount"), function (m) {
      registerSubject(m.dataset.ctKey, m.dataset.ctKind || "note", m.dataset.ctLabel || m.dataset.ctKey);
      m.addEventListener("click", function (ev) {
        if (ev.target && ev.target.closest && ev.target.closest("button")) return;
        openDrawer(m.dataset.ctKey);
      });
    });
  }

  /* ------------------------------------------------------- roles + weeks --- */
  var ROLES = [];       /* {key, label, project, hrs:{wkLabel:h}} */
  function readRoles() {
    var tbl = $("roles-table");
    if (!tbl) return;
    var rows = tbl.querySelectorAll("tr.demand-main");
    var comments = tbl.querySelectorAll("tr.comment-row .ct-mount, tr.comment-row textarea");
    Array.prototype.forEach.call(rows, function (tr, i) {
      var roleEl = tr.querySelector(".demand-role");
      var projEl = tr.querySelector(".demand-proj");
      var c = comments[i];
      var rk = c ? (c.dataset.ctKey || ("r:" + (c.dataset.rk || ""))) : ("r:" + slug(roleEl ? roleEl.textContent : i));
      var hrs = {};
      Array.prototype.forEach.call(tr.querySelectorAll("td.wk [data-h]"), function (cell, j) {
        hrs[GRID.weeks[j]] = parseFloat(cell.dataset.h) || 0;
      });
      var label = roleEl ? roleEl.textContent.replace(/\s+/g, " ").trim() : "Open role";
      ROLES.push({ key: rk, label: label, project: projEl ? projEl.textContent.trim() : "", hrs: hrs, row: tr });
    });
  }

  /* --------------------------------------------------------------- store --- */
  function threadRef(key) { return S.db.doc("threads/" + key.replace(/[^A-Za-z0-9_.:~@+-]/g, "-")); }

  function writeErr(err, where) {
    var code = (err && err.code) || "error";
    var msg = code === "quota_exceeded"
      ? "The shared store is full - clear out old items before adding more."
      : "Couldn't save (" + code + "). You may not have edit access to this page.";
    flashDrawerError(msg + (where ? " [" + where + "]" : ""));
  }

  function addComment(key, text, status, extra) {
    if (!S.db) return Promise.resolve();
    var t = S.threads[key] || { label: subjectLabel(key), kind: subjectKind(key), comments: [] };
    var list = (t.comments || []).slice();
    list.push({
      id: uid(), text: text, author: S.author || "Unattributed",
      ts: Date.now(), week: THIS_WEEK, status: status || "note",
      ref: (extra && extra.ref) || null
    });
    if (list.length > 300) list = list.slice(list.length - 300);
    return threadRef(key).set({
      label: subjectLabel(key), kind: subjectKind(key), comments: list,
      seeded: !!t.seeded, updated: Date.now()
    }).catch(function (e) { writeErr(e, "comment"); });
  }

  /* legacy single-textarea role comments -> first comment of that thread */
  function seedLegacy(key) {
    if (!S.db || key.indexOf("r:") !== 0) return;
    var t = S.threads[key];
    if (t && (t.seeded || (t.comments && t.comments.length))) return;
    var rk = key.slice(2);
    S.db.doc("role_comments/" + rk).get().then(function (snap) {
      if (!snap.exists) return;
      var body = snap.data() || {};
      var txt = String(body.text || "").trim();
      var cur = S.threads[key];
      if (cur && (cur.seeded || (cur.comments && cur.comments.length))) return;
      var comments = txt ? [{
        id: uid(), text: txt, author: "(carried over)",
        ts: body.ts || Date.now(), week: mondayISO(new Date(body.ts || Date.now())),
        status: "note", ref: null
      }] : [];
      return threadRef(key).set({
        label: subjectLabel(key), kind: "role", comments: comments,
        seeded: true, updated: Date.now()
      });
    }).catch(function () {});
  }

  /* ------------------------------------------------------------- drawer ---- */
  var drawer, scrim, drBody, drTitle, drKind, drWeekSel, drErr, composeBox, composeStatus;
  var showEarlier = false;

  function buildDrawer() {
    scrim = el("div", "ct-scrim");
    scrim.hidden = true;
    scrim.addEventListener("click", closeDrawer);

    drawer = el("div", "ct-drawer");
    drawer.hidden = true;
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-label", "Comment history");

    var head = el("div", "ct-dr-head");
    head.style.position = "relative";
    drKind = el("div", "ct-dr-kind", "");
    drTitle = el("div", "ct-dr-title", "");
    var close = el("button", "ct-dr-close", "×");
    close.type = "button";
    close.title = "Close";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", closeDrawer);
    var tools = el("div", "ct-dr-tools");
    drWeekSel = el("select", "mlog-select");
    drWeekSel.setAttribute("aria-label", "Filter this thread by meeting week");
    drWeekSel.addEventListener("change", function () { renderDrawer(); });
    var actBtn = el("button", "ct-ghost", "+ Action item");
    actBtn.type = "button";
    actBtn.addEventListener("click", function () { toggleForm("action"); });
    var allocBtn = el("button", "ct-ghost", "+ Allocation");
    allocBtn.type = "button";
    allocBtn.addEventListener("click", function () { toggleForm("alloc"); });
    tools.appendChild(drWeekSel); tools.appendChild(actBtn); tools.appendChild(allocBtn);
    head.appendChild(drKind); head.appendChild(drTitle); head.appendChild(close); head.appendChild(tools);

    drBody = el("div", "ct-dr-body");

    var foot = el("div", "ct-dr-foot ct-compose");
    composeBox = el("textarea");
    composeBox.placeholder = "Add a comment - kept in this thread and tagged with this week's meeting...";
    composeBox.setAttribute("aria-label", "New comment");
    composeBox.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); postComment(); }
    });
    var row = el("div", "ct-compose-row");
    composeStatus = el("select", "mlog-select");
    composeStatus.setAttribute("aria-label", "Status for this comment");
    STATUSES.forEach(function (s) {
      var o = el("option", null, s[1]); o.value = s[0]; composeStatus.appendChild(o);
    });
    var post = el("button", "ct-primary", "Comment");
    post.type = "button";
    post.addEventListener("click", postComment);
    row.appendChild(composeStatus); row.appendChild(post);
    drErr = el("div", "ct-err"); drErr.hidden = true;
    foot.appendChild(composeBox); foot.appendChild(row); foot.appendChild(drErr);

    drawer.appendChild(head); drawer.appendChild(drBody); drawer.appendChild(foot);
    /* mount inside .viz-root so the dashboard's colour tokens apply; position:
       fixed still resolves against the viewport (no transformed ancestor). */
    var host = document.querySelector(".viz-root") || document.body;
    host.appendChild(scrim); host.appendChild(drawer);

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && !drawer.hidden) closeDrawer();
    });
  }

  function flashDrawerError(msg) {
    if (!drErr) return;
    drErr.hidden = false; drErr.textContent = msg;
    setTimeout(function () { drErr.hidden = true; }, 6000);
  }

  function openDrawer(key) {
    S.openKey = key;
    showEarlier = false;
    formOpen = null;
    if (drawer.hidden) { drawer.hidden = false; scrim.hidden = false; }
    seedLegacy(key);
    renderDrawer();
    setTimeout(function () { composeBox.focus(); }, 30);
  }
  function closeDrawer() {
    drawer.hidden = true; scrim.hidden = true; S.openKey = null; formOpen = null;
  }

  function postComment() {
    var txt = (composeBox.value || "").trim();
    if (!txt) return;
    if (!requireAuthor()) return;
    if (!S.db) { flashDrawerError(OFFLINE); return; }
    composeBox.value = "";
    addComment(S.openKey, txt, composeStatus.value);
  }

  function requireAuthor() {
    if (S.author) return true;
    var inp = $("mlog-author");
    flashDrawerError("Add your name in the Meeting Log header first, so comments are attributed.");
    if (inp) { inp.focus(); }
    return false;
  }

  var formOpen = null;
  function toggleForm(which) {
    formOpen = (formOpen === which) ? null : which;
    renderDrawer();
  }

  function renderDrawer() {
    if (!S.openKey || drawer.hidden) return;
    var key = S.openKey;
    var t = S.threads[key] || { comments: [] };
    var comments = (t.comments || []).slice().sort(function (a, b) { return b.ts - a.ts; });

    drKind.textContent = ({ consultant: "Consultant", role: "Open role", account: "Client account",
                            project: "Project", section: "Section" })[subjectKind(key)] || "Subject";
    drTitle.textContent = subjectLabel(key);

    /* week filter options for this thread */
    var weeks = {};
    comments.forEach(function (c) { weeks[c.week || "?"] = 1; });
    var wkList = Object.keys(weeks).sort().reverse();
    var prev = drWeekSel.value;
    clear(drWeekSel);
    var all = el("option", null, "All weeks"); all.value = "all"; drWeekSel.appendChild(all);
    wkList.forEach(function (w) {
      var o = el("option", null, weekLabelLong(w) + (w === THIS_WEEK ? " (this week)" : ""));
      o.value = w; drWeekSel.appendChild(o);
    });
    drWeekSel.value = (prev && (prev === "all" || weeks[prev])) ? prev : "all";

    clear(drBody);

    /* forms */
    if (formOpen === "action") drBody.appendChild(actionForm(key));
    if (formOpen === "alloc") drBody.appendChild(allocForm(key));

    /* linked items */
    var acts = S.actions.filter(function (a) { return a.key === key && !a.done; });
    var alcs = S.allocs.filter(function (a) { return a.key === key && a.status === "proposed"; });
    if (acts.length || alcs.length) {
      var box = el("div", "ct-form");
      box.appendChild(el("h4", null, "Open on this item"));
      acts.forEach(function (a) { box.appendChild(actionRow(a, true)); });
      alcs.forEach(function (a) { box.appendChild(allocRow(a, true)); });
      drBody.appendChild(box);
    }

    if (!comments.length) {
      drBody.appendChild(el("div", "mlog-empty",
        S.offline ? OFFLINE : "No comments yet on " + subjectLabel(key) + "."));
      return;
    }

    var filter = drWeekSel.value;
    var shown = filter === "all" ? comments : comments.filter(function (c) { return c.week === filter; });
    var groups = [];
    var byWeek = {};
    shown.forEach(function (c) {
      var w = c.week || "?";
      if (!byWeek[w]) { byWeek[w] = []; groups.push(w); }
      byWeek[w].push(c);
    });
    groups.sort().reverse();

    var hiddenCount = 0;
    groups.forEach(function (w, gi) {
      var older = (filter === "all") && w < THIS_WEEK && gi > 0;
      if (older && !showEarlier) { hiddenCount += byWeek[w].length; return; }
      var h = el("div", "ct-wk-head",
        weekLabelLong(w) + (w === THIS_WEEK ? " · this week" : ""));
      drBody.appendChild(h);
      byWeek[w].forEach(function (c) { drBody.appendChild(commentNode(c, w)); });
    });
    if (hiddenCount) {
      var more = el("button", "ct-more", "Show " + hiddenCount + " earlier comment" +
        (hiddenCount === 1 ? "" : "s"));
      more.type = "button";
      more.addEventListener("click", function () { showEarlier = true; renderDrawer(); });
      drBody.appendChild(more);
    }
  }

  function commentNode(c) {
    var n = el("div", "ct-cmt");
    var meta = el("div", "ct-cmt-meta");
    meta.appendChild(el("span", "ct-cmt-author", c.author || "Unattributed"));
    meta.appendChild(document.createTextNode(" · " + stamp(c.ts)));
    if (c.status && c.status !== "note") {
      meta.appendChild(el("span", "ct-st ct-st-" + c.status + "-b", STATUS_LABEL[c.status] || c.status));
    }
    n.appendChild(meta);
    n.appendChild(el("div", "ct-cmt-text", c.text));
    return n;
  }

  /* --------------------------------------------------------- action items -- */
  function actionForm(key) {
    var f = el("div", "ct-form");
    f.appendChild(el("h4", null, "New action item"));
    var text = field(f, "What", "input", { placeholder: "e.g. confirm Proceed IX start date with the client" });
    var owner = field(f, "Owner", "input", { placeholder: "name", value: S.author || "" });
    var due = field(f, "Due", "input", { type: "date" });
    var row = el("div", "ct-compose-row");
    var save = el("button", "ct-primary", "Add action item");
    save.type = "button";
    save.addEventListener("click", function () {
      var t = (text.value || "").trim();
      if (!t) { text.focus(); return; }
      if (!requireAuthor()) return;
      S.db.collection("actions").add({
        text: t, owner: (owner.value || "").trim() || "unassigned",
        due: due.value || "", done: false, doneTs: 0,
        key: key, label: subjectLabel(key), kind: subjectKind(key),
        week: THIS_WEEK, author: S.author, ts: Date.now()
      }).then(function () {
        addComment(key, "Action item: " + t +
          ((owner.value || "").trim() ? " - " + owner.value.trim() : "") +
          (due.value ? " (due " + due.value + ")" : ""), "action");
        formOpen = null; renderDrawer();
      }).catch(function (e) { writeErr(e, "action"); });
    });
    var cancel = el("button", "ct-ghost", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", function () { formOpen = null; renderDrawer(); });
    row.appendChild(save); row.appendChild(cancel);
    f.appendChild(row);
    setTimeout(function () { text.focus(); }, 20);
    return f;
  }

  function field(parent, label, tag, attrs) {
    var wrap = el("div", "ct-field");
    wrap.appendChild(el("label", null, label));
    var input = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "value") input.value = attrs[k]; else input.setAttribute(k, attrs[k]);
    });
    wrap.appendChild(input);
    parent.appendChild(wrap);
    return input;
  }

  function actionRow(a, compact) {
    var r = el("div", "mlog-row" + (a.done ? " mlog-done" : ""));
    var main = el("div", "mlog-row-main");
    var title = el("div", "mlog-row-title");
    if (!compact) {
      title.appendChild(el("span", "subject-tag", subjectKindShort(a.kind)));
    }
    title.appendChild(document.createTextNode(a.text));
    main.appendChild(title);
    var sub = el("div", "mlog-row-sub");
    var bits = [a.owner || "unassigned"];
    if (!compact) bits.push(a.label || "");
    bits.push("raised " + weekLabel(a.week));
    sub.appendChild(document.createTextNode(bits.filter(Boolean).join(" · ") + " "));
    if (a.due) {
      var days = Math.floor((new Date(a.due + "T12:00:00") - new Date()) / 86400000);
      var cls = days < 0 ? "due-chip due-late" : (days <= 3 ? "due-chip due-soon" : "due-chip");
      sub.appendChild(el("span", cls, "due " + weekLabel(a.due) + (days < 0 ? " · overdue" : "")));
    }
    main.appendChild(sub);
    var side = el("div", "mlog-row-side");
    var done = el("button", "mlog-sm", a.done ? "Reopen" : "Done");
    done.type = "button";
    done.addEventListener("click", function () {
      S.db.doc("actions/" + a.id).update({ done: !a.done, doneTs: a.done ? 0 : Date.now() })
        .catch(function (e) { writeErr(e, "action"); });
    });
    side.appendChild(done);
    if (!compact) {
      var go = el("button", "mlog-sm", "Open");
      go.type = "button";
      go.addEventListener("click", function () { openDrawer(a.key); });
      side.appendChild(go);
    }
    var del = el("button", "mlog-sm", "×");
    del.type = "button"; del.title = "Remove";
    del.addEventListener("click", function () {
      S.db.doc("actions/" + a.id).delete().catch(function (e) { writeErr(e, "action"); });
    });
    side.appendChild(del);
    r.appendChild(main); r.appendChild(side);
    return r;
  }

  function subjectKindShort(k) {
    return ({ consultant: "person", role: "role", account: "client", project: "project",
              section: "section" })[k] || "note";
  }

  /* ---------------------------------------------------------- allocations -- */
  function allocForm(key) {
    var f = el("div", "ct-form");
    var head = el("h4", null, "Propose an allocation");
    f.appendChild(head);

    var kind = subjectKind(key);
    var changeSel = field(f, "Change", "select", {});
    [["add", "Assign to a project"], ["remove", "Remove from a project"]].forEach(function (o) {
      var op = el("option", null, o[1]); op.value = o[0]; changeSel.appendChild(op);
    });
    var consInput = field(f, "Consultant", "input",
      { placeholder: "start typing a name", list: "ct-cons-list",
        value: kind === "consultant" ? subjectLabel(key) : "" });
    if (!$("ct-cons-list")) {
      var dl = el("datalist"); dl.id = "ct-cons-list";
      GRID.names.forEach(function (n) { var o = el("option"); o.value = n; dl.appendChild(o); });
      document.body.appendChild(dl);
    }

    var roleSel = field(f, "Against", "select", {});
    var o0 = el("option", null, "Other project (not an open role)"); o0.value = ""; roleSel.appendChild(o0);
    ROLES.forEach(function (r) {
      var o = el("option", null, r.label); o.value = r.key; roleSel.appendChild(o);
    });
    if (kind === "role") roleSel.value = key;

    var projInput = field(f, "Project", "input",
      { placeholder: "client / project name", list: "ct-proj-list" });
    if (!$("ct-proj-list")) {
      var pl = el("datalist"); pl.id = "ct-proj-list";
      Object.keys(S.subjects).forEach(function (k) {
        if (k.indexOf("p:") !== 0) return;
        var o = el("option"); o.value = S.subjects[k].label; pl.appendChild(o);
      });
      (document.querySelector(".viz-root") || document.body).appendChild(pl);
    }
    var hrs = field(f, "Hours / week", "input", { type: "number", min: "1", max: "60", step: "1", value: "20" });
    var wkFrom = field(f, "From week", "select", {});
    var wkTo = field(f, "Through", "select", {});
    GRID.weeks.forEach(function (w, i) {
      var a = el("option", null, w); a.value = String(i); wkFrom.appendChild(a);
      var b = el("option", null, w); b.value = String(i); wkTo.appendChild(b);
    });
    wkTo.value = String(Math.max(0, GRID.weeks.length - 1));
    var note = field(f, "Note", "input", { placeholder: "optional - why, caveats" });
    var hint = el("div", "ct-hint");
    f.appendChild(hint);

    function isRemove() { return changeSel.value === "remove"; }

    // In remove mode the open-role select is meaningless: you are taking hours off an
    // existing booking, not filling unfilled demand.
    function syncKind() {
      var rem = isRemove();
      head.textContent = rem ? "Propose a removal" : "Propose an allocation";
      var roleRow = roleSel.parentNode;
      if (roleRow) roleRow.hidden = rem;
      if (rem) {
        projInput.removeAttribute("readonly");
        var pl = $("ct-rem-list") || el("datalist");
        pl.id = "ct-rem-list"; pl.textContent = "";
        var cons = (consInput.value || "").trim();
        var bk = cons ? bookedProjects(cons) : {};
        Object.keys(bk).sort().forEach(function (pr) {
          var o = el("option"); o.value = pr; pl.appendChild(o);
        });
        if (!pl.parentNode) (document.querySelector(".viz-root") || document.body).appendChild(pl);
        projInput.setAttribute("list", "ct-rem-list");
        projInput.placeholder = cons ? "project to take them off" : "pick the consultant first";
        if (kind === "project" && !projInput.value) projInput.value = subjectLabel(key);
        syncRemoveHours();
      } else {
        projInput.setAttribute("list", "ct-proj-list");
        projInput.placeholder = "client / project name";
        syncRole();
      }
      hint.textContent = rem
        ? "Saved as a proposed removal: the 8 Week Outlook strikes the hours through, Capacity vs. Need "
          + "shows them freed, and it stays on the Proposed allocations list until someone marks it entered "
          + "in Salesforce. Nothing is changed in Salesforce from here."
        : "Saved as a proposed assignment: it shows on the 8 Week Outlook and in Capacity vs. Need marked "
          + "pending, and stays on the Proposed allocations list until someone marks it entered in Salesforce.";
      save.textContent = rem ? "Propose removal" : "Propose allocation";
    }

    // Prefill hours and the week range from what the consultant is actually booked to.
    function syncRemoveHours() {
      var cons = (consInput.value || "").trim();
      var pr = (projInput.value || "").trim();
      if (!cons || !pr) return;
      var wks = bookedProjects(cons)[pr];
      if (!wks) return;
      var first = -1, last = -1, h = 0;
      GRID.weeks.forEach(function (w, i) {
        if ((wks[w] || 0) > 0) { if (first < 0) first = i; last = i; h = Math.max(h, wks[w]); }
      });
      if (first >= 0) { wkFrom.value = String(first); wkTo.value = String(last); hrs.value = String(h); }
    }

    function syncRole() {
      var r = roleByKey(roleSel.value);
      if (r) {
        projInput.value = r.project || r.label;
        projInput.setAttribute("readonly", "readonly");
        var firstWk = -1, lastWk = -1, h = 0;
        GRID.weeks.forEach(function (w, i) {
          if ((r.hrs[w] || 0) > 0) { if (firstWk < 0) firstWk = i; lastWk = i; h = r.hrs[w]; }
        });
        if (firstWk >= 0) { wkFrom.value = String(firstWk); wkTo.value = String(lastWk); }
        if (h) hrs.value = String(Math.round(h));
      } else {
        if (projInput.hasAttribute("readonly")) projInput.value = "";
        projInput.removeAttribute("readonly");
      }
    }
    roleSel.addEventListener("change", syncRole);

    var row = el("div", "ct-compose-row");
    var save = el("button", "ct-primary", "Propose allocation");
    save.type = "button";
    changeSel.addEventListener("change", syncKind);
    consInput.addEventListener("change", function () { if (isRemove()) syncKind(); });
    projInput.addEventListener("change", function () { if (isRemove()) syncRemoveHours(); });
    if (kind === "project") changeSel.value = "remove";
    syncKind();
    save.addEventListener("click", function () {
      var cons = (consInput.value || "").trim();
      var proj = (projInput.value || "").trim();
      var h = parseFloat(hrs.value) || 0;
      var i0 = parseInt(wkFrom.value, 10), i1 = parseInt(wkTo.value, 10);
      if (!cons) { consInput.focus(); return; }
      if (!proj) { projInput.focus(); return; }
      if (!(h > 0)) { hrs.focus(); return; }
      if (i1 < i0) { var t = i0; i0 = i1; i1 = t; }
      if (!requireAuthor()) return;
      var weeks = GRID.weeks.slice(i0, i1 + 1);
      S.db.collection("allocations").add({
        kind: isRemove() ? "remove" : "add",
        consultant: cons, project: proj,
        roleKey: isRemove() ? "" : (roleSel.value || ""),
        roleLabel: (!isRemove() && roleSel.value) ? (roleByKey(roleSel.value) || {}).label || "" : "",
        hours: h, weeks: weeks, status: "proposed",
        note: (note.value || "").trim(), key: key, label: subjectLabel(key),
        author: S.author, ts: Date.now(), week: THIS_WEEK
      }).then(function () {
        addComment(key, (isRemove() ? "Proposed removal: " + cons + " off " + proj
                                    : "Proposed allocation: " + cons + " → " + proj) + ", " + h +
          " hrs/wk, " + weeks[0] + " through " + weeks[weeks.length - 1] +
          ((note.value || "").trim() ? " - " + note.value.trim() : ""), "action");
        formOpen = null; renderDrawer();
      }).catch(function (e) { writeErr(e, "allocation"); });
    });
    var cancel = el("button", "ct-ghost", "Cancel");
    cancel.type = "button";
    cancel.addEventListener("click", function () { formOpen = null; renderDrawer(); });
    row.appendChild(save); row.appendChild(cancel);
    f.appendChild(row);
    return f;
  }

  /* Current bookings for a consultant, read back off the staff grid's cell tooltips
     ("Sep 28: Ascend - ... (16h); Merz - ... (3.76h)"). Used to prefill a removal so
     the freed hours match what Salesforce actually has, rather than being typed. */
  function bookedProjects(name) {
    var tr = GRID.rowByName[name];
    var out = {};
    if (!tr) return out;
    var cells = tr.querySelectorAll("td.wk .wk-cell");
    Array.prototype.forEach.call(cells, function (cell, i) {
      var t = cell.getAttribute("title") || "";
      var body = t.replace(/^[^:]*:\s*/, "");
      body.split("; ").forEach(function (bit) {
        var m = /^(.*)\s\(([\d.]+)h\)$/.exec(bit.trim());
        if (!m) return;
        out[m[1]] = out[m[1]] || {};
        out[m[1]][GRID.weeks[i]] = parseFloat(m[2]) || 0;
      });
    });
    return out;
  }

  function peopleOnProject(project) {
    var out = [];
    GRID.names.forEach(function (n) {
      if (bookedProjects(n)[project]) out.push(n);
    });
    return out;
  }

  function roleByKey(k) {
    for (var i = 0; i < ROLES.length; i++) if (ROLES[i].key === k) return ROLES[i];
    return null;
  }

  function allocRow(a, compact) {
    var r = el("div", "mlog-row" + (a.status !== "proposed" ? " mlog-done" : ""));
    var main = el("div", "mlog-row-main");
    var title = el("div", "mlog-row-title");
    title.appendChild(el("span", "subject-tag", a.status === "entered" ? "entered" : "pending"));
    if (a.kind === "remove") title.appendChild(el("span", "subject-tag rem-tag", "remove"));
    title.appendChild(document.createTextNode(
      a.consultant + (a.kind === "remove" ? " \u2212 off " : " → ") + a.project));
    main.appendChild(title);
    var sub = a.hours + " hrs/wk · " + (a.weeks || []).join(", ") +
      (a.kind === "remove" ? " · hours freed"
        : (a.roleLabel ? " · against " + a.roleLabel : " · not an open role")) +
      " · " + (a.author || "?") + ", " + weekLabel(a.week);
    main.appendChild(el("div", "mlog-row-sub", sub + (a.note ? " · " + a.note : "")));
    var side = el("div", "mlog-row-side");
    if (a.status === "proposed") {
      var ok = el("button", "mlog-sm", "Entered in Salesforce");
      ok.type = "button";
      ok.addEventListener("click", function () {
        S.db.doc("allocations/" + a.id).update({ status: "entered", enteredTs: Date.now(),
          enteredBy: S.author || "" }).catch(function (e) { writeErr(e, "allocation"); });
      });
      side.appendChild(ok);
    } else {
      var undo = el("button", "mlog-sm", "Reopen");
      undo.type = "button";
      undo.addEventListener("click", function () {
        S.db.doc("allocations/" + a.id).update({ status: "proposed" })
          .catch(function (e) { writeErr(e, "allocation"); });
      });
      side.appendChild(undo);
    }
    if (!compact) {
      var go = el("button", "mlog-sm", "Open");
      go.type = "button";
      go.addEventListener("click", function () { openDrawer(a.key); });
      side.appendChild(go);
    }
    var del = el("button", "mlog-sm", "×");
    del.type = "button"; del.title = "Remove";
    del.addEventListener("click", function () {
      S.db.doc("allocations/" + a.id).delete().catch(function (e) { writeErr(e, "allocation"); });
    });
    side.appendChild(del);
    r.appendChild(main); r.appendChild(side);
    return r;
  }

  /* ------------------------------------------------- allocation overlay ---- */
  function clearOverlay() {
    Array.prototype.forEach.call(document.querySelectorAll(".wk-proj-prop"), function (n) {
      n.parentNode.removeChild(n);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".wk-cell.wk-prop"), function (n) {
      n.classList.remove("wk-prop");
    });
    Array.prototype.forEach.call(document.querySelectorAll(".prop-chip"), function (n) {
      n.parentNode.removeChild(n);
    });
    Array.prototype.forEach.call(document.querySelectorAll("tr.cap-prop-row, tr.cap-prop-gap-row"), function (n) {
      n.parentNode.removeChild(n);
    });
    Array.prototype.forEach.call(document.querySelectorAll("tr.demand-prop-role, tr.demand-prop-total"), function (n) {
      n.parentNode.removeChild(n);
    });
    var note = document.querySelector(".cap-prop-note");
    if (note) note.parentNode.removeChild(note);
  }

  function renderOverlay() {
    clearOverlay();
    var pend = S.allocs.filter(function (a) { return a.status === "proposed"; });
    if (!pend.length) return;

    /* 1. staff grid cells */
    pend.forEach(function (a) {
      var tr = GRID.rowByName[a.consultant];
      if (!tr) return;
      var cells = tr.querySelectorAll("td.wk .wk-cell");
      (a.weeks || []).forEach(function (w) {
        var i = GRID.weeks.indexOf(w);
        if (i < 0 || !cells[i]) return;
        var cell = cells[i];
        cell.classList.add("wk-prop");
        var rem = a.kind === "remove";
        var line = el("div", "wk-proj wk-proj-prop" + (rem ? " wk-proj-rem" : ""),
          (rem ? "\u2212" : "+") + Math.round(a.hours / 40 * 100) + "% " + shortProject(a.project));
        line.title = (rem ? "Proposed removal: " + a.consultant + " off " + a.project
                          : "Proposed: " + a.consultant + " → " + a.project) + " (" + a.hours +
          " hrs/wk), not yet in Salesforce" + (a.note ? " - " + a.note : "");
        cell.appendChild(line);
      });
    });

    /* 2. open-role cards */
    pend.forEach(function (a) {
      if (!a.roleKey || a.kind === "remove") return;
      var r = roleByKey(a.roleKey);
      if (!r || !r.row) return;
      var host = r.row.querySelector(".chip-row") || r.row.querySelector(".col-demand-name");
      if (!host) return;
      var chip = el("span", "prop-chip", "Proposed: " + a.consultant + " · " + a.hours + " h/wk");
      chip.title = "Pending Salesforce entry";
      host.appendChild(chip);
    });

    /* 3. open roles: hours a proposed removal vacates are unfilled work, so they show
          here as a proposed opening with their own total. */
    var rems = pend.filter(function (a) { return a.kind === "remove"; });
    var rtbl = document.getElementById("roles-table");
    var totalRow = rtbl ? rtbl.querySelector("tr.demand-total-row") : null;
    if (rems.length && totalRow) {
      var nW0 = GRID.weeks.length;
      var freed = new Array(nW0).fill(0);
      rems.forEach(function (a) {
        var tr = el("tr", "demand-prop-role");
        var td = el("td", "col-demand-name");
        var h1 = el("div", "demand-role", shortProject(a.project) + ": vacated by " + a.consultant);
        td.appendChild(h1);
        td.appendChild(el("div", "demand-proj", a.project));
        var chips = el("div", "chip-row");
        chips.appendChild(el("span", "prop-chip", "proposed removal \u00b7 pending Salesforce"));
        if (a.note) chips.appendChild(el("span", "chip chip-quiet", a.note));
        td.appendChild(chips);
        tr.appendChild(td);
        for (var j = 0; j < nW0; j++) {
          var on = (a.weeks || []).indexOf(GRID.weeks[j]) >= 0;
          if (on) freed[j] += a.hours;
          var cell = el("td", "wk");
          cell.appendChild(el("div", "wk-cell " + (on ? "wk-demand wk-demand-prop" : "wk-demand-empty"),
                              on ? String(a.hours) : "\u2014"));
          tr.appendChild(cell);
        }
        totalRow.parentNode.insertBefore(tr, totalRow);
      });
      var openNow = readNums(totalRow);
      var t2 = el("tr", "demand-total-row demand-prop-total");
      t2.appendChild(el("td", null, "Total after proposed removals (hrs/wk)"));
      for (var k2 = 0; k2 < nW0; k2++) {
        t2.appendChild(numCell(Math.round((openNow[k2] || 0) + freed[k2]).toLocaleString()));
      }
      totalRow.parentNode.insertBefore(t2, totalRow.nextSibling);
    }

    /* 4. capacity table */
    var tbl = document.querySelector("table.capacity-table");
    if (!tbl) return;
    var gap = tbl.querySelector("tr.cap-gap-row");
    if (!gap) return;
    var openRow = null;
    Array.prototype.forEach.call(tbl.querySelectorAll("tbody tr"), function (tr) {
      var td = tr.querySelector("td");
      if (td && /Open roles/.test(td.textContent)) openRow = tr;
    });
    var nWk = GRID.weeks.length;
    var propRole = new Array(nWk).fill(0), propNew = new Array(nWk).fill(0),
        propRem = new Array(nWk).fill(0);
    pend.forEach(function (a) {
      (a.weeks || []).forEach(function (w) {
        var i = GRID.weeks.indexOf(w);
        if (i < 0) return;
        if (a.kind === "remove") propRem[i] += a.hours;
        else if (a.roleKey) propRole[i] += a.hours;
        else propNew[i] += a.hours;
      });
    });
    var anyRem = propRem.some(function (v) { return v > 0; });
    var openHrs = openRow ? readNums(openRow) : new Array(nWk).fill(0);
    var gapHrs = readNums(gap);

    var r1 = el("tr", "cap-prop-row");
    r1.appendChild(el("td", null, "Proposed assignments (pending Salesforce)"));
    var r0 = null;
    if (anyRem) {
      r0 = el("tr", "cap-prop-row");
      r0.appendChild(el("td", null, "Proposed removals (booked hours vacated)"));
    }
    var r2 = el("tr", "cap-prop-row");
    r2.appendChild(el("td", null, "Unfilled demand after proposed"));
    var r3 = el("tr", "cap-prop-gap-row");
    r3.appendChild(el("td", null, "Surplus / (gap) after proposed"));
    for (var i = 0; i < nWk; i++) {
      var tot = propRole[i] + propNew[i];
      r1.appendChild(numCell(tot ? tot.toLocaleString() : "-"));
      if (r0) r0.appendChild(numCell(propRem[i] ? "\u2212" + Math.round(propRem[i]).toLocaleString() : "-"));
      // vacated hours are still work to be done: they move from booked to unfilled
      var rem = Math.max(0, openHrs[i] - propRole[i] + propRem[i]);
      r2.appendChild(numCell(Math.round(rem).toLocaleString()));
      // ...so total need is unchanged by a removal, and the surplus does not move
      var g = gapHrs[i] - propNew[i];
      var c = numCell((g >= 0 ? "+" : "−") + Math.abs(Math.round(g)).toLocaleString());
      c.className += g >= 0 ? " cap-pos" : " cap-neg";
      r3.appendChild(c);
    }
    gap.parentNode.insertBefore(r1, gap.nextSibling);
    if (r0) r1.parentNode.insertBefore(r0, r1.nextSibling);
    (r0 || r1).parentNode.insertBefore(r2, (r0 || r1).nextSibling);
    r2.parentNode.insertBefore(r3, r2.nextSibling);
    var note = el("div", "cap-prop-note",
      "Proposed rows come from the Meeting Log and are not in Salesforce yet. An assignment made against an " +
      "open role reduces unfilled demand without changing total need; one made to any other project adds to " +
      "need, so it lowers the surplus. A proposed removal moves hours from booked to unfilled - the work " +
      "still has to be done by someone, so it appears in Open Roles as vacated and total need and the " +
      "surplus do not move. If the work itself is going away rather than changing hands, close the demand " +
      "line in Salesforce; this page cannot tell the two apart. " +
      "Grid percentages for proposed work assume a 40-hour week.");
    tbl.parentNode.insertBefore(note, tbl.nextSibling);
  }

  function readNums(tr) {
    var out = [];
    Array.prototype.forEach.call(tr.querySelectorAll("td.wk"), function (td) {
      var txt = td.textContent.replace(/\(.*?\)/g, "").replace(/[,\s]/g, "")
        .replace(/−/g, "-").replace(/\+/g, "");
      out.push(parseFloat(txt) || 0);
    });
    return out;
  }
  function numCell(txt) {
    var td = el("td", "wk num", txt);
    return td;
  }
  function shortProject(p) {
    var s = String(p).split(/ - |: |-/)[0].trim();
    return s.length > 14 ? s.slice(0, 13) + "..." : s;
  }

  /* -------------------------------------------------------- what changed --- */
  function buildSnapshot() {
    var snap = { week: THIS_WEEK, ts: Date.now(), gen: "", head: {}, staff: {}, roles: {}, accounts: {} };
    var sub = document.querySelector(".dash-subtitle");
    if (sub) snap.gen = sub.textContent.trim();
    Array.prototype.forEach.call(document.querySelectorAll(".headline-band"), function (b) {
      var label = b.querySelector(".headline-label");
      var figs = b.querySelector(".headline-figs");
      if (label && figs) snap.head[label.textContent.trim()] = figs.textContent.replace(/\s+/g, " ").trim();
    });
    GRID.names.forEach(function (n) {
      var tr = GRID.rowByName[n];
      var badge = tr.querySelector(".util-badge");
      var avg = badge ? parseInt(badge.textContent, 10) : NaN;
      snap.staff[n] = { avg: isNaN(avg) ? null : avg,
                        under: !!(badge && badge.classList.contains("util-badge-under")) };
    });
    ROLES.forEach(function (r) {
      var peak = 0;
      Object.keys(r.hrs).forEach(function (w) { if (r.hrs[w] > peak) peak = r.hrs[w]; });
      snap.roles[r.key] = { label: r.label, peak: peak };
    });
    var pane = $("s3-pane-acct");
    if (pane) {
      Array.prototype.forEach.call(pane.querySelectorAll(".ub-row"), function (row) {
        var nm = row.querySelector(".ub-name"), v = row.querySelector(".ub-val");
        if (!nm || !v) return;
        var under = !!row.querySelector(".ub-under");
        snap.accounts[nm.textContent.trim()] = (under ? -1 : 1) * (parseFloat(v.textContent) || 0);
      });
    }
    return snap;
  }

  function storeSnapshot(snap) {
    if (!S.db) return;
    var ref = S.db.doc("snapshots/" + snap.week);
    ref.get().then(function (d) {
      var body = d.exists ? (d.data() || {}) : null;
      if (!body || body.gen !== snap.gen) ref.set(snap).catch(function () {});
    }).catch(function () {});
  }

  function changeList() {
    var cur = S.curSnap;
    var weeks = Object.keys(S.snaps).filter(function (w) { return w < cur.week; }).sort();
    if (!weeks.length) return null;
    var prev = S.snaps[weeks[weeks.length - 1]];
    var out = [];
    Object.keys(cur.head).forEach(function (k) {
      if (prev.head && prev.head[k] && prev.head[k] !== cur.head[k]) {
        out.push({ cls: "chg-new", b: k, t: prev.head[k] + "  →  " + cur.head[k] });
      }
    });
    var newlyUnder = [], noLongerUnder = [], moved = [];
    Object.keys(cur.staff).forEach(function (n) {
      var c = cur.staff[n], p = prev.staff ? prev.staff[n] : null;
      if (!p) { out.push({ cls: "chg-new", b: n, t: "new on the schedule" }); return; }
      if (c.under && !p.under) newlyUnder.push(n);
      if (!c.under && p.under) noLongerUnder.push(n);
      if (c.avg !== null && p.avg !== null && Math.abs(c.avg - p.avg) >= 8) {
        moved.push({ n: n, d: c.avg - p.avg, from: p.avg, to: c.avg });
      }
    });
    Object.keys(prev.staff || {}).forEach(function (n) {
      if (!cur.staff[n]) out.push({ cls: "chg-down", b: n, t: "no longer on the schedule" });
    });
    newlyUnder.forEach(function (n) {
      out.push({ cls: "chg-down", b: n, t: "now under target across the 8 weeks" });
    });
    noLongerUnder.forEach(function (n) {
      out.push({ cls: "chg-up", b: n, t: "no longer under target" });
    });
    moved.sort(function (a, b) { return Math.abs(b.d) - Math.abs(a.d); }).slice(0, 12).forEach(function (m) {
      out.push({ cls: m.d > 0 ? "chg-up" : "chg-down", b: m.n,
                 t: m.from + "%  →  " + m.to + "% avg" });
    });
    Object.keys(cur.roles).forEach(function (k) {
      if (!prev.roles || !prev.roles[k]) out.push({ cls: "chg-new", b: "New role", t: cur.roles[k].label });
    });
    Object.keys(prev.roles || {}).forEach(function (k) {
      if (!cur.roles[k]) out.push({ cls: "chg-up", b: "Role gone", t: prev.roles[k].label });
    });
    Object.keys(cur.accounts).forEach(function (n) {
      var c = cur.accounts[n], p = (prev.accounts || {})[n];
      if (p === undefined) return;
      if (Math.abs(c - p) >= 15) {
        out.push({ cls: c < p ? "chg-down" : "chg-up", b: n,
                   t: fmtVar(p) + "  →  " + fmtVar(c) + " hrs" });
      }
    });
    return { since: prev.week, items: out };
  }
  function fmtVar(v) { return (v < 0 ? "−" : "+") + Math.abs(v).toFixed(1); }

  /* --------------------------------------------------------- meeting log -- */
  function countsFor() {
    var wk = S.week;
    function inWeek(x) { return wk === "all" || x.week === wk; }
    var acts = S.actions.filter(function (a) { return !a.done; });
    var allocs = S.allocs.filter(function (a) { return a.status === "proposed"; });
    var recent = [];
    Object.keys(S.threads).forEach(function (k) {
      (S.threads[k].comments || []).forEach(function (c) {
        if (inWeek(c)) recent.push({ key: k, c: c });
      });
    });
    recent.sort(function (a, b) { return b.c.ts - a.c.ts; });
    var disc = [];
    Object.keys(S.threads).forEach(function (k) {
      var cs = (S.threads[k].comments || []).slice().sort(function (a, b) { return b.ts - a.ts; });
      for (var i = 0; i < cs.length; i++) {
        if (cs[i].status && cs[i].status !== "note") {
          if (cs[i].status !== "resolved") disc.push({ key: k, c: cs[i] });
          break;
        }
      }
    });
    return { acts: acts, allocs: allocs, recent: recent, disc: disc };
  }

  function renderLog() {
    var pane = $("mlog-pane");
    if (!pane) return;
    var c = countsFor();
    $("n-actions").textContent = c.acts.length;
    $("n-allocs").textContent = c.allocs.length;
    $("n-disc").textContent = c.disc.length;
    $("n-recent").textContent = c.recent.length;
    if ($("n-agenda")) $("n-agenda").textContent = Object.keys(S.agendas).length;

    /* week filter options */
    var sel = $("mlog-week");
    var seen = {};
    Object.keys(S.threads).forEach(function (k) {
      (S.threads[k].comments || []).forEach(function (x) { seen[x.week] = 1; });
    });
    Object.keys(S.snaps).forEach(function (w) { seen[w] = 1; });
    Object.keys(S.agendas).forEach(function (w) { seen[w] = 1; });
    seen[THIS_WEEK] = 1;
    var wks = Object.keys(seen).sort().reverse();
    if (sel.dataset.n !== String(wks.length)) {
      var cur = sel.value;
      clear(sel);
      var all = el("option", null, "All weeks"); all.value = "all"; sel.appendChild(all);
      wks.forEach(function (w) {
        var o = el("option", null, weekLabelLong(w) + (w === THIS_WEEK ? " (this week)" : ""));
        o.value = w; sel.appendChild(o);
      });
      sel.value = seen[cur] || cur === "all" ? cur : "all";
      sel.dataset.n = String(wks.length);
    }

    clear(pane);
    if (S.offline) { pane.appendChild(el("div", "ct-offline", OFFLINE)); return; }
    if (!S.ready) { pane.appendChild(el("div", "mlog-empty", "Loading the shared meeting log...")); return; }

    if (S.tab === "actions") {
      var open = c.acts;
      var done = S.actions.filter(function (a) { return a.done; });
      if (!open.length) pane.appendChild(el("div", "mlog-empty",
        "No open action items. Add one from any comment thread - click the ✎ beside a consultant, role, client or section heading."));
      var byWeek = groupBy(open, function (a) { return a.week; });
      Object.keys(byWeek).sort().reverse().forEach(function (w) {
        pane.appendChild(el("div", "mlog-group-head", "Raised " + weekLabelLong(w) +
          (w === THIS_WEEK ? " · this week" : "")));
        byWeek[w].forEach(function (a) { pane.appendChild(actionRow(a)); });
      });
      if (done.length) {
        pane.appendChild(el("div", "mlog-group-head", "Closed (" + done.length + ")"));
        done.slice(-8).forEach(function (a) { pane.appendChild(actionRow(a)); });
      }
    } else if (S.tab === "allocs") {
      var pend = c.allocs;
      var ent = S.allocs.filter(function (a) { return a.status !== "proposed"; });
      if (!pend.length) pane.appendChild(el("div", "mlog-empty",
        "Nothing proposed. Open a consultant or an open role and use the + Allocation button to assign someone."));
      pend.forEach(function (a) { pane.appendChild(allocRow(a)); });
      if (pend.length) {
        var bar = el("div", "mlog-bar");
        var exp = el("button", "ct-ghost", "Export for Salesforce (CSV)");
        exp.type = "button";
        exp.addEventListener("click", function () { exportAllocs(pend); });
        bar.appendChild(exp);
        bar.appendChild(el("span", "mlog-row-sub",
          "These are not in Salesforce - there is no Salesforce connection on this page yet."));
        pane.appendChild(bar);
      }
      if (ent.length) {
        pane.appendChild(el("div", "mlog-group-head", "Entered in Salesforce (" + ent.length + ")"));
        ent.slice(-10).forEach(function (a) { pane.appendChild(allocRow(a)); });
      }
    } else if (S.tab === "disc") {
      if (!c.disc.length) pane.appendChild(el("div", "mlog-empty",
        'Nothing flagged. Comments marked Watching or Action needed show up here until someone marks them resolved.'));
      c.disc.sort(function (a, b) { return b.c.ts - a.c.ts; }).forEach(function (x) {
        pane.appendChild(commentRow(x.key, x.c));
      });
    } else if (S.tab === "recent") {
      if (!c.recent.length) pane.appendChild(el("div", "mlog-empty",
        S.week === "all" ? "No comments yet." : "No comments in that week."));
      var g = groupBy(c.recent, function (x) { return x.c.week; });
      Object.keys(g).sort().reverse().forEach(function (w) {
        pane.appendChild(el("div", "mlog-group-head", weekLabelLong(w) +
          (w === THIS_WEEK ? " · this week" : "")));
        g[w].slice(0, 40).forEach(function (x) { pane.appendChild(commentRow(x.key, x.c)); });
      });
    } else if (S.tab === "agenda") {
      var aw = Object.keys(S.agendas).filter(function (w) { return S.week === "all" || w === S.week; }).sort().reverse();
      if (!aw.length) pane.appendChild(el("div", "mlog-empty",
        S.week === "all" ? "No archived agendas yet - each weekly refresh files the previous meeting's agenda here."
                         : "No archived agenda for that week."));
      aw.forEach(function (w) {
        var a = S.agendas[w] || {};
        var items = (a.items || []).slice().sort(function (x, y) { return (x.order || 0) - (y.order || 0); });
        pane.appendChild(el("div", "mlog-group-head", "Meeting agenda · " + weekLabelLong(w) +
          (w === THIS_WEEK ? " · this week" : "") + " · " + items.filter(function (i) { return i.done; }).length +
          " of " + items.length + " done"));
        var ol = el("ol", "mlog-agenda-list");
        items.forEach(function (i) {
          var li = el("li", "mlog-agenda-item" + (i.done ? " mlog-agenda-done" : ""));
          li.appendChild(el("span", "mlog-agenda-mark", i.done ? "✓" : "○"));
          li.appendChild(el("span", "mlog-agenda-text", i.text || ""));
          ol.appendChild(li);
        });
        pane.appendChild(ol);
      });
    } else if (S.tab === "changed") {
      var ch = S.curSnap ? changeList() : null;
      if (!ch) {
        pane.appendChild(el("div", "mlog-empty",
          "No earlier build on file yet - this week's figures become the baseline, and next week's refresh will list what moved."));
      } else if (!ch.items.length) {
        pane.appendChild(el("div", "mlog-empty",
          "Nothing material moved since " + weekLabelLong(ch.since) + "."));
      } else {
        pane.appendChild(el("div", "mlog-group-head", "Since " + weekLabelLong(ch.since)));
        var list = el("div", "chg-list");
        ch.items.forEach(function (i) {
          var n = el("div", "chg " + i.cls);
          n.appendChild(el("span", "chg-b", i.b + ": "));
          n.appendChild(document.createTextNode(i.t));
          list.appendChild(n);
        });
        pane.appendChild(list);
      }
    }
  }

  function commentRow(key, c) {
    var r = el("div", "mlog-row");
    var main = el("div", "mlog-row-main");
    var title = el("div", "mlog-row-title");
    title.appendChild(el("span", "subject-tag", subjectKindShort(subjectKind(key))));
    title.appendChild(document.createTextNode(subjectLabel(key)));
    if (c.status && c.status !== "note") {
      title.appendChild(el("span", "ct-st ct-st-" + c.status + "-b", STATUS_LABEL[c.status] || c.status));
    }
    main.appendChild(title);
    main.appendChild(el("div", "mlog-row-sub", (c.author || "?") + " · " + stamp(c.ts)));
    main.appendChild(el("div", "mlog-row-title", c.text));
    var side = el("div", "mlog-row-side");
    var go = el("button", "mlog-sm", "Open");
    go.type = "button";
    go.addEventListener("click", function () { openDrawer(key); });
    side.appendChild(go);
    r.appendChild(main); r.appendChild(side);
    return r;
  }

  function groupBy(arr, fn) {
    var o = {};
    arr.forEach(function (x) { var k = fn(x) || "?"; (o[k] = o[k] || []).push(x); });
    return o;
  }

  function exportAllocs(list) {
    var rows = [["Consultant", "Project", "Against open role", "Hours per week",
                 "First week", "Last week", "Proposed by", "Meeting week", "Note"]];
      rows[0].splice(0, 0, "Change");
    list.forEach(function (a) {
      var w = a.weeks || [];
      rows.push([a.kind === "remove" ? "REMOVE" : "ADD",
                 a.consultant, a.project, a.roleLabel || "", a.hours,
                 w[0] || "", w[w.length - 1] || "", a.author || "", a.week || "", a.note || ""]);
    });
    var csv = rows.map(function (r) {
      return r.map(function (v) {
        v = String(v === undefined || v === null ? "" : v);
        return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
      }).join(",");
    }).join("\n");
    var pane = $("mlog-pane");
    var box = el("div", "ct-form");
    box.appendChild(el("h4", null, "Proposed allocations - copy into Salesforce"));
    var ta = el("textarea", "ct-export");
    ta.value = csv;
    ta.readOnly = true;
    box.appendChild(ta);
    var row = el("div", "ct-compose-row");
    var copy = el("button", "ct-primary", "Copy");
    copy.type = "button";
    copy.addEventListener("click", function () {
      ta.select();
      var done = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(csv); done = true;
        }
      } catch (e) {}
      copy.textContent = done ? "Copied" : "Select all and copy";
      setTimeout(function () { copy.textContent = "Copy"; }, 2500);
    });
    row.appendChild(copy);
    box.appendChild(row);
    pane.appendChild(box);
    ta.focus(); ta.select();
  }

  /* ----------------------------------------------------------- badges ----- */
  function renderBadges() {
    Array.prototype.forEach.call(document.querySelectorAll(".ct-btn"), function (b) {
      var key = b.dataset.ctKey;
      var t = S.threads[key];
      var n = t && t.comments ? t.comments.length : 0;
      var cnt = b.querySelector(".ct-count");
      if (cnt) cnt.textContent = n ? String(n) : "";
      b.classList.toggle("ct-has", n > 0);
      ["watch", "action", "resolved"].forEach(function (s) { b.classList.remove("ct-st-" + s); });
      if (n) {
        var cs = t.comments.slice().sort(function (a, b2) { return b2.ts - a.ts; });
        for (var i = 0; i < cs.length; i++) {
          if (cs[i].status && cs[i].status !== "note") { b.classList.add("ct-st-" + cs[i].status); break; }
        }
      }
      var open = S.actions.filter(function (a) { return a.key === key && !a.done; }).length;
      b.title = (n ? n + " comment" + (n === 1 ? "" : "s") : "No comments yet") +
        (open ? " · " + open + " open action" + (open === 1 ? "" : "s") : "") +
        " - " + subjectLabel(key);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".ct-mount"), function (m) {
      var key = m.dataset.ctKey;
      var t = S.threads[key];
      var cs = (t && t.comments ? t.comments.slice() : []).sort(function (a, b) { return b.ts - a.ts; });
      clear(m);
      if (!cs.length) {
        m.appendChild(el("div", "ct-mount-empty",
          S.offline ? OFFLINE : "No comments yet - click to add one."));
      } else {
        cs.slice(0, 2).forEach(function (c) {
          var line = el("div", "ct-mount-line");
          line.appendChild(el("span", "ct-mount-meta", c.author + " · " + weekLabel(c.week) + " · "));
          line.appendChild(document.createTextNode(c.text.length > 180 ? c.text.slice(0, 179) + "..." : c.text));
          if (c.status && c.status !== "note") {
            line.appendChild(el("span", "ct-st ct-st-" + c.status + "-b", STATUS_LABEL[c.status]));
          }
          m.appendChild(line);
        });
      }
      var b = el("button", "ct-open", cs.length > 2
        ? "Open thread · " + cs.length + " comments"
        : (cs.length ? "Open thread" : "Add a comment"));
      b.type = "button";
      b.addEventListener("click", function (ev) {
      ev.stopPropagation();
      ev.preventDefault();
      openDrawer(key);
    });
      m.appendChild(b);
    });
  }

  // Each part renders independently: a throw in one (a malformed stored document,
  // a browser quirk) used to take the whole page's live updates down with it and
  // leave the UI stuck on its last good render with no visible error. Isolate
  // them and say so in the console instead of failing silently.
  function renderAll() {
    [["badges", renderBadges], ["log", renderLog],
     ["overlay", renderOverlay], ["drawer", renderDrawer]].forEach(function (p) {
      try { p[1](); }
      catch (e) { try { console.error("[staffing] render " + p[0] + " failed:", e); } catch (e2) {} }
    });
  }

  /* -------------------------------------------------------------- boot ---- */
  function bootUI() {
    wireStaffGrid();
    wireVarianceRows();
    wireProjectRows();
    wireSectionHeads();
    wireMounts();
    wireExistingButtons();
    readRoles();
    buildDrawer();

    var authorInput = $("mlog-author");
    if (authorInput) {
      authorInput.value = S.author;
      authorInput.addEventListener("change", function () {
        S.author = (authorInput.value || "").trim();
        try { window.localStorage.setItem("ct.author", S.author); } catch (e) {}
      });
      authorInput.addEventListener("blur", function () {
        S.author = (authorInput.value || "").trim();
        try { window.localStorage.setItem("ct.author", S.author); } catch (e) {}
      });
    }
    var tabs = $("mlog-tabs");
    if (tabs) {
      tabs.addEventListener("click", function (ev) {
        var b = ev.target && ev.target.closest ? ev.target.closest(".mlog-tab") : null;
        if (!b) return;
        S.tab = b.dataset.pane;
        Array.prototype.forEach.call(tabs.querySelectorAll(".mlog-tab"), function (x) {
          x.classList.toggle("mlog-tab-active", x === b);
        });
        renderLog();
      });
    }
    var wk = $("mlog-week");
    if (wk) wk.addEventListener("change", function () { S.week = wk.value; renderLog(); });
  }

  function bootStore() {
    if (!(window.claude && typeof window.claude.use === "function")) { S.offline = true; renderAll(); return; }
    window.claude.use("db").then(function (db) {
      if (!db) { S.offline = true; renderAll(); return; }
      S.db = db;
      S.ready = true;

      db.collection("threads").onSnapshot(function (snap) {
        var next = {};
        snap.docs.forEach(function (d) {
          if (!d.exists) return;
          var b = d.data() || {};
          next[d.id] = { label: b.label || d.id, kind: b.kind || "note",
                         comments: Array.isArray(b.comments) ? b.comments : [],
                         seeded: !!b.seeded };
          if (!S.subjects[d.id]) S.subjects[d.id] = { label: next[d.id].label, kind: next[d.id].kind };
        });
        S.threads = next;
        renderAll();
      }, function () { S.offline = true; renderAll(); });

      // withId: snapshot bodies are FROZEN and this file runs in strict mode, so
      // `d.data().id = d.id` throws a TypeError - which kills the whole snapshot
      // handler before renderAll() and leaves the UI frozen on its last good
      // render. It went unnoticed for weeks because actions and allocations were
      // both empty, so .map() never touched a real document; the first proposed
      // removal written into the store made every later render a no-op. Copy
      // first, always. Local test stubs hand back plain objects and will NOT
      // reproduce this - only the live page freezes them.
      function withId(d) {
        var b = {}, src = d.data() || {};
        Object.keys(src).forEach(function (k) { b[k] = src[k]; });
        b.id = d.id;
        return b;
      }

      db.collection("actions").onSnapshot(function (snap) {
        S.actions = snap.docs.filter(function (d) { return d.exists; }).map(withId)
          .sort(function (a, b) { return (a.due || "9999") < (b.due || "9999") ? -1 : 1; });
        renderAll();
      }, function () {});

      db.collection("allocations").onSnapshot(function (snap) {
        S.allocs = snap.docs.filter(function (d) { return d.exists; }).map(withId)
          .sort(function (a, b) { return (a.ts || 0) - (b.ts || 0); });
        renderAll();
      }, function () {});

      S.curSnap = buildSnapshot();
      storeSnapshot(S.curSnap);
      db.collection("snapshots").onSnapshot(function (snap) {
        var m = {};
        snap.docs.forEach(function (d) { if (d.exists) m[d.id] = d.data() || {}; });
        S.snaps = m;
        renderLog();
      }, function () {});
      db.collection("agenda_archive").onSnapshot(function (snap) {
        var m = {};
        snap.docs.forEach(function (d) { if (d.exists) m[d.id] = d.data() || {}; });
        S.agendas = m;
        renderLog();
      }, function () {});

      renderAll();
    }).catch(function () { S.offline = true; renderAll(); });
  }

  function boot() {
    bootUI();
    S.curSnap = buildSnapshot();
    renderAll();
    bootStore();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
</script>"""
