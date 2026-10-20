#!/usr/bin/env python3
"""Adds the Action Items panel (Version 36 -> 37).

Mark: "add an action items list that allows me to add action items in one meeting
so they show up in the next meeting."

The page already had action items - but only reachable from inside a comment
thread (the drawer's "+ Action item"), and only visible in the Meeting Log tab.
This puts them on the page as their own panel, under the agenda, and writes to the
SAME `actions` collection in the artifact's shared store, so:

  - items added here appear in the Meeting Log and vice versa;
  - they are tagged with the meeting week they were raised in and simply stay
    open until someone checks them off - the panel groups anything raised before
    this week under "Carried over", which is the whole point;
  - nothing is lost on the weekly data refresh, because the store is not touched
    by a republish.

Document shape (unchanged, so both writers interoperate):
  {text, owner, due, done, doneTs, key, label, kind, week, author, ts}

    python3 add_action_items.py v36_full.html v37_full.html
"""
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "v36_full.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else "v37_full.html"

PANEL = """<section class="agenda-panel act-panel" id="action-items">
  <h2 class="sec-head">Action Items <span class="agenda-sub">shared &mdash; what you add in one meeting stays here for the next one until it is checked off</span></h2>
  <div id="act-status" class="agenda-note">Loading the shared action items&hellip;</div>
  <div id="act-list" hidden></div>
  <div id="act-form" class="act-form" hidden>
    <input id="act-text" type="text" maxlength="300" placeholder="Add an action item and press Enter&hellip;" aria-label="New action item">
    <input id="act-owner" type="text" maxlength="60" placeholder="owner" aria-label="Owner">
    <input id="act-due" type="date" aria-label="Due date">
    <button id="act-add" type="button">Add</button>
    <label class="act-done-toggle"><input type="checkbox" id="act-show-done"> show completed</label>
  </div>
</section>"""

SCRIPT = """<script>
/* Action Items (Mark, Sep 15 2026): a panel over the same `actions` collection the
   comment drawer and the Meeting Log already use, so an item raised in one meeting
   is still here at the next one. Items are tagged with the Monday of the week they
   were raised; anything older than this week groups under "Carried over". */
(function () {
  "use strict";
  var MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var OFFLINE = "Action items live on the live dashboard page on claude.ai - this copy can't reach them.";
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt !== undefined && txt !== null) n.textContent = txt;
    return n;
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function isoOf(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function mondayISO(d) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
    return isoOf(x);
  }
  function weekLabel(iso) {
    var p = String(iso || "").split("-");
    if (p.length !== 3) return "an earlier meeting";
    return MON[parseInt(p[1], 10) - 1] + " " + parseInt(p[2], 10);
  }
  var THIS_WEEK = mondayISO(new Date());

  var statusEl = $("act-status"), listEl = $("act-list"), formEl = $("act-form");
  var textEl = $("act-text"), ownerEl = $("act-owner"), dueEl = $("act-due");
  var addBtn = $("act-add"), showDone = $("act-show-done");
  if (!statusEl) return;
  if (!(window.claude && typeof window.claude.use === "function")) {
    statusEl.textContent = OFFLINE;
    return;
  }

  var author = "";
  try { author = window.localStorage.getItem("ct.author") || ""; } catch (e) {}

  window.claude.use("db").then(function (db) {
    if (!db) { statusEl.textContent = OFFLINE; return; }
    var col = db.collection("actions");
    var items = [];

    function flash(msg) {
      statusEl.hidden = false;
      statusEl.textContent = msg;
      setTimeout(function () { if (items.length) statusEl.hidden = true; }, 4000);
    }
    function onErr(err) {
      flash((err && err.code) === "quota_exceeded"
        ? "The shared store is full - clear some completed items first."
        : "Couldn't save that (" + ((err && err.code) || "error") + "). You may not have edit access.");
    }

    function dueChip(a) {
      if (!a.due) return null;
      var days = Math.floor((new Date(a.due + "T12:00:00") - new Date()) / 86400000);
      var cls = days < 0 ? "due-chip due-late" : (days <= 3 ? "due-chip due-soon" : "due-chip");
      return el("span", cls, "due " + weekLabel(a.due) + (days < 0 ? " · overdue" : ""));
    }

    function row(a) {
      var r = el("div", "act-row" + (a.done ? " act-done" : ""));
      var cb = document.createElement("input");
      cb.type = "checkbox"; cb.checked = !!a.done;
      cb.setAttribute("aria-label", a.done ? "Reopen" : "Mark done");
      cb.addEventListener("change", function () {
        col.doc(a.id).update({ done: cb.checked, doneTs: cb.checked ? Date.now() : 0 })
          .catch(onErr);
      });
      var main = el("div", "act-main");
      main.appendChild(el("div", "act-text", a.text));
      var sub = el("div", "act-sub");
      sub.appendChild(document.createTextNode(
        (a.owner || "unassigned") + " · raised " + weekLabel(a.week) +
        (a.label && a.kind !== "section" ? " · " + a.label : "") + " "));
      var chip = dueChip(a);
      if (chip) sub.appendChild(chip);
      main.appendChild(sub);
      var del = el("button", "act-x", "×");
      del.type = "button"; del.title = "Remove";
      del.addEventListener("click", function () { col.doc(a.id).delete().catch(onErr); });
      r.appendChild(cb); r.appendChild(main); r.appendChild(del);
      return r;
    }

    function group(title, list, note) {
      if (!list.length) return null;
      var g = el("div", "act-group");
      var h = el("div", "act-group-head", title + " (" + list.length + ")");
      if (note) h.appendChild(el("span", "act-group-note", note));
      g.appendChild(h);
      list.forEach(function (a) { g.appendChild(row(a)); });
      return g;
    }

    function render() {
      while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
      var open = items.filter(function (a) { return !a.done; });
      var done = items.filter(function (a) { return a.done; });
      var carried = open.filter(function (a) { return (a.week || "") < THIS_WEEK; });
      var fresh = open.filter(function (a) { return (a.week || "") >= THIS_WEEK; });
      var g1 = group("Carried over", carried, " still open from an earlier meeting");
      var g2 = group("Raised this week", fresh, null);
      if (g1) listEl.appendChild(g1);
      if (g2) listEl.appendChild(g2);
      if (showDone.checked) {
        var g3 = group("Completed", done.slice(-20), null);
        if (g3) listEl.appendChild(g3);
      }
      if (!open.length && !(showDone.checked && done.length)) {
        statusEl.hidden = false;
        statusEl.textContent = done.length
          ? "No open action items - " + done.length + " completed."
          : "No action items yet - add the first one below.";
      } else {
        statusEl.hidden = true;
      }
    }

    function add() {
      var t = (textEl.value || "").trim();
      if (!t) { textEl.focus(); return; }
      var payload = {
        text: t, owner: (ownerEl.value || "").trim() || "unassigned",
        due: dueEl.value || "", done: false, doneTs: 0,
        key: "s:action-items", label: "Action Items", kind: "section",
        week: THIS_WEEK, author: author, ts: Date.now()
      };
      textEl.value = ""; dueEl.value = "";
      col.add(payload).catch(onErr);
    }
    addBtn.addEventListener("click", add);
    [textEl, ownerEl].forEach(function (n) {
      n.addEventListener("keydown", function (ev) { if (ev.key === "Enter") add(); });
    });
    showDone.addEventListener("change", render);

    col.onSnapshot(function (snap) {
      items = snap.docs.filter(function (d) { return d.exists; }).map(function (d) {
        var b = d.data() || {}, o = {};
        Object.keys(b).forEach(function (k) { o[k] = b[k]; });   /* snapshots are frozen */
        o.id = d.id;
        o.text = String(o.text || "");
        return o;
      }).sort(function (a, b) {
        return (a.due || "9999") < (b.due || "9999") ? -1 : ((a.due || "9999") > (b.due || "9999") ? 1 : (a.ts || 0) - (b.ts || 0));
      });
      listEl.hidden = false; formEl.hidden = false;
      render();
    }, function () {
      statusEl.hidden = false;
      statusEl.textContent = "The shared action items aren't reachable right now.";
    });
  }).catch(function () { statusEl.textContent = OFFLINE; });
})();
</script>"""

