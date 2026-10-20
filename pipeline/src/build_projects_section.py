#!/usr/bin/env python3
"""Renders the 'Projects, Roles & Open Demand' section of the Cleartelligence
Staffing Dashboard - the project-first counterpart to the consultant-first
8 Week Outlook grid.

Added Sep 10 2026 at Mark's request: "a table that shows all projects, all roles,
all allocations, and all open roles listed by project for the next 8 weeks."

Structure (three row levels, one table):
  * client band row      - client name, project count, staffed headcount, open-role count
  * project row          - clickable; project name, PM, stage/status chips, and the
                           project's total allocated billable hours in each of the
                           8 weeks (with a "+n open" tag where unfilled demand sits)
  * detail rows (hidden) - one per assigned consultant (name, title, job-level chip)
                           and one per open role, each with hours per week

Cells are ALLOCATED BILLABLE HOURS per week, so a project row is the exact sum of
its detail rows and the grand-total row ties to the Capacity vs. Need table's
"Booked on projects" + "Open roles" rows.

Scope is CLIENT WORK SCHEDULED IN SALESFORCE. ATS-only requisitions (O.INTERNAL_ROLES)
are deliberately excluded - see build_projects().

Data: outlook_data.py (OUTLOOK_ALLOC, OPEN_DEMAND, OUTLOOK_STAFF) for the numbers,
projects_meta.py (PROJECT_META, CONSULTANT_TITLES) for client / PM / stage / title.
Holiday-shortened weeks use build_outlook_section.base_hours, so open-role demand in
those weeks is 4 days like everywhere else. CSS lives in dashboard_style.css.
"""
import html
import re
from collections import defaultdict

import outlook_data as O
import projects_meta as PM
from build_outlook_section import CLIENT_SHORT, base_hours

WEEKS = O.OUTLOOK_WEEKS
WL = O.WEEK_LABELS


def e(s):
    return html.escape(str(s), quote=True)


def hrs(v):
    """40.0 -> '40'; 20.51 -> '20.5'; 0 -> ''."""
    if v is None or v < 0.005:
        return ""
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:110]


# ---------------------------------------------------------------- shaping

def project_client(project):
    meta = PM.PROJECT_META.get(project)
    if meta:
        return meta[0]
    for r in O.OPEN_DEMAND:
        if r["project"] == project:
            return r["client"]
    return project


def build_projects():
    """[{project, client, pm, status, stage, staff: [...], roles: [...],
         staff_wk, open_wk, total_wk}] - one entry per project in the window."""
    # staffed hours: (project, consultant) -> {week: hours}
    staffed = defaultdict(lambda: defaultdict(float))
    for (name, wk), allocs in O.OUTLOOK_ALLOC.items():
        for h, proj in allocs:
            staffed[(proj, name)][wk] += h

    # Salesforce-scheduled demand ONLY.
    #
    # O.INTERNAL_ROLES is the ATS side of the join: requisitions with no Salesforce
    # demand line - the practice-director / marketing / delivery-lead searches, and
    # any client requisition Salesforce has not scheduled. Those records carry a
    # PRACTICE NAME in "project" and either "Cleartelligence (internal)" or a bare
    # client string in "client", so feeding them in here invented client bands named
    # "AI Engineering", "Data Management", "Marketing", "Solutions Architecture",
    # "Delivery Mangement · Mantis" and "Data Visualization & Analytics (no scheduled
    # demand in Salesforce)" - none of which is a client or a project. Mark flagged it
    # on Sep 14 2026; they are out of this section for good.
    #
    # They still render in Open Roles & Recruiting and in Recruiting Activity, which is
    # where a requisition with no scheduled work belongs. They carry hrs=0 and
    # weeks=[], so excluding them moves no hours in any row or total.
    roles_by_proj = defaultdict(list)
    for r in O.OPEN_DEMAND:
        roles_by_proj[r["project"]].append(r)

    names = sorted({p for p, _ in staffed} | set(roles_by_proj))
    out = []
    for proj in names:
        meta = PM.PROJECT_META.get(proj)
        client, pm, status, stage = meta if meta else (project_client(proj), "", "", "")
        staff = []
        for (p, name), weeks in staffed.items():
            if p != proj:
                continue
            title, level = PM.CONSULTANT_TITLES.get(name, ("", ""))
            practice = O.OUTLOOK_STAFF.get(name, {}).get("practice", "")
            staff.append({"name": name, "title": norm(title), "level": level,
                          "practice": practice, "weeks": dict(weeks),
                          "total": sum(weeks.values())})
        staff.sort(key=lambda s: (-s["total"], s["name"]))

        roles = []
        for r in roles_by_proj.get(proj, []):
            weeks = {wk: r["hrs"] * base_hours(wk) / 8.0 for wk in r.get("weeks") or []}
            roles.append({**r, "weeks": weeks, "total": sum(weeks.values())})
        roles.sort(key=lambda r: (-r["total"], r["role"]))

        staff_wk = {wk: sum(s["weeks"].get(wk, 0.0) for s in staff) for wk in WEEKS}
        open_wk = {wk: sum(r["weeks"].get(wk, 0.0) for r in roles) for wk in WEEKS}
        out.append({"project": proj, "client": client, "pm": pm, "status": status,
                    "stage": stage, "staff": staff, "roles": roles,
                    "staff_wk": staff_wk, "open_wk": open_wk,
                    "total": sum(staff_wk.values()) + sum(open_wk.values())})
    return out


