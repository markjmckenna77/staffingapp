#!/usr/bin/env python3
"""Recruiting Activity in the Open Roles & Recruiting format (Mark, Oct 6 2026).

Post-processing pass, runs after recruiting_bgcheck.py (and before or after collapsible_sections.py):

    python3 recruiting_roles_format.py dashboard.html [dashboard.html]

Keeps the stat tiles. Replaces the three columns (Filled / Waiting on background check / Opened in
the last two weeks) and the no-requisition / closed table with one table laid out like the Open
Roles table: a band per group, then for every role a bold "Client: Role" title with its weekly
hours and a yellow Recruiting Update box underneath. Weekly hours and "Skills needed" are borrowed
from the matching row of the Open Roles table (#roles-table) when there is one; otherwise the week
cells read as dashes. Everything else comes from the section as recruiting_bgcheck.py left it.
"""
import html
import re
import sys

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SRC = ARGS[0]
OUT = ARGS[1] if len(ARGS) > 1 else SRC
s = open(SRC, encoding="utf-8").read()
if 'id="rec-table"' in s:
    print("already applied"); sys.exit(0)

sec_start = s.index('<section class="section4 recruiting-section">')
sec_end = s.index("</section>", sec_start)
sec = s[sec_start:sec_end]

# ---------------------------------------------------------------- Open Roles rows to borrow from
roles = {}       # label -> {"cells": html, "skills": html, "update": html}
rt = s[s.index('id="roles-table"'):s.index("</table>", s.index('id="roles-table"'))]
thead = re.search(r"<thead>.*?</thead>", rt, re.S).group(0)
for m in re.finditer(r'<tr data-role-id="(or\d+)"[^>]*data-ct-label="([^"]*)"[^>]*class="demand-main role-row"[^>]*>(.*?)</tr>\s*'
                   r'<tr class="role-update[^"]*"[^>]*><td colspan="9"><div class="demand-update">(.*?)</div></td></tr>', rt, re.S):
    rid, label, row, upd = m.groups()
    cells = "".join(re.findall(r'<td class="wk">.*?</td>', row, re.S))
    sk = re.search(r'<div class="demand-skills">(.*?)</div>', upd, re.S)
    note = re.sub(r'<div class="demand-skills">.*?</div>', "", upd, flags=re.S)
    roles[html.unescape(label)] = {"cells": cells, "skills": sk.group(1) if sk else "", "update": note}
NWK = len(re.findall(r'<th class="wk">', thead))
EMPTY = '<td class="wk"><div class="wk-cell wk-demand-empty" data-h="0">&mdash;</div></td>' * NWK

MATCHED = []   # (client, role, Open Roles label) - printed by --explain
STOP = {"inc", "the", "and", "for", "contract", "senior", "sr", "us", "cti", "llc", "corp"}
def toks(t):
    return {w for w in re.findall(r"[a-z0-9]+", html.unescape(t).lower()) if len(w) > 2 and w not in STOP}
def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", html.unescape(t).lower()).strip()

def initials(t):
    return "".join(w[0] for w in re.findall(r"[a-z0-9]+", norm(t)))

def same_client(a, b):
    if not a or not b:
        return True
    na, nb = norm(a), norm(b)
    return bool(toks(a) & toks(b)) or na[:3] == nb[:3] or initials(a) == nb.replace(" ", "") or initials(b) == na.replace(" ", "")

def match(client, role, who=""):
    """The Open Roles row this recruiting line is about, or None."""
    for label in roles:                                      # same role text, same client
        lc, _, lr = label.partition(": ")
        if lr and norm(lr) == norm(role) and same_client(lc, client):
            MATCHED.append((client, role, label)); return roles[label]
    if who:                                                   # candidate named in the demand line
        first = who.split(" ")[0]
        for label in roles:
            if re.search(r"\b" + re.escape(first) + r"\b", label, re.I):
                MATCHED.append((client, role, label)); return roles[label]
    want, best, score = toks(client + " " + role), None, 0
    for label in roles:
        hit = len(want & toks(label))
        if hit > score:
            best, score = label, hit
    if best and score >= 3:
        MATCHED.append((client, role, best)); return roles[best]
    return None

# ---------------------------------------------------------------- what the section says now
def col_items(title):
    m = re.search(r'<h3 class="section4-subhead">' + re.escape(title) + r'.*?</h3>\s*<ul class="rec-list"[^>]*>(.*?)</ul>', sec, re.S)
    return re.findall(r"<li>(.*?)</li>", m.group(1), re.S) if m else []