CSS = """
/* ---- Action Items panel (Mark, Sep 15 2026) ----------------------------- */
.act-panel { padding: 12px 18px 14px; }
.act-group { margin-bottom: 10px; }
.act-group:last-child { margin-bottom: 0; }
.act-group-head { font-size: 11px; text-transform: uppercase; letter-spacing: 0.03em;
  color: var(--muted-ink); font-weight: 700; margin: 0 0 3px; }
.act-group-note { text-transform: none; letter-spacing: 0; font-weight: 500;
  color: var(--muted-ink); font-style: italic; }
.act-row { display: flex; align-items: flex-start; gap: 9px; padding: 5px 0;
  border-bottom: 1px solid var(--gridline); }
.act-row:last-child { border-bottom: none; }
.act-row input[type="checkbox"] { margin-top: 2px; accent-color: var(--accent); }
.act-main { flex: 1 1 auto; min-width: 0; }
.act-text { font-size: 13px; }
.act-sub { font-size: 11px; color: var(--muted-ink); margin-top: 1px; }
.act-done .act-text { text-decoration: line-through; color: var(--muted-ink); }
.act-x { background: none; border: 1px solid var(--gridline); border-radius: 5px;
  color: var(--text-secondary); cursor: pointer; font-size: 12px; line-height: 1;
  padding: 2px 7px; flex: 0 0 auto; }
.act-x:hover { background: var(--gridline); color: var(--text-primary); }
.act-form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; }
.act-form input[type="text"] { border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-page); color: var(--text-primary); font: inherit;
  font-size: 12.5px; padding: 6px 10px; }
#act-text { flex: 1 1 320px; }
#act-owner { flex: 0 0 130px; }
.act-form input[type="date"] { border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-page); color: var(--text-primary); font: inherit;
  font-size: 12.5px; padding: 5px 8px; }
.act-form button { border: 1px solid var(--border); border-radius: 6px; background: var(--accent);
  color: #fff; font: inherit; font-size: 12.5px; font-weight: 600; padding: 6px 14px; cursor: pointer; }
.act-form button:hover { filter: brightness(1.08); }
.act-done-toggle { font-size: 11.5px; color: var(--muted-ink); display: inline-flex;
  align-items: center; gap: 5px; }
</style>"""

src = open(SRC, encoding="utf-8").read()
assert 'class="agenda-panel act-panel"' not in src, "already applied"

# panel goes directly under the Meeting Agenda
anchor = '<section class="summary-panel">'
assert src.count(anchor) == 1, "summary anchor not unique"
src = src.replace(anchor, PANEL + "\n\n\n" + anchor, 1)
src = src.replace("\n</style>", CSS, 1)
src = src.replace("</body></html>", SCRIPT + "\n</body></html>", 1)

open(OUT, "w", encoding="utf-8").write(src)
print(f"wrote {OUT} ({len(src):,} bytes)")