# ---------------------------------------------------------------- rows

NCOLS = len(WEEKS) + 1


def wk_cells(weeks, cls, open_weeks=None):
    cells = []
    for wk in WEEKS:
        v = weeks.get(wk, 0.0)
        o = (open_weeks or {}).get(wk, 0.0)
        txt = hrs(v)
        tag = (f'<span class="pj-open-tag">+{hrs(o)} open</span>') if o > 0.005 else ""
        if not txt and not tag:
            # carries data-h="0" like every other cell so a column-wise reader can index
            # td.wk [data-h] positionally without empty weeks shifting the alignment
            cells.append('<td class="wk"><div class="pj-cell pj-cell-empty" data-h="0">'
                         "&mdash;</div></td>")
            continue
        # a project week with open demand but nobody booked reads as a dash, not "0"
        h_span = (f'<span class="pj-h">{txt}</span>' if txt
                  else '<span class="pj-h pj-h-zero">&mdash;</span>')
        body = f'{h_span}{tag}'
        cells.append(f'<td class="wk"><div class="pj-cell {cls}" data-h="{v + o:g}">{body}</div></td>')
    return "".join(cells)


def client_row(client, rows, cid):
    """Client roll-up: the sum of its projects' weekly hours, with the projects
    collapsed underneath (Mark, Sep 14 2026). Previously this was a name-only band and
    every project sat open below it, so the section opened at 84 rows with no way to
    read a client as one line."""
    n_open = sum(len(p["roles"]) for p in rows)
    people = {s["name"] for p in rows for s in p["staff"]}
    staff_wk = {wk: sum(p["staff_wk"].get(wk, 0.0) for p in rows) for wk in WEEKS}
    open_wk = {wk: sum(p["open_wk"].get(wk, 0.0) for p in rows) for wk in WEEKS}
    chips = [f'<span class="count-chip">{len(rows)} project{"s" if len(rows) > 1 else ""}</span>',
             f'<span class="count-chip">{len(people)} consultant{"s" if len(people) != 1 else ""}</span>']
    if n_open:
        chips.append(f'<span class="count-chip pj-chip-open">{n_open} open</span>')
    label = (f'<button type="button" class="pj-toggle pj-client-toggle" aria-expanded="false" '
             f'aria-controls="{cid}" data-target="{cid}" '
             f'aria-label="Show the {len(rows)} project{"s" if len(rows) != 1 else ""} '
             f'for {e(client)}">'
             f'<span class="pj-caret" aria-hidden="true"></span>'
             f'<span class="pj-client-name">{e(client)}</span></button> '
             + " ".join(chips))
    return (f'<tr class="pj-client-row" data-cl="{cid}">'
            f'<td class="col-pj-name">{label}</td>'
            f'{wk_cells(staff_wk, "pj-cell-client", open_wk)}</tr>')


def project_row(p, idx, cid):
    pid = f"pj-{idx}-{slug(p['project'])}"
    n_staff = len(p["staff"])
    n_roles = len(p["roles"])
    chips = []
    if p["stage"] and p["stage"] != "Won / Closed":
        chips.append(f'<span class="chip chip-stage">{e(p["stage"])}</span>')
    if p["status"] and p["status"] != "In Progress":
        chips.append(f'<span class="chip">{e(p["status"])}</span>')
    if p["pm"]:
        chips.append(f'<span class="chip chip-quiet">PM {e(p["pm"])}</span>')
    chips.append(f'<span class="chip chip-quiet">{n_staff} assigned</span>'
                 if n_staff else '<span class="chip chip-quiet">no one assigned</span>')
    if n_roles:
        chips.append(f'<span class="chip pj-chip-open">{n_roles} open role'
                     f'{"s" if n_roles > 1 else ""}</span>')
    n_detail = n_staff + n_roles
    label = (f'<button type="button" class="pj-toggle" aria-expanded="false" '
             f'aria-controls="{pid}" data-target="{pid}" '
             f'aria-label="Show the {n_detail} staffing line'
             f'{"s" if n_detail != 1 else ""} on {e(p["project"])}">'
             f'<span class="pj-caret" aria-hidden="true"></span>'
             f'<span class="pj-name">{e(p["project"])}</span></button>'
             f'<div class="chip-row">{"".join(chips)}</div>')
    return (f'<tr class="pj-row" data-pj="{pid}" data-client="{cid}" hidden>'
            f'<td class="col-pj-name pj-indent-proj">{label}</td>'
            f'{wk_cells(p["staff_wk"], "pj-cell-total", p["open_wk"])}</tr>')