def split_item(li):
    who = re.match(r"<b>(.*?)</b> &mdash; ", li)
    body = li[who.end():] if who else li
    sub = re.search(r'<div class="rec-item-sub">(.*?)</div>', body, re.S)
    tag = re.search(r'<span class="bg-tag[^"]*">.*?</span>', body, re.S)
    title = re.sub(r"<div.*", "", re.sub(r'<span class="bg-tag.*?</span>', "", body, flags=re.S), flags=re.S).strip()
    return (who.group(1) if who else ""), title, (sub.group(1) if sub else ""), (tag.group(0) if tag else "")

def client_role(title):
    for sep in (": ", " - "):
        if sep in title:
            c, _, r = title.partition(sep)
            return c.strip(), r.strip()
    return "", title.strip()

filled = [split_item(x) for x in col_items("Filled")]
waiting = [split_item(x) for x in col_items("Waiting on background check")]
opened = [split_item(x) for x in col_items("Opened in the last two weeks")]
gaps = re.findall(r'<tr class="rec-row-(noreq|closed)"><td>.*?</td><td>(.*?)</td><td>(.*?)</td>', sec, re.S)
notes = re.findall(r'<div class="rec-note">(.*?)</div>', sec[sec.index("rec-table-wrap"):] if "rec-table-wrap" in sec else "", re.S)

# ---------------------------------------------------------------- rows
def band(label, n, note):
    return (f'        <tr class="grid-open-head rec-band"><td colspan="{NWK + 1}">{label} '
            f'<span class="count-chip pj-chip-open">{n}</span><span class="goh-note">{note}</span></td></tr>\n')

def row(title, chips, src, update, meta=""):
    cells = src["cells"] if src else EMPTY
    chip_html = f'<div class="chip-row">{"".join(chips)}</div>' if chips else ""
    skills = f'<div class="demand-skills">{src["skills"]}</div>' if src and src["skills"] else ""
    meta_html = f'<div class="rec-meta">{meta}</div>' if meta else ""
    return (f'        <tr class="role-row rec-role"><td class="col-demand-name"><div class="demand-role">'
            f'<span class="role-title">{title}</span></div>{chip_html}</td>{cells}</tr>\n'
            f'        <tr class="role-update rec-update demand-sub has-sub"><td colspan="{NWK + 1}"><div class="demand-update">'
            f'<b>Recruiting Update:</b> {update}{meta_html}{skills}</div></td></tr>\n')

def empty_row(text):
    return f'        <tr class="rec-empty-row"><td colspan="{NWK + 1}">{text}</td></tr>\n'

def split_sub(sub):
    parts = [p.strip() for p in sub.split(" &middot; ")]
    return parts[0], parts[1:]

FILLED_SRC = {}   # candidate first name -> the Open Roles row their filled requisition matched
body = ""
body += band("Filled", len(filled), "candidate selected &middot; onboarding under way")
for who, title, sub, _ in filled:
    project, rest = split_sub(sub)
    c, r = client_role(title)
    src = match(c, r, who)
    if who:
        FILLED_SRC[who.split(" ")[0].lower()] = src
    body += row(title, [f'<span class="chip chip-fit">{who}</span>'] if who else [], src,
                " &middot; ".join(rest) or "<i>no status note in this export.</i>", f"Project: {project}" if project else "")
if not filled:
    body += empty_row("No roles filled in this export.")

body += band("Waiting on background check", len(waiting),
             "read from the recruiter&#39;s status notes &middot; &quot;last mentioned&quot; means later notes are silent on it &mdash; confirm in the meeting")
for who, title, sub, tag in waiting:
    note, meta = split_sub(sub)
    c, r = client_role(title)
    chips = ([f'<span class="chip chip-fit">{who}</span>'] if who else []) + ([tag] if tag else [])
    body += row(title, chips, match(c, r, who), note, " &middot; ".join(meta))
if not waiting:
    body += empty_row("No requisition is waiting on a background check in this export.")

body += band("Opened in the last two weeks", len(opened), "new requisitions in the ATS since the previous export")
for who, title, sub, _ in opened:
    c, r = client_role(title)
    named = [k for k in FILLED_SRC if re.search(r"\b" + re.escape(k) + r"\b", title, re.I)]
    src = FILLED_SRC[named[0]] if named else match(c, r, who)   # "(Sakshi hire)" -> Sakshi's filled requisition
    upd = src["update"].replace("<b>Recruiting Update:</b> ", "", 1) if src else "<i>new requisition &mdash; no status note yet.</i>"
    body += row(title, ['<span class="chip chip-stage">new</span>'], src, upd)
