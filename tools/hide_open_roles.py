#!/usr/bin/env python3
"""Hide chosen roles from the Open Roles & Recruiting table (Mark, Oct 13 2026).

Standing rule: every role whose label starts with "Internal:" is hidden (the practice-director,
marketing, delivery-lead searches carry no project demand and are not staffing decisions).
Per-week extras go in HIDE_EXTRA (e.g. a role that was filled but Salesforce still schedules).

A hidden role takes its whole row group with it (main row, recruiting-update row, "+more" row and
the hidden fits/detail row); the "Total unfilled demand" row and the "N open roles" count in the
heading are recomputed from what is left. The 8 Week Outlook capacity rows and the Projects
section are not touched - they still carry the Salesforce demand.

    python3 hide_open_roles.py dashboard_artifact.html [out.html] [--extra "Sakshi" ...]
"""
import re, sys, html

STANDING = [r"^\s*Internal:"]
HIDE_EXTRA = ["Sakshi"]          # week of Oct 12: role filled, Salesforce still schedules it

args = sys.argv[1:]
extra = list(HIDE_EXTRA)
if "--extra" in args:
    k = args.index("--extra"); extra = args[k + 1:]; args = args[:k]
SRC = args[0]
OUT = args[1] if len(args) > 1 else SRC
PATS = [re.compile(p, re.I) for p in STANDING] + [re.compile(re.escape(x), re.I) for x in extra]

s = open(SRC, encoding="utf-8").read()
i = s.index('id="open-roles"')
tb = s.index("<tbody>", i) + len("<tbody>")
te = s.index("</tbody>", tb)
body = s[tb:te]

rows = re.findall(r"\s*<tr\b.*?</tr>", body, re.S)
tail = body[len("".join(rows)):]
assert body.startswith("".join(rows)) and not tail.strip(), "tbody did not split cleanly into rows"

# group: each demand-main row owns the rows that follow it until the next demand-main / total row
groups, cur = [], None
for r in rows:
    if 'class="demand-main' in r or 'class="demand-total-row"' in r:
        cur = [r]; groups.append(cur)
    elif cur is not None:
        cur.append(r)
    else:
        groups.append([r])

def label(row):
    m = re.search(r'data-ct-label="([^"]*)"', row)
    return html.unescape(m.group(1)) if m else ""

kept, hidden = [], []
for g in groups:
    lab = label(g[0])
    if 'class="demand-main' in g[0] and any(p.search(lab) for p in PATS):
        hidden.append(lab)
    else:
        kept.append(g)

# recompute the total row from the remaining main rows
tot = None
for g in kept:
    if 'class="demand-main' not in g[0]:
        continue
    hs = [float(x) for x in re.findall(r'data-h="([\d.]+)"', g[0])]
    tot = hs if tot is None else [a + b for a, b in zip(tot, hs)]
def fmt(v):
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:g}"
for g in kept:
    if 'class="demand-total-row"' in g[0]:
        cells = iter(tot)
        g[0] = re.sub(r'(<div class="wk-cell wk-demand-total">)[^<]*(</div>)',
                      lambda m: m.group(1) + fmt(next(cells)) + m.group(2), g[0])

s = s[:tb] + "".join("".join(g) for g in kept) + tail + s[te:]

n = sum(1 for g in kept if 'class="demand-main' in g[0])
s = re.sub(r'(<span class="section4-range">)\d+ open roles', lambda m: f"{m.group(1)}{n} open roles", s, count=1)

# ---- Recruiting Activity (Mark, Oct 13 2026: "make the same changes"): the same patterns hide a
# requisition row (and its update row) in #rec-table; band counts and the "roles filled" tile follow.
rec_hidden = []
if 'id="rec-table"' in s:
    i = s.index('id="rec-table"')
    tb = s.index("<tbody>", i) + len("<tbody>"); te = s.index("</tbody>", tb)
    body = s[tb:te]
    rows = re.findall(r"\s*<tr\b.*?</tr>", body, re.S)
    rtail = body[len("".join(rows)):]
    assert body.startswith("".join(rows)) and not rtail.strip(), "rec-table tbody did not split cleanly"
    def rec_label(row):
        # title plus the candidate / status chips, so "Sakshi" matches a row titled by the requisition
        m = re.search(r'<td class="col-demand-name">(.*?)</td>', row, re.S)
        return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""
    # bands: band row + its rows until the next band
    bands, cur = [], None
    for r in rows:
        if 'class="grid-open-head rec-band' in r:
            cur = [r]; bands.append(cur)
        elif cur is not None:
            cur.append(r)
        else:
            bands.append([r])
    out_rows, filled_visible = [], 0
    for b in bands:
        if 'class="grid-open-head rec-band' not in b[0]:
            out_rows.extend(b); continue
        head, rest, keep, skip_update = b[0], b[1:], [], False
        for r in rest:
            if 'class="role-row rec-role"' in r:
                lab = rec_label(r)
                skip_update = any(p.search(lab) for p in PATS)
                if skip_update:
                    rec_hidden.append(lab); continue
                keep.append(r)
            elif 'class="role-update rec-update' in r:
                if not skip_update: keep.append(r)
            else:
                keep.append(r)
        cnt = sum(1 for r in keep if 'class="role-row rec-role"' in r)
        head = re.sub(r'(<span class="count-chip[^"]*">)\d+(</span>)', lambda m: m.group(1) + str(cnt) + m.group(2), head, count=1)
        if re.search(r'<span class="pj-caret"></span>\s*Filled\b', head):
            filled_visible = cnt
        out_rows.append(head); out_rows.extend(keep)
    s = s[:tb] + "".join(out_rows) + rtail + s[te:]
    if rec_hidden:
        s = re.sub(r'(<div class="rec-stat"><div class="rec-stat-num">)\d+(</div><div class="rec-stat-label">roles filled)',
                   lambda m: m.group(1) + str(filled_visible) + m.group(2), s, count=1)

if not hidden and not rec_hidden:
    print("nothing to hide"); sys.exit(0)
open(OUT, "w", encoding="utf-8").write(s)
print(f"open roles: hid {len(hidden)}: " + "; ".join(hidden))
print(f"recruiting activity: hid {len(rec_hidden)}: " + "; ".join(rec_hidden))
print(f"{n} roles remain; total row now {', '.join(fmt(v) for v in tot)}; wrote {OUT} ({len(s):,} bytes)")