def staff_row(p, s, pid):
    lvl = f'<span class="pj-level">{e(s["level"])}</span>' if s["level"] else ""
    title = f'<span class="pj-title">{e(s["title"])}</span>' if s["title"] else \
            f'<span class="pj-title pj-title-none">{e(s["practice"])}</span>'
    return (f'<tr class="pj-detail" data-parent="{pid}" hidden>'
            f'<td class="col-pj-name pj-indent">'
            f'<span class="pj-person">{e(s["name"])}</span>{lvl}<br>{title}</td>'
            f'{wk_cells(s["weeks"], "pj-cell-staff")}</tr>')


def role_row(p, r, pid):
    bits = [f'<span class="pj-open-role">{e(r["role"])}</span>',
            '<span class="pj-open-badge">OPEN</span>']
    sub = []
    if r.get("stage"):
        sub.append(e(r["stage"]))
    if r.get("prob") is not None:
        sub.append(f'{r["prob"]}%')
    if r.get("cat"):
        sub.append(e(r["cat"]))
    if r.get("geo"):
        sub.append(e({"us": "US", "eu": "EU", "india": "India (CTI)"}.get(r["geo"], r["geo"])))
    subline = (f'<br><span class="pj-title">{" &middot; ".join(sub)}</span>') if sub else ""
    return (f'<tr class="pj-detail pj-detail-open" data-parent="{pid}" hidden>'
            f'<td class="col-pj-name pj-indent">{"".join(bits)}{subline}</td>'
            f'{wk_cells(r["weeks"], "pj-cell-open")}</tr>')


def total_row(projects):
    staffed = {wk: sum(p["staff_wk"][wk] for p in projects) for wk in WEEKS}
    opened = {wk: sum(p["open_wk"][wk] for p in projects) for wk in WEEKS}
    cells = "".join(
        f'<td class="wk"><div class="pj-cell pj-cell-grand">'
        f'<span class="pj-h">{staffed[wk]:,.0f}</span>'
        + (f'<span class="pj-open-tag">+{opened[wk]:,.0f} open</span>' if opened[wk] > 0.005 else "")
        + "</div></td>" for wk in WEEKS)
    return (f'<tr class="pj-grand-row"><td>All projects &mdash; allocated hrs/wk'
            f'</td>{cells}</tr>')


TOGGLE_JS = """<script>
(function () {
  var table = document.getElementById("projects-table");
  if (!table) return;
  var allClients = document.getElementById("projects-expand-clients");
  var allProjects = document.getElementById("projects-expand-all");

  function mark(tr, open) {
    tr.classList.toggle("pj-open", open);
    var btn = tr.querySelector(".pj-toggle");
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  // a project row shows its consultant / open-role lines
  function setProject(tr, open) {
    var pid = tr.dataset.pj;
    table.querySelectorAll('tr.pj-detail[data-parent="' + pid + '"]').forEach(function (d) {
      d.hidden = !open;
    });
    mark(tr, open);
  }

  // a client row shows its projects; closing it closes their details too, so the
  // section never keeps hidden rows in a half-open state
  function setClient(tr, open) {
    var cid = tr.dataset.cl;
    table.querySelectorAll('tr.pj-row[data-client="' + cid + '"]').forEach(function (p) {
      p.hidden = !open;
      if (!open) setProject(p, false);
    });
    mark(tr, open);
  }

  table.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest ? ev.target.closest(".pj-toggle") : null;
    if (!btn) return;
    var clientTr = btn.closest("tr.pj-client-row");
    if (clientTr) { setClient(clientTr, !clientTr.classList.contains("pj-open")); return; }
    var tr = btn.closest("tr.pj-row");
    if (tr) setProject(tr, !tr.classList.contains("pj-open"));
  });

  function wire(btn, labelOpen, labelShut, fn) {
    if (!btn) return;
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-pressed") !== "true";
      btn.setAttribute("aria-pressed", open ? "true" : "false");
      btn.classList.toggle("outlook-btn-active", open);
      btn.textContent = open ? labelOpen : labelShut;
      fn(open);
    });
  }

  wire(allClients, "Collapse all clients", "Expand all clients", function (open) {
    table.querySelectorAll("tr.pj-client-row").forEach(function (tr) { setClient(tr, open); });
    if (!open && allProjects) {
      allProjects.setAttribute("aria-pressed", "false");
      allProjects.classList.remove("outlook-btn-active");
      allProjects.textContent = "Expand all projects";
    }
  });

  // expanding every project implies expanding every client, or the rows stay hidden
  wire(allProjects, "Collapse all projects", "Expand all projects", function (open) {
    if (open) {
      table.querySelectorAll("tr.pj-client-row").forEach(function (tr) { setClient(tr, true); });
      if (allClients) {
        allClients.setAttribute("aria-pressed", "true");
        allClients.classList.add("outlook-btn-active");
        allClients.textContent = "Collapse all clients";
      }
    }
    table.querySelectorAll("tr.pj-row").forEach(function (tr) { setProject(tr, open); });
  });
})();
</script>"""


