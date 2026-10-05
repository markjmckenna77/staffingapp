#!/usr/bin/env python3
"""Meeting Agenda section for the staffing dashboard.

The agenda persists in the artifact's shared data store (the `db` runtime
capability, declared as capabilities={"db": {}} at publish): every org viewer of
the live claude.ai page sees the same list live and can add / check off /
reorder / remove items, and items survive the weekly republish untouched (the
store belongs to the artifact, not to a version). In the downloaded copy - or
if the capability is unavailable - the section degrades to a one-line note.
Include AGENDA_HTML right after the dash-subtitle and AGENDA_JS at the end of
the fragment; AGENDA_CSS goes in the stylesheet.
"""

AGENDA_HTML = """<section class="agenda-panel">
  <h2 class="sec-head">Meeting Agenda</h2>
  <div id="agenda-status" class="agenda-note">Loading the shared agenda&hellip;</div>
  <ol id="agenda-items" class="agenda-items" hidden></ol>
  <div id="agenda-form" class="agenda-form" hidden>
    <input id="agenda-input" type="text" maxlength="300" placeholder="Add an agenda item and press Enter&hellip;" aria-label="New agenda item">
    <button id="agenda-add" type="button">Add</button>
    <button id="agenda-clear" type="button" class="agenda-quiet-btn" hidden>Clear checked-off items</button>
  </div>
</section>"""

