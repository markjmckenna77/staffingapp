#!/usr/bin/env python3
"""Allocations from the Open Roles section + two small header edits (Mark, Oct 5 2026 evening).

Post-processing pass that runs LAST in the weekly build, after flatten_open_roles.py:

    python3 allocate_layer.py dashboard_artifact.html dashboard_artifact.html

What it changes:
  1. Meeting Agenda header: the "shared - everyone who opens this page sees the same list ..."
     note is removed.
  2. "Summary" section header becomes "Utilization Summary".
  3. Open Roles & Recruiting: every suggested consultant gets an "Allocate" button, and every
     suggestions line gets "Allocate someone else"; both open the role's drawer on the allocation
     form with the consultant, project, hours and weeks prefilled. The form's primary action is
     "Allocate in NetSuite" (POST /api/allocate) for approvers when the app has NetSuite
     credentials, and falls back to the old "Propose allocation" otherwise. NetSuite is the
     system of record for staffing - the dashboard's Snowflake tables are rebuilt from NetSuite's
     Resource Allocations - so the page's Salesforce wording around allocations becomes NetSuite.
"""
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "dashboard_artifact.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if 'class="alloc-btn"' in s:
    print("already applied"); sys.exit(0)


def must_replace(old, new, count=1, where=None):
    global s
    hay = s if where is None else where
    assert old in hay, f"anchor not found: {old[:90]!r}"
    if where is None:
        s = s.replace(old, new, count)
        return None
    return hay.replace(old, new, count)


# ---- 1. agenda note ---------------------------------------------------------------------
s = re.sub(r'(<h2 class="sec-head">Meeting Agenda) <span class="agenda-sub">shared &mdash; everyone who opens '
           r'this page sees the same list, and it survives the weekly refresh</span>', r"\1", s, count=1)
assert "everyone who opens this page sees the same list" not in s, "agenda note still present"

# ---- 2. Summary -> Utilization Summary ------------------------------------------------------
must_replace('<h2 class="sec-head">Summary</h2>', '<h2 class="sec-head">Utilization Summary</h2>')

# ---- 3a. Allocate buttons on the suggestion rows -------------------------------------------
n_btn = 0
def add_buttons(m):
    global n_btn
    row = m.group(0)
    def card(mm):
        global n_btn
        name = re.search(r'<span class="fit-name">(.*?)</span>', mm.group(0)).group(1)
        n_btn += 1
        return mm.group(0)[:-len("</li>")] + (f'<button type="button" class="alloc-btn" data-cons="{name}" '
                                              f'title="Allocate {name} to this role in NetSuite">Allocate</button></li>')
    row = re.sub(r'<li class="fit-card">.*?</li>', card, row, flags=re.S)
    row = row.replace('</div></td></tr>', '<div class="alloc-other"><button type="button" class="alloc-btn alloc-btn-other">'
                      'Allocate someone else&hellip;</button></div></div></td></tr>', 1)
    return row
s, n_rows = re.subn(r'<tr hidden data-role-parent="or\d+" class="role-detail demand-sub fits-row[^"]*"[^>]*>.*?</tr>',
                    add_buttons, s, flags=re.S)
assert n_rows, "no suggestion rows found"

# ---- 3b. app-layer script: NetSuite wording, prefill, the real write ------------------------
i0 = s.index("function allocForm(key)")
i0 = s.rfind("<script>", 0, i0); i1 = s.index("</script>", i0)
js = s[i0:i1]

