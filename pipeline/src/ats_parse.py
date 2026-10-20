#!/usr/bin/env python3
"""Parses the recruiting ATS export (all_jobs_status_report_*.xlsx) into the shapes
outlook_data carries: an `ats` dict per matched open-demand role, plus a list of
requisitions that have no Salesforce demand line, plus the RECRUITING_WEEK summary.

COMPENSATION NEVER LEAVES THIS MODULE. The export carries Cost, Annual Salary and
Hourly Pay Rate columns, and recruiters sometimes put figures in the free-text status
notes as well ("Salary likely on low end... $220k-240k is more realistic"). The banned
columns are dropped at read time and `scrub()` removes any sentence carrying money or
pay language before the note is ever returned.
"""
import re
from datetime import datetime

import openpyxl

BANNED_COLS = {"Cost", "Annual Salary (FTE only)", "Hourly Pay Rate (Contract only)"}
MONEY = re.compile(r"\$|\bsalary\b|\bcomp\b|\bpay\b|\brate[sd]?\b|\bk-\d|\d{2,3}k\b|"
                   r"\bbill(?:ing)?\b|\bcost\b|\bbudget\b", re.I)


def scrub(text):
    """Drop any sentence that mentions money or pay. Recruiters put figures in notes."""
    out = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]
    return " ".join(s for s in out if not MONEY.search(s))


def latest_note(notes):
    """Status notes are a reverse-chronological log, newest line first."""
    for line in (notes or "").splitlines():
        line = line.strip()
        if line:
            return scrub(line)
    return ""


def load(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Data"]
    hdr = [c.value for c in ws[1]]
    keep = [i for i, h in enumerate(hdr) if h not in BANNED_COLS]
    reqs = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        r = {hdr[i]: row[i] for i in keep}
        opened = r.get("Open Date (Job)")
        reqs.append({
            "job": (r.get("Job Name") or "").strip(),
            "client": (r.get("Client") or "").strip(),
            "portfolio": (r.get("Portfolio") or "").strip(),
            "department": (r.get("Department") or "").strip(),
            "offices": (r.get("Offices") or "").strip(),
            "emp": (r.get("Employment Type") or "").strip(),
            "openings": r.get("Number of openings"),
            "manager": (r.get("Manager") or "").strip(),
            "start": (r.get("Anticipated Start Date") or "").strip(),
            "opened": opened.date().isoformat() if isinstance(opened, datetime) else str(opened or ""),
            "days_open": r.get("Days Open (Job)"),
            "recruiter": (r.get("Primary Recruiter") or "").strip(),
            "interviewing": r.get("Candidates Interviewing"),
            "update": latest_note(r.get("Status notes")),
            "history": [scrub(l) for l in (r.get("Status notes") or "").splitlines() if l.strip()],
        })
    return reqs


def geo_of(offices):
    o = (offices or "").lower()
    if "cti" in o or "hyderabad" in o or "india" in o:
        return "india"
    if "london" in o or "eu" in o or "europe" in o:
        return "eu"
    return "us"


if __name__ == "__main__":
    for q in load("ats_2026-09-11.xlsx"):
        print(f"{q['job']}\n   client={q['client']!r} dept={q['department']} geo={geo_of(q['offices'])} "
              f"interviewing={q['interviewing']} start={q['start']} open {q['days_open']}d "
              f"recruiter={q['recruiter']}\n   update: {q['update']}")