AGENDA_JS = """<script>
(function () {
  "use strict";
  var statusEl = document.getElementById("agenda-status");
  var listEl = document.getElementById("agenda-items");
  var formEl = document.getElementById("agenda-form");
  var inputEl = document.getElementById("agenda-input");
  var addBtn = document.getElementById("agenda-add");
  var clearBtn = document.getElementById("agenda-clear");
  var offlineMsg = "The shared agenda works on the live dashboard page on claude.ai - this copy can't reach it.";
  if (!(window.claude && typeof window.claude.use === "function")) { statusEl.textContent = offlineMsg; return; }

  window.claude.use("db").then(function (db) {
    if (!db) { statusEl.textContent = offlineMsg; return; }
    var col = db.collection("agenda");
    var items = [];

    function flash(msg) {
      statusEl.hidden = false;
      statusEl.textContent = msg;
      setTimeout(function () { if (items.length) statusEl.hidden = true; }, 4000);
    }
    function onWriteError(err) {
      flash(err && err.code === "quota_exceeded"
        ? "The agenda store is full - clear some items first."
        : "Couldn't save that change (" + ((err && err.code) || "error") + "). You may not have edit access to this page.");
    }

    // id of the item being edited in place, or null. The list re-renders on every
    // snapshot, so the in-progress text and caret are carried across a re-render
    // rather than being lost when somebody else edits a different item.
    var editingId = null;
    // Clearing the list detaches the focused editor, and Chromium fires blur as it
    // goes - which would commit and close the edit every time somebody else touches
    // the agenda. Suppress the blur handler for the duration of a re-render.
    var rerendering = false;

    function commitEdit(it, value) {
      var text = (value || "").trim();
      editingId = null;
      if (text && text !== it.text) {
        col.doc(it.id).update({ text: text, editedTs: Date.now() }).catch(onWriteError);
      }
      render();
    }

    function render() {
      var live = listEl.querySelector(".agenda-edit");
      var pending = live ? live.value : null;
      var caret = live ? [live.selectionStart, live.selectionEnd] : null;
      var liveNotes = document.activeElement && document.activeElement.classList &&
                      document.activeElement.classList.contains("agenda-notes") ? document.activeElement : null;
      var notesId = liveNotes ? liveNotes.dataset.id : null;
      var notesVal = liveNotes ? liveNotes.value : null;
      var notesCaret = liveNotes ? [liveNotes.selectionStart, liveNotes.selectionEnd] : null;
      var focusNotes = null;
      rerendering = true;
      listEl.textContent = "";
      var focusMe = null;
      items.forEach(function (it, idx) {
        var li = document.createElement("li");
        li.className = it.done ? "agenda-item agenda-done" : "agenda-item";
        var cb = document.createElement("input");
        cb.type = "checkbox"; cb.checked = !!it.done;
        cb.setAttribute("aria-label", "Done");
        cb.addEventListener("change", function () {
          col.doc(it.id).update({ done: cb.checked }).catch(onWriteError);
        });
        var body;
        if (editingId === it.id) {
          body = document.createElement("input");
          body.type = "text"; body.className = "agenda-edit"; body.maxLength = 300;
          body.value = pending !== null ? pending : it.text;
          body.setAttribute("aria-label", "Edit agenda item");
          body.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter") { ev.preventDefault(); commitEdit(it, body.value); }
            else if (ev.key === "Escape") { ev.preventDefault(); editingId = null; render(); }
          });
          body.addEventListener("blur", function () {
            if (!rerendering && editingId === it.id) commitEdit(it, body.value);
          });
          focusMe = body;
        } else {
          body = document.createElement("span");
          body.className = "agenda-text"; body.textContent = it.text;
          body.title = "Click to edit";
          body.tabIndex = 0;
          body.setAttribute("role", "button");
          body.addEventListener("click", function () { editingId = it.id; render(); });
          body.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter" || ev.key === " ") {
              ev.preventDefault(); editingId = it.id; render();
            }
          });
        }
        var ctl = document.createElement("span");
        ctl.className = "agenda-ctls";
        function mkBtn(label, title, fn, disabled) {
          var b = document.createElement("button");
          b.type = "button"; b.textContent = label; b.title = title;
          b.disabled = !!disabled;
          // mousedown, not click: a click fires after the edit input's blur has
          // already committed and re-rendered, which throws the button away first
          b.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
          b.addEventListener("click", fn);
          ctl.appendChild(b);
        }
        if (editingId !== it.id) {
          mkBtn("\\u270e", "Edit", function () { editingId = it.id; render(); });
        }
        mkBtn("\\u2191", "Move up", function () { swap(idx, idx - 1); }, idx === 0);
        mkBtn("\\u2193", "Move down", function () { swap(idx, idx + 1); }, idx === items.length - 1);
        mkBtn("\\u00d7", "Remove", function () { col.doc(it.id).delete().catch(onWriteError); });
        li.appendChild(cb); li.appendChild(body); li.appendChild(ctl);
        var notes = document.createElement("textarea");
        notes.className = "agenda-notes"; notes.dataset.id = it.id; notes.rows = 1;
        notes.placeholder = "Meeting notes\u2026"; notes.maxLength = 2000;
        notes.setAttribute("aria-label", "Meeting notes for this agenda item");
        notes.value = notesId === it.id && notesVal !== null ? notesVal : it.notes;
        function growNotes() { notes.style.height = "auto"; notes.style.height = (notes.scrollHeight + 2) + "px"; }
        var notesTimer = null, notesSaved = notes.value;
        function saveNotes() {
          clearTimeout(notesTimer);
          if (notes.value === notesSaved) return;
          notesSaved = notes.value;
          col.doc(it.id).update({ notes: notes.value, notesTs: Date.now() }).catch(onWriteError);
        }
        notes.addEventListener("input", function () {
          growNotes();
          clearTimeout(notesTimer);
          notesTimer = setTimeout(saveNotes, 700);
        });
        notes.addEventListener("blur", saveNotes);
        li.appendChild(notes);
        if (notesId === it.id) focusNotes = notes;
        listEl.appendChild(li);
        growNotes();
      });
      rerendering = false;
      if (focusNotes) {
        focusNotes.focus();
        try { focusNotes.setSelectionRange(notesCaret[0], notesCaret[1]); } catch (e) {}
      }
      if (focusMe) {
        focusMe.focus();
        if (caret) { try { focusMe.setSelectionRange(caret[0], caret[1]); } catch (e) {} }
        else { focusMe.select(); }
      }
      var anyDone = items.some(function (it) { return it.done; });
      clearBtn.hidden = !anyDone;
      if (!items.length) {
        statusEl.hidden = false;
        statusEl.textContent = "No agenda items yet - add the first one below.";
      } else {
        statusEl.hidden = true;
      }
    }

    function swap(i, j) {
      if (j < 0 || j >= items.length) return;
      var a = items[i], b = items[j];
      col.doc(a.id).update({ order: b.order }).catch(onWriteError);
      col.doc(b.id).update({ order: a.order }).catch(onWriteError);
    }

    function addItem() {
      var text = (inputEl.value || "").trim();
      if (!text) return;
      var maxOrder = items.length ? items[items.length - 1].order : 0;
      inputEl.value = "";
      col.add({ text: text, done: false, order: maxOrder + 1, ts: Date.now() }).catch(onWriteError);
    }
    addBtn.addEventListener("click", addItem);
    inputEl.addEventListener("keydown", function (ev) { if (ev.key === "Enter") addItem(); });
    clearBtn.addEventListener("click", function () {
      items.filter(function (it) { return it.done; }).forEach(function (it) {
        col.doc(it.id).delete().catch(onWriteError);
      });
    });

    col.orderBy("order").onSnapshot(function (snap) {
      items = snap.docs.filter(function (d) { return d.exists; }).map(function (d) {
        var body = d.data() || {};
        return { id: d.id, text: String(body.text || ""), done: !!body.done,
                 notes: String(body.notes || ""),
                 order: typeof body.order === "number" ? body.order : 0 };
      });
      listEl.hidden = false; formEl.hidden = false;
      render();
    }, function () {
      statusEl.hidden = false;
      statusEl.textContent = "The shared agenda isn't reachable right now.";
    });
  }).catch(function () { statusEl.textContent = offlineMsg; });
})();
</script>"""