js = must_replace('  var ROLES = [];       /* {key, label, project, hrs:{wkLabel:h}} */',
'''  var ROLES = [];       /* {key, label, project, hrs:{wkLabel:h}} */
  /* Allocations go to NetSuite (the staffing system of record) through /api/allocate when the
     app has credentials and the viewer is an approver; otherwise the form only proposes. */
  var ALLOC = { configured: false, dryRun: true, approver: false, system: "netsuite" };
  try {
    fetch("/api/allocate", { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && typeof j === "object") ALLOC = j; }).catch(function () {});
  } catch (e0) {}
  /* ISO Monday for a grid week label ("Oct 5") - the grid's year is the one that puts its first
     week within six months of today. */
  var MONTHS = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };
  function weekISO(i) {
    var first = (GRID.weeks[0] || "").split(" ");
    var mo = MONTHS[first[0]], day = parseInt(first[1], 10);
    if (mo === undefined || !day) return "";
    var now = new Date(), y = now.getFullYear();
    var d = new Date(Date.UTC(y, mo, day));
    var diff = (d - Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000;
    if (diff > 183) d = new Date(Date.UTC(y - 1, mo, day));
    if (diff < -183) d = new Date(Date.UTC(y + 1, mo, day));
    d.setUTCDate(d.getUTCDate() + 7 * i);
    return d.toISOString().slice(0, 10);
  }
  /* "Client: Role title" -> the project the Projects, Roles & Open Demand section lists it under. */
  function roleProject(label) {
    var i = label.indexOf(": ");
    var client = i > 0 ? label.slice(0, i).trim() : "", title = (i > 0 ? label.slice(i + 2) : label).replace(/\\s+/g, " ").trim();
    var best = null;
    Array.prototype.forEach.call(document.querySelectorAll("tr.pj-detail-open"), function (tr) {
      var t = tr.querySelector(".pj-open-role"); if (!t) return;
      if (t.textContent.replace(/\\s+/g, " ").trim() !== title) return;
      var pj = document.querySelector('tr.pj-row[data-pj="' + tr.dataset.parent + '"]');
      var pn = pj && pj.querySelector(".pj-name");
      var cl = pj && document.querySelector('tr.pj-client-row[data-cl="' + pj.dataset.client + '"] .pj-client-name');
      var cname = cl ? cl.textContent.trim() : "";
      var cand = { project: pn ? pn.textContent.trim() : "", client: cname };
      if (!best || (client && cname && (cname.indexOf(client) === 0 || client.indexOf(cname) === 0))) best = cand;
    });
    return best;
  }''', where=js)

js = must_replace('    var head = el("h4", null, "Propose an allocation");',
                  '    var head = el("h4", null, "Allocate a consultant");', where=js)
js = must_replace('''        value: kind === "consultant" ? subjectLabel(key) : "" });''',
                  '''        value: kind === "consultant" ? subjectLabel(key) : (S.allocPrefill || "") });
    S.allocPrefill = "";''', where=js)
js = must_replace('''      head.textContent = rem ? "Propose a removal" : "Propose an allocation";''',
                  '''      head.textContent = rem ? "Propose a removal" : "Allocate a consultant";''', where=js)
js = must_replace('''      hint.textContent = rem
        ? "Saved as a proposed removal: the 8 Week Outlook strikes the hours through, Capacity vs. Need "
          + "shows them freed, and it stays on the Proposed allocations list until someone marks it entered "
          + "in Salesforce. Nothing is changed in Salesforce from here."
        : "Saved as a proposed assignment: it shows on the 8 Week Outlook and in Capacity vs. Need marked "
          + "pending, and stays on the Proposed allocations list until someone marks it entered in Salesforce.";
      save.textContent = rem ? "Propose removal" : "Propose allocation";''',
'''      var live = !rem && ALLOC.configured && ALLOC.approver;
      hint.textContent = rem
        ? "Saved as a proposed removal: the 8 Week Outlook strikes the hours through, Capacity vs. Need "
          + "shows them freed, and it stays on the Proposed allocations list until someone marks it entered "
          + "in NetSuite. Nothing is changed in NetSuite from here."
        : live
          ? (ALLOC.dryRun ? "Dry run: NetSuite is checked (consultant, project, open role) but nothing is written yet. "
             : "Creates the Resource Allocation in NetSuite now - the system of record - and retires the open role's "
               + "generic allocation it fills. ")
            + "Snowflake and this dashboard pick it up on the next Fivetran sync and dbt build; until then it shows "
            + "here as entered."
          : (ALLOC.configured ? "Only approvers can write to NetSuite; " : "NetSuite isn't connected to the app yet; ")
            + "saved as a proposed assignment: it shows on the 8 Week Outlook and in Capacity vs. Need marked "
            + "pending, and stays on the Proposed allocations list until someone enters it in NetSuite.";
      save.textContent = rem ? "Propose removal" : (live ? (ALLOC.dryRun ? "Check in NetSuite (dry run)" : "Allocate in NetSuite") : "Propose allocation");''', where=js)

OLD_CLICK = '''      var weeks = GRID.weeks.slice(i0, i1 + 1);
      S.db.collection("allocations").add({'''
