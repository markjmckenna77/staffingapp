#!/usr/bin/env python3
"""Open Roles & Recruiting (Mark, Oct 5 2026, late): the click-to-open line reads
"Staffing Suggestions and Allocations" and there is no commenting on open roles.

  - the toggle label becomes "Staffing Suggestions and Allocations"; roles whose only detail was a
    comment thread lose the toggle line altogether
  - the comment rows under each role are removed; the role's thread key moves onto the role row
    (data-ct-key) so Allocate and the proposals overlay keep addressing the same subject
  - the drawer opened from an Allocate button is allocation-only: no comment box, no week filter,
    no "+ Action item" (the allocation history still shows, it is the record of what was entered)
Idempotent post-processing pass, run after open_roles_polish.py:

    python3 roles_alloc_only.py dashboard_artifact.html [dashboard_artifact.html]
"""
import re
import sys

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else SRC
s = open(SRC, encoding="utf-8").read()
if "Staffing Suggestions and Allocations" in s:
    print("already applied"); sys.exit(0)

i0 = s.index('id="roles-table"'); i1 = s.index("</table>", i0)
tbl = s[i0:i1]

# key per role, from its comment mount
keys, labels = {}, {}
for rid, key, label in re.findall(r'<tr hidden data-role-parent="(or\d+)" class="role-detail demand-sub comment-row"[^>]*>.*?data-ct-key="([^"]+)"[^>]*data-ct-label="([^"]*)"', tbl, re.S):
    keys[rid] = key; labels[rid] = label
assert keys, "no role comment mounts found"

# stamp the key on the role row and on its suggestions row; drop the comment rows
def stamp_main(m):
    rid = m.group(1)
    return m.group(0).replace(f'<tr data-role-id="{rid}" ', f'<tr data-role-id="{rid}" data-ct-key="{keys.get(rid, "")}" data-ct-kind="role" data-ct-label="{labels.get(rid, "")}" ', 1)
tbl = re.sub(r'<tr data-role-id="(or\d+)" class="demand-main role-row"[^>]*>', stamp_main, tbl)
def stamp_fits(m):
    rid = m.group(1)
    return m.group(0).replace(f'<tr hidden data-role-parent="{rid}" ', f'<tr hidden data-role-parent="{rid}" data-ct-key="{keys.get(rid, "")}" ', 1)
tbl = re.sub(r'<tr hidden data-role-parent="(or\d+)" class="role-detail demand-sub fits-row[^"]*"[^>]*>', stamp_fits, tbl)
tbl, n_removed = re.subn(r'\s*<tr hidden data-role-parent="or\d+" class="role-detail demand-sub comment-row"[^>]*>.*?</tr>', "", tbl, flags=re.S)

# toggle labels; toggles that only opened a comment thread go away
n_label = 0
def relabel(m):
    global n_label
    row = m.group(0)
    label = re.sub(r"<[^>]+>", "", re.search(r'<span class="pj-caret"></span>(.*?)</button>', row, re.S).group(1)).strip()
    if label.lower() in ("comments", "details"):
        return ""
    n_label += 1
    return re.sub(r'(<span class="pj-caret"></span>).*?(</button>)', r"\1Staffing Suggestions and Allocations\2", row, count=1, flags=re.S)
tbl = re.sub(r'\s*<tr class="role-more"[^>]*>.*?</tr>', relabel, tbl, flags=re.S)
s = s[:i0] + tbl + s[i1:]

# the Allocate handler and ROLES reader take the key from the rows now
old = '''    var mount = tbl.querySelector('tr[data-role-parent="' + id + '"] .ct-mount');
    var key = mount ? mount.dataset.ctKey : "";'''
assert old in s
s = s.replace(old, '''    var keyed = tbl.querySelector('tr[data-role-parent="' + id + '"][data-ct-key], tr[data-role-id="' + id + '"][data-ct-key]');
    var key = keyed ? keyed.dataset.ctKey : "";''', 1)
old = '''      var rk = c ? (c.dataset.ctKey || ("r:" + (c.dataset.rk || ""))) : ("r:" + slug(roleEl ? roleEl.textContent : i));'''
assert old in s
s = s.replace(old, '''      var rk = tr.dataset.ctKey || (c ? (c.dataset.ctKey || ("r:" + (c.dataset.rk || ""))) : ("r:" + slug(roleEl ? roleEl.textContent : i)));
      if (tr.dataset.ctKey && !S.subjects[rk]) S.subjects[rk] = { label: tr.dataset.ctLabel || (roleEl ? roleEl.textContent.replace(/\\s+/g, " ").trim() : rk), kind: "role" };''', 1)

# allocation-only drawer when opened from an Allocate button
old = '''  window.__ctAllocate = function (key, cons) {
    S.allocPrefill = cons || "";
    openDrawer(key);'''
assert old in s
s = s.replace(old, '''  window.__ctAllocate = function (key, cons) {
    S.allocPrefill = cons || "";
    if (!S.subjects[key]) {
      var rowEl = document.querySelector('#roles-table tr.demand-main[data-ct-key="' + key + '"]');
      S.subjects[key] = { kind: "role", label: rowEl ? (rowEl.dataset.ctLabel || rowEl.textContent.replace(/\\s+/g, " ").trim()) : key };
    }
    openDrawer(key);
    drawer.classList.add("ct-alloc-only");''', 1)
old = '''  function closeDrawer() {
    drawer.hidden = true; scrim.hidden = true; S.openKey = null; formOpen = null;'''
assert old in s
s = s.replace(old, '''  function closeDrawer() {
    drawer.classList.remove("ct-alloc-only");
    drawer.hidden = true; scrim.hidden = true; S.openKey = null; formOpen = null;''', 1)
# any other way into the drawer clears the mode
old = '''  function openDrawer(key) {
    S.openKey = key;'''
assert old in s
s = s.replace(old, '''  function openDrawer(key) {
    drawer.classList.remove("ct-alloc-only");
    S.openKey = key;''', 1)

CSS = """
/* ---- Oct 5 2026 (Mark): open roles have no comments; the Allocate drawer is allocation-only */
.ct-drawer.ct-alloc-only .ct-dr-foot textarea, .ct-drawer.ct-alloc-only .ct-dr-foot .ct-compose-row, .ct-drawer.ct-alloc-only .ct-dr-tools .mlog-select,
.ct-drawer.ct-alloc-only .ct-dr-tools .ct-ghost:not(:last-child), .ct-drawer.ct-alloc-only .mlog-empty { display: none !important; }
.ct-drawer.ct-alloc-only .ct-dr-body { padding-bottom: 16px; }
</style>"""
s = s.replace("\n</style>", CSS, 1)

open(OUT, "w", encoding="utf-8").write(s)
print(f"open roles: {n_removed} comment rows removed, {n_label} toggles relabelled; wrote {OUT} ({len(s):,} bytes)")
