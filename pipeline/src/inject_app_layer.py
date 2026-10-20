#!/usr/bin/env python3
"""Fold the collaboration layer (staffing_app_layer.py) into a built dashboard.

Usage:  python3 inject_app_layer.py <source.html> [--full]

<source.html> may be either the artifact fragment written by build_dashboard.py
(dashboard_artifact.html) or the copy pulled back from the live artifact with
the Artifact tool's read action (which carries the platform's <!doctype ...>
<body> wrapper); the wrapper is detected and stripped.

Writes dashboard_artifact.html (fragment, for the Artifact tool) and
dashboard.html (standalone document, for SendUserFile).

What it changes in the built HTML - nothing else is touched:
  * appends APP_CSS to the <style> block
  * inserts the Meeting Log panel right after the Meeting Agenda panel
  * swaps each single-line `.role-comment` textarea (open roles, and the
    Capacity vs. Need commentary box) for a `.ct-mount` thread mount, keeping
    the same stable key so the old comments are carried into the new threads
  * appends APP_JS at the end of the fragment

Everything else in the app - the per-consultant, per-account and per-section
comment buttons, the allocation overlay, the week-over-week diff - is wired up
at run time from the rendered DOM, so a weekly data refresh needs no changes
here.
"""
import html
import re
import sys

import staffing_app_layer as APP

TITLE = "Cleartelligence Staffing Dashboard"


def strip_wrapper(doc):
    """Return the authored fragment from either a fragment or a wrapped page."""
    if not doc.lstrip().lower().startswith("<!doctype"):
        return doc
    i = doc.find("<body>")
    if i < 0:
        raise SystemExit("could not find <body> in the wrapped document")
    frag = doc[i + len("<body>"):]
    for tail in ("</body></html>", "</body>\n</html>\n", "</body>\n</html>"):
        if frag.rstrip().endswith(tail):
            frag = frag.rstrip()[: -len(tail)]
            break
    return frag.strip("\n")


def add_css(frag):
    i = frag.rfind("</style>")
    if i < 0:
        raise SystemExit("no </style> found")
    return frag[:i] + APP.APP_CSS + frag[i:]


def add_panel(frag):
    if 'id="meeting-log"' in frag:
        return frag
    i = frag.find('<section class="agenda-panel">')
    if i < 0:
        raise SystemExit("agenda panel not found")
    j = frag.find("</section>", i)
    if j < 0:
        raise SystemExit("agenda panel end not found")
    j += len("</section>")
    return frag[:j] + "\n\n" + APP.APP_HTML + frag[j:]


MOUNT = ('<div class="ct-mount{extra}" data-ct-key="{key}" data-ct-kind="{kind}" '
         'data-ct-label="{label}" role="button" tabindex="0" '
         'aria-label="Comments for {label}"></div>')

TEXTAREA_RE = re.compile(r'<textarea class="role-comment[^"]*"[^>]*?data-rk="([^"]+)"[^>]*>\s*</textarea>',
                         re.S)
ROLE_TITLE_RE = re.compile(r'<div class="demand-role">(.*?)</div>', re.S)


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ").strip()


HEAD_RE = re.compile(r'<h2 class="sec-head">(.*?)</h2>', re.S)


def heading_before(frag, pos):
    """Text of the nearest <h2 class="sec-head"> above pos, minus its sub-span."""
    best = None
    for m in HEAD_RE.finditer(frag):
        if m.start() > pos:
            break
        best = m
    if not best:
        return None
    inner = re.sub(r"<span.*?</span>", "", best.group(1), flags=re.S)
    return strip_tags(inner)


def swap_textareas(frag):
    titles = [strip_tags(t) for t in ROLE_TITLE_RE.findall(frag)]
    state = {"i": 0}

    def repl(m):
        rk = m.group(1)
        if rk.startswith("section-"):
            # a section commentary box: take its label from the heading above it, so the
            # mount and that heading's own comment button share one thread.
            label = heading_before(frag, m.start()) or rk[len("section-"):].replace("-", " ").title()
            return MOUNT.format(extra=" section-note", key="s:" + slug(label),
                                kind="section", label=html.escape(label, quote=True))
        idx = state["i"]
        state["i"] += 1
        label = titles[idx] if idx < len(titles) else rk
        return MOUNT.format(extra="", key="r:" + rk, kind="role",
                            label=html.escape(label, quote=True))

    return TEXTAREA_RE.sub(repl, frag)


def slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:110]


def add_js(frag):
    return frag.rstrip("\n") + "\n\n" + APP.APP_JS + "\n"


FOOT_EXTRA = (
    " The Meeting Log, the comment threads on every consultant, open role, client account and "
    "section heading, the action items and the proposed allocations all live in this page&#39;s "
    "shared data store on claude.ai: they are visible live to everyone who opens the page, are "
    "tagged with the meeting week they were written in, and survive the weekly data refresh. "
    "Proposed allocations are <b>not</b> written to Salesforce &mdash; they are held here, shown "
    "as a pending overlay on the 8 Week Outlook and the capacity table, and exported for entry. "
    "A downloaded copy of this page cannot reach any of it.")


def extend_footer(frag):
    marker = "a downloaded copy cannot reach it.</p>"
    if marker in frag:
        return frag.replace(marker, "a downloaded copy cannot reach it." + FOOT_EXTRA + "</p>", 1)
    i = frag.rfind("</p>\n</footer>")
    if i < 0:
        return frag
    return frag[:i] + FOOT_EXTRA + frag[i:]


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1]
    with open(src, encoding="utf-8") as fh:
        doc = fh.read()

    frag = strip_wrapper(doc)
    n_before = len(TEXTAREA_RE.findall(frag))
    frag = add_css(frag)
    frag = add_panel(frag)
    frag = swap_textareas(frag)
    frag = extend_footer(frag)
    frag = add_js(frag)

    with open("dashboard_artifact.html", "w", encoding="utf-8") as fh:
        fh.write(frag)

    style_end = frag.find("</style>") + len("</style>")
    head_css = frag[frag.find("<style>"):style_end]
    body = frag[style_end:].lstrip("\n")
    full = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'<title>{TITLE}</title>\n<style>\nbody {{ margin: 0; padding: 0; }}\n'
            f'{head_css[len("<style>"):]}\n</head>\n<body>\n{body}\n</body>\n</html>\n')
    with open("dashboard.html", "w", encoding="utf-8") as fh:
        fh.write(full)

    print(f"swapped {n_before} comment boxes for thread mounts; "
          f"fragment {len(frag):,} bytes, document {len(full):,} bytes")


if __name__ == "__main__":
    main()