NEW_CLICK = '''      var weeks = GRID.weeks.slice(i0, i1 + 1);
      if (!isRemove() && ALLOC.configured && ALLOC.approver) {
        var isoWeeks = [], ii;
        for (ii = i0; ii <= i1; ii++) { var w = weekISO(ii); if (w) isoWeeks.push(w); }
        if (isoWeeks.length !== weeks.length) { flashDrawerError("Couldn't work out the week dates for this grid."); return; }
        var rl = roleSel.value ? ((roleByKey(roleSel.value) || {}).label || "") : "";
        var rp = rl ? roleProject(rl) : null;
        save.disabled = true; save.textContent = "Writing to NetSuite\\u2026";
        fetch("/api/allocate", { method: "POST", credentials: "same-origin",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ consultant: cons, project: (rp && rp.project) || proj, roleKey: roleSel.value || "",
            roleLabel: rl, roleTitle: rl ? rl.slice(rl.indexOf(": ") + 2) : "", hours: h, weeks: isoWeeks,
            note: (note.value || "").trim(), key: key, label: subjectLabel(key), author: S.author, week: THIS_WEEK,
            fillOpenRole: !!roleSel.value }) })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { j.__status = r.status; return j; }); })
        .then(function (j) {
          save.disabled = false;
          if (j.ok) {
            var ns = j.netsuite || {};
            addComment(key, (j.dryRun ? "NetSuite dry run OK: " : "Allocated in NetSuite: ") + cons + " \\u2192 " + (ns.projectName || proj)
              + ", " + h + " hrs/wk (" + (ns.percentOfTime || "") + "%), " + ns.startDate + " to " + ns.endDate
              + (ns.allocationId ? " \\u00b7 allocation " + ns.allocationId : "")
              + (ns.openRole && ns.openRole.action !== "none" ? " \\u00b7 open role " + ns.openRole.action : "")
              + ((note.value || "").trim() ? " - " + note.value.trim() : ""), "action");
            formOpen = null; renderDrawer();
          } else if (j.error === "netsuite_not_configured") {
            ALLOC.configured = false; formOpen = null; renderDrawer();
            flashDrawerError("Saved as a proposal - NetSuite isn't connected yet.");
          } else {
            var d = j.detail && typeof j.detail === "object" ? JSON.stringify(j.detail) : (j.detail || "");
            flashDrawerError("NetSuite refused (" + (j.error || j.__status) + ")" + (d ? ": " + String(d).slice(0, 300) : "")
              + (j.id ? " - kept as a proposal." : ""));
            syncKind();
          }
        }).catch(function () { save.disabled = false; syncKind(); flashDrawerError("Couldn't reach the app to allocate."); });
        return;
      }
      S.db.collection("allocations").add({'''
js = must_replace(OLD_CLICK, NEW_CLICK, where=js)

js = must_replace('''  function closeDrawer() {
    drawer.hidden = true; scrim.hidden = true; S.openKey = null; formOpen = null;
  }''', '''  function closeDrawer() {
    drawer.hidden = true; scrim.hidden = true; S.openKey = null; formOpen = null;
  }
  /* Open Roles "Allocate" buttons: open the role's drawer straight on the allocation form. */
  window.__ctAllocate = function (key, cons) {
    S.allocPrefill = cons || "";
    openDrawer(key);
    formOpen = "alloc"; renderDrawer();
    setTimeout(function () { var f = drawer.querySelector(".ct-form input, .ct-form select"); if (f) f.focus(); }, 40);
  };''', where=js)

js = must_replace("""          if ((r.hrs[w] || 0) > 0) { if (firstWk < 0) firstWk = i; lastWk = i; h = r.hrs[w]; }""",
                  """          if ((r.hrs[w] || 0) > 0) { if (firstWk < 0) firstWk = i; lastWk = i; h = Math.max(h, r.hrs[w]); }""", where=js)

js = must_replace('      var ok = el("button", "mlog-sm", "Entered in Salesforce");',
                  '      var ok = el("button", "mlog-sm", ALLOC.configured && ALLOC.approver && a.kind !== "remove" ? "Enter in NetSuite" : "Entered in NetSuite");', where=js)