def section_projects():
    projects = build_projects()
    by_client = defaultdict(list)
    for p in projects:
        by_client[p["client"]].append(p)

    head = "".join(f'<th class="wk">{WL[w]}</th>' for w in WEEKS)
    out = ['      <div class="outlook-scroll"><table class="outlook-table projects-grid" id="projects-table">',
           f'        <thead><tr><th>Client / project / role</th>{head}</tr></thead>',
           "        <tbody>"]
    idx = 0
    for ci, client in enumerate(sorted(by_client, key=lambda c: c.lower()), 1):
        rows = sorted(by_client[client], key=lambda p: (-p["total"], p["project"]))
        cid = f"cl-{ci}-{slug(client)}"
        out.append(client_row(CLIENT_SHORT.get(client, client), rows, cid))
        for p in rows:
            idx += 1
            pid = f"pj-{idx}-{slug(p['project'])}"
            out.append(project_row(p, idx, cid))
            for s in p["staff"]:
                out.append(staff_row(p, s, pid))
            for r in p["roles"]:
                out.append(role_row(p, r, pid))
    out.append(total_row(projects))
    out.append("        </tbody>")
    out.append("      </table></div>")
    out.append(TOGGLE_JS)
    grid = "\n".join(out)

    n_proj = len(projects)
    n_clients = len(by_client)
    n_roles = sum(len(p["roles"]) for p in projects)
    controls = """      <div class="outlook-controls">
        <button type="button" class="outlook-btn" id="projects-expand-clients" aria-pressed="false">Expand all clients</button>
        <button type="button" class="outlook-btn" id="projects-expand-all" aria-pressed="false">Expand all projects</button>
        <span class="s3-tabs-note">every client rolls up its projects &middot; click a client for its projects, then a project for who is on it &middot; cells are allocated billable <b>hours per week</b> &middot; unfilled demand shows as <b>+n open</b> &middot; client work only &mdash; internal and SG&amp;A requisitions have no Salesforce project, so they sit in Open Roles &amp; Recruiting</span>
      </div>"""
    return f"""<section class="section4 projects-section">
  <h2 class="sec-head">Projects, Roles &amp; Open Demand <span class="section4-range">{n_proj} projects &middot; {n_clients} clients &middot; {n_roles} open roles &middot; weeks of {WL[WEEKS[0]]} &ndash; {WL[WEEKS[-1]]}</span></h2>
  <textarea class="role-comment section-note" data-rk="section-projects-roles" rows="1"
    placeholder="Add commentary on project staffing &mdash; shared with everyone who opens the live page"
    aria-label="Commentary on projects and roles"></textarea>
{controls}
{grid}
</section>"""


if __name__ == "__main__":
    projects = build_projects()
    with open("projects_section.html", "w", encoding="utf-8") as fh:
        fh.write(section_projects())
    for wk in WEEKS:
        st = sum(p["staff_wk"][wk] for p in projects)
        op = sum(p["open_wk"][wk] for p in projects)
        print(f"{WL[wk]:>7}: staffed {st:8.1f} (OUTLOOK_BOOKED {O.OUTLOOK_BOOKED[wk]:8.1f})  open {op:6.1f}")
    print(f"projects={len(projects)} "
          f"staff_lines={sum(len(p['staff']) for p in projects)} "
          f"role_lines={sum(len(p['roles']) for p in projects)}")
    missing = sorted({s["name"] for p in projects for s in p["staff"] if not s["title"]})
    if missing:
        print("no title on file:", missing)
    # A practice name showing up as a client means INTERNAL_ROLES has leaked back in.
    PRACTICES = {"AI Engineering", "Data Management", "Marketing", "Solutions Architecture",
                 "Solution Architecture", "Delivery", "Portfolio Mgmt"}
    leaked = sorted({p["client"] for p in projects
                     if p["client"] in PRACTICES or p["client"] == p["project"]})
    if leaked:
        print("WARNING - non-client bands in the projects table:", leaked)