if not opened:
    body += empty_row("No requisitions opened in the last two weeks.")

noreq = [(c, r) for k, c, r in gaps if k == "noreq"]
closed = [(c, r) for k, c, r in gaps if k == "closed"]
body += band("Scheduled demand with no requisition", len(noreq),
             "open demand in Salesforce with nothing open in the ATS &mdash; fill internally or raise a requisition")
for c, r in noreq:
    body += row(f"{c}: {r}" if c else r, ['<span class="chip chip-norec">no requisition</span>'], match(c, r),
                "<i>no requisition open in the ATS &mdash; either it is meant to be filled internally, or the requisition has not been raised yet.</i>")
if not noreq:
    body += empty_row("Every scheduled role has a requisition open in the ATS.")

if closed:
    body += band("Requisitions closed", len(closed), "in the previous export, absent from this one")
    for c, r in closed:
        body += row(f"{c}: {r}" if c else r, ['<span class="chip chip-quiet">closed</span>'], match(c, r),
                    "<i>no longer in the ATS export &mdash; confirm it was filled or cancelled.</i>")

thead_rec = thead.replace("<th>Open role</th>", "<th>Requisition / role</th>")
table = (f'  <div class="outlook-scroll"><table class="outlook-table staff-grid" id="rec-table">\n{thead_rec}\n<tbody>\n'
         f'{body}</tbody></table></div>\n')

# swap: everything from the columns through the gaps table and its note -> the new table
a = sec.index('<div class="rec-cols">')
b = sec.index('<div class="rec-note rec-note-bottom">')
new_sec = sec[:a] + table.lstrip() + "  " + sec[b:]
s = s[:sec_start] + new_sec + s[sec_end:]

CSS = """
/* ---- Recruiting Activity in the Open Roles format (Mark, Oct 6 2026) */
#rec-table tr[hidden] { display: none !important; }
#rec-table .wk-cell.wk-demand, #rec-table .wk-cell.wk-demand-empty {
  min-width: 78px; padding: 3px 4px 2px; border-radius: 6px; font-weight: 700; font-size: 12px; font-variant-numeric: tabular-nums; }
#rec-table .wk-cell.wk-demand { box-shadow: inset 3px 0 0 var(--status-warning); }
#rec-table .wk-cell.wk-demand::after, #rec-table .wk-cell.wk-demand-empty::after {
  content: "hrs/wk"; display: block; font-size: 9px; line-height: 1.35; font-weight: 400; color: var(--text-secondary); }
#rec-table .wk-cell.wk-demand-empty::after { visibility: hidden; }
#rec-table tr.role-row td { border-bottom: none; }
#rec-table tr.role-row td.col-demand-name { padding-left: 8px !important; }
#rec-table .role-title { text-decoration: none; }
#rec-table tr.role-update td { padding: 0 8px 9px 22px !important; border-bottom: 1px solid var(--gridline); }
#rec-table tr.role-update .demand-update { margin: 0; }
#rec-table .rec-meta { font-size: 10.5px; color: var(--text-secondary); margin-top: 2px; }
#rec-table .demand-skills { margin-top: 3px; padding-top: 3px; border-top: 1px dashed color-mix(in srgb, var(--status-warning) 45%, transparent); }
#rec-table tr.rec-empty-row td { padding: 7px 8px 8px 22px !important; font-size: 11.5px; color: var(--muted-ink);
  font-style: italic; border-bottom: 1px solid var(--gridline); }
#rec-table .chip-row .bg-tag { margin-left: 0; margin-right: 4px; }
.outlook-scroll:has(> #rec-table) { overflow-x: clip; }
#rec-table thead th { position: sticky; top: 0; z-index: 6; background: var(--gridline); box-shadow: 0 1px 0 var(--gridline); }
</style>"""
s = s.replace("\n</style>", CSS, 1)
if "--explain" in sys.argv:
    for c, r, l in MATCHED:
        print(f"  {c}: {r}  ->  {l}")
open(OUT, "w", encoding="utf-8").write(s)
print(f"recruiting table: {len(filled)} filled, {len(waiting)} waiting, {len(opened)} opened, {len(noreq)} no-req, {len(closed)} closed; "
      f"matched to Open Roles: {body.count('wk-demand')} demand cells; wrote {OUT} ({len(s):,} bytes)")