for old, new in [
    ('" hrs/wk), not yet in Salesforce"', '" hrs/wk), not yet in NetSuite"'),
    ('"Pending Salesforce entry"', '"Pending NetSuite entry"'),
    ('"proposed removal · pending Salesforce"', '"proposed removal · pending NetSuite"'),
    ('"Proposed assignments (pending Salesforce)"', '"Proposed assignments (pending NetSuite)"'),
    ('"Proposed rows come from the Meeting Log and are not in Salesforce yet. ', '"Proposed rows come from the Meeting Log and are not in NetSuite yet. '),
    ('"line in Salesforce; this page cannot tell the two apart. "', '"line in NetSuite; this page cannot tell the two apart. "'),
    ('"Export for Salesforce (CSV)"', '"Export for NetSuite (CSV)"'),
    ('"These are not in Salesforce - there is no Salesforce connection on this page yet."', '"These are not in NetSuite yet."'),
    ('"Entered in Salesforce ("', '"Entered in NetSuite ("'),
    ('"Proposed allocations - copy into Salesforce"', '"Proposed allocations - copy into NetSuite"'),
    ('the freed hours match what Salesforce actually has', 'the freed hours match what NetSuite actually has'),
]:
    js = must_replace(old, new, where=js)
assert "Salesforce" not in js, [m.start() for m in re.finditer("Salesforce", js)][:3]
s = s[:i0] + js + s[i1:]

# ---- 3c. the buttons' click handling, next to the open-roles toggle script -----------------
anchor = '/* Open roles (Mark, Oct 5 2026): title, recruiting update, then a "Staffing suggestions &'
j0 = s.index(anchor); j1 = s.index("</script>", j0) + len("</script>")
ALLOC_JS = '''
<script>
/* Allocate from an open role (Mark, Oct 5 2026): the suggestion buttons open the role's comment
   drawer on the allocation form with the consultant, project, hours and weeks filled in. */
(function () {
  var tbl = document.getElementById("roles-table");
  if (!tbl) return;
  tbl.addEventListener("click", function (ev) {
    var b = ev.target && ev.target.closest ? ev.target.closest(".alloc-btn") : null;
    if (!b) return;
    ev.preventDefault(); ev.stopPropagation();
    var tr = b.closest("tr[data-role-parent]"); if (!tr) return;
    var id = tr.dataset.roleParent;
    var mount = tbl.querySelector('tr[data-role-parent="' + id + '"] .ct-mount');
    var key = mount ? mount.dataset.ctKey : "";
    if (!key || typeof window.__ctAllocate !== "function") return;
    window.__ctAllocate(key, b.dataset.cons || "");
  });
})();
</script>'''
s = s[:j1] + ALLOC_JS + s[j1:]

# ---- 3d. CSS ----------------------------------------------------------------------------------
CSS = """
/* ---- Oct 5 2026 (Mark): Allocate from the Open Roles suggestions */
#roles-table .fit-card { position: relative; padding-right: 88px !important; }
#roles-table .fit-card .alloc-btn { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); margin-left: 0; }
#roles-table .alloc-btn { margin-left: 8px; padding: 2px 9px; font: 600 10.5px/1.5 inherit; font-family: inherit;
  color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 999px; cursor: pointer;
  vertical-align: middle; white-space: nowrap; }
#roles-table .alloc-btn:hover { background: var(--accent); color: #fff; }
#roles-table .alloc-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
#roles-table .alloc-other { margin-top: 6px; }
#roles-table .alloc-btn-other { margin-left: 0; background: none; }
</style>"""
s = s.replace("\n</style>", CSS, 1)

# ---- 3e. footer sentence ----------------------------------------------------------------------
must_replace("Proposed allocations are <b>not</b> written to Salesforce &mdash; they are held here, shown as a pending "
             "overlay on the 8 Week Outlook and the capacity table, and exported for entry.",
             "Allocations made with an open role&#39;s <b>Allocate</b> button are written to NetSuite &mdash; the system of "
             "record for staffing, from which Snowflake&#39;s allocation tables are rebuilt by Fivetran and dbt &mdash; by an "
             "approver, and show here as entered until the next data refresh carries them; proposals are held here, shown "
             "as a pending overlay on the 8 Week Outlook and the capacity table, until someone enters them.")

open(OUT, "w", encoding="utf-8").write(s)
print(f"allocate layer: {n_rows} suggestion rows, {n_btn} Allocate buttons; agenda note removed; Utilization Summary; wrote {OUT} ({len(s):,} bytes)")