AGENDA_CSS = """
/* ---------- Meeting agenda (shared via the artifact data store) ---------- */
.agenda-panel [hidden] { display: none !important; }
.agenda-panel { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 14px 18px 16px; margin-bottom: 16px; }
.agenda-panel h2 { font-size: 17px; margin: 0 0 8px; }
.agenda-sub { font-size: 11.5px; font-weight: 500; color: var(--muted-ink); margin-left: 8px; }
.agenda-note { font-size: 12.5px; color: var(--text-secondary); font-style: italic; margin: 2px 0 6px; }
.agenda-items { margin: 0 0 10px; padding-left: 22px; }
.agenda-item { padding: 3px 0; border-bottom: 1px solid var(--gridline); font-size: 13px; }
.agenda-item:last-child { border-bottom: none; }
.agenda-item input[type="checkbox"] { margin-right: 8px; vertical-align: -2px; accent-color: var(--accent); }
.agenda-done .agenda-text { text-decoration: line-through; color: var(--muted-ink); }
.agenda-ctls { float: right; }
.agenda-notes { display: block; width: calc(100% - 26px); margin: 3px 0 4px 26px; padding: 3px 7px; box-sizing: border-box;
  border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--text-secondary);
  font: inherit; font-size: 12px; line-height: 1.4; resize: none; overflow: hidden; min-height: 24px; }
.agenda-notes::placeholder { color: var(--muted-ink); font-style: italic; }
.agenda-notes:hover { border-color: var(--gridline); background: var(--surface-page); }
.agenda-notes:focus { outline: none; border-color: var(--accent); background: var(--surface-1); color: var(--text-primary); }
.agenda-done .agenda-notes { color: var(--muted-ink); }
.agenda-text { cursor: text; border-bottom: 1px dotted transparent; }
.agenda-text:hover { border-bottom-color: var(--muted-ink); }
.agenda-text:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px; }
.agenda-edit { width: calc(100% - 140px); border: 1px solid var(--accent); border-radius: 5px;
  background: var(--surface-page); color: var(--text-primary); font: inherit; font-size: 13px;
  padding: 2px 7px; }
.agenda-ctls button { background: none; border: 1px solid var(--gridline); border-radius: 5px; color: var(--text-secondary); cursor: pointer; font-size: 12px; line-height: 1; padding: 2px 7px; margin-left: 4px; }
.agenda-ctls button:hover:not(:disabled) { background: var(--gridline); color: var(--text-primary); }
.agenda-ctls button:disabled { opacity: 0.35; cursor: default; }
.agenda-form { display: flex; gap: 8px; align-items: center; }
.agenda-form input[type="text"] { flex: 1; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-page); color: var(--text-primary); font: inherit; font-size: 12.5px; padding: 6px 10px; }
.agenda-form button { border: 1px solid var(--border); border-radius: 6px; background: var(--accent); color: #fff; font: inherit; font-size: 12.5px; font-weight: 600; padding: 6px 14px; cursor: pointer; }
.agenda-form button:hover { filter: brightness(1.08); }
.agenda-form button.agenda-quiet-btn { background: var(--surface-page); color: var(--text-secondary); font-weight: 500; }
"""
