#!/usr/bin/env python3
"""Keep an open drawer form alive across store re-renders (Mark, Oct 5 2026: "the drop down to
select a resource to allocate disappears too fast").

The shared-store shim polls every 4 s and every snapshot calls renderAll() -> renderDrawer(), which
rebuilt the Action / Allocation form each time - so the consultant datalist closed and half-typed
values were lost within seconds. Now renderDrawer() leaves the drawer alone while the same form is
open; it rebuilds when the form is closed, switched or saved (those paths change `formOpen` first).
Idempotent post-processing pass, run after open_roles_polish.py:

    python3 drawer_form_hold.py dashboard_artifact.html [dashboard_artifact.html]
"""
import sys

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if 'f.dataset.form = "alloc";' in s:
    print("already applied"); sys.exit(0)

def rep(old, new):
    global s
    assert old in s, old[:80]
    s = s.replace(old, new, 1)

rep('''  function actionForm(key) {
    var f = el("div", "ct-form");''', '''  function actionForm(key) {
    var f = el("div", "ct-form");
    f.dataset.form = "action";''')
rep('''  function allocForm(key) {
    var f = el("div", "ct-form");''', '''  function allocForm(key) {
    var f = el("div", "ct-form");
    f.dataset.form = "alloc";''')
rep('''  function renderDrawer() {
    if (!S.openKey || drawer.hidden) return;
    var key = S.openKey;''', '''  function renderDrawer() {
    if (!S.openKey || drawer.hidden) return;
    /* A form the user is filling in must survive the store's periodic re-render (Mark, Oct 5
       2026): while the same form is open for the same subject, leave the drawer as it is. */
    var held = drawer.querySelector('.ct-form[data-form="' + formOpen + '"]');
    if (formOpen && held && held.dataset.key === S.openKey) return;
    var key = S.openKey;''')
# stamp the subject on the form when it is mounted
rep('''    if (formOpen === "action") drBody.appendChild(actionForm(key));
    if (formOpen === "alloc") drBody.appendChild(allocForm(key));''',
    '''    if (formOpen === "action") { var fa = actionForm(key); fa.dataset.key = key; drBody.appendChild(fa); }
    if (formOpen === "alloc") { var fb = allocForm(key); fb.dataset.key = key; drBody.appendChild(fb); }''')

open(OUT, "w", encoding="utf-8").write(s)
print(f"drawer form hold applied; wrote {OUT} ({len(s):,} bytes)")
