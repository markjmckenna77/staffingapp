// /api/allocate - make a staffing allocation for real (Oct 5 2026).
//
//   GET   { system: "netsuite", configured, dryRun, approver, ping? }   (ping=1, admins only)
//   GET   ?consultant=Name[&from=YYYY-MM-DD]  -> { employeeName, allocations: [...] } the consultant's
//                                                 Resource Allocations in NetSuite (the consultant modal)
//   POST  either { allocationId }                 push an existing proposed allocation or removal
//         or     { consultant, project, hours, weeks, roleKey?, roleLabel?, roleTitle?, projectId?,
//                  note?, key?, label?, author?, week?, fillOpenRole? }
//                                                 record it in the allocations collection and push it
//         or     { kind: "remove", consultant, project, weeks, hours?, projectId?, note?, key?, label?,
//                  author?, week? }               take the consultant off the project for those weeks
//                                                 (Mark, Oct 21 2026: "unallocate") - the Resource
//                                                 Allocations are deleted, ended or split in NetSuite
//         or     { kind: "update", consultant, allocationId, startDate?, endDate?, hoursPerWeek?, note? }
//                                                 change one allocation's dates / weekly hours (0 hrs or an
//                                                 end before the start deletes it)
//         or     { kind: "reshape", consultant, project, projectId?, weeks: [{week, hours}], note? }
//                                                 week-by-week hours from the Outlook grid; only the weeks
//                                                 that differ from NetSuite are rewritten
//
// The write goes to NetSuite (lib/netsuite.ts), which is the system of record: Snowflake's
// CONS_* tables are rebuilt from NetSuite's Resource Allocations by Fivetran + dbt, so the
// dashboard's next refresh picks the allocation up without any direct Snowflake write. Until
// then the page shows it from the allocations collection (status "entered").
//
// Approvers only (APPROVER_EMAILS / ADMIN_EMAILS). When NetSuite is not configured the
// allocation is saved as a proposal and the response says so (409 netsuite_not_configured).
import { NextResponse } from "next/server";
import { actor, fail, isAdmin, isApprover, jsonBody, unauthorized } from "@/lib/api";
import { createAllocation, listAllocations, netsuiteConfigured, netsuiteDryRun, netsuitePing, removeAllocation, reshapeWeeks, updateAllocation } from "@/lib/netsuite";
import { addDoc, getDoc, updateDoc } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const who = await actor();
  if (!who) return unauthorized();
  const q = new URL(req.url).searchParams;
  const cons = (q.get("consultant") ?? "").trim();
  if (cons) {
    if (!netsuiteConfigured()) return NextResponse.json({ error: "netsuite_not_configured" }, { status: 409 });
    try {
      const listed = await listAllocations(cons, q.get("from") ?? undefined);
      return NextResponse.json({ ok: true, ...listed }, { headers: { "cache-control": "private, no-store" } });
    } catch (e) {
      const code = (e as { code?: string })?.code ?? "";
      if (code.startsWith("netsuite_")) return NextResponse.json({ error: code, detail: (e as { detail?: unknown }).detail ?? null }, { status: 502 });
      return fail(e);
    }
  }
  const out: Record<string, unknown> = {
    system: "netsuite", configured: netsuiteConfigured(), dryRun: netsuiteDryRun(), approver: isApprover(who),
  };
  if (q.get("ping") === "1" && isAdmin(who)) out.ping = await netsuitePing();
  return NextResponse.json(out, { headers: { "cache-control": "private, no-store" } });
}

type AllocDoc = {
  kind: "add" | "remove"; consultant: string; project: string; projectId?: number;
  roleKey: string; roleLabel: string; roleTitle: string; hours: number; weeks: string[];
  status: string; note: string; key: string; label: string; author: string; ts: number; week: string;
  fillOpenRole?: boolean;
};

function roleTitleOf(label: string): string {
  // Open-role labels read "Client: Role title"; the NetSuite allocation carries just the title.
  const i = label.indexOf(": ");
  return i > 0 ? label.slice(i + 2).trim() : label.trim();
}

export async function POST(req: Request) {
  const who = await actor();
  if (!who) return unauthorized();
  if (!isApprover(who)) return NextResponse.json({ error: "not_an_approver" }, { status: 403 });
  try {
    const b = await jsonBody(req);
    let id: string;
    let a: AllocDoc;

    if (b.kind === "update" || b.kind === "reshape") {
      if (!netsuiteConfigured()) return NextResponse.json({ error: "netsuite_not_configured" }, { status: 409 });
      const consultant = String(b.consultant ?? "").trim();
      if (!consultant) return NextResponse.json({ error: "bad_body", detail: "consultant is required" }, { status: 400 });
      const note = String(b.note ?? "").slice(0, 1000);
      const log: Record<string, unknown> = { kind: b.kind, consultant, note, key: String(b.key ?? ""), label: String(b.label ?? ""),
        author: String(b.author ?? who), ts: Date.now(), week: String(b.week ?? ""), status: "proposed" };
      let result: unknown;
      if (b.kind === "update") {
        const allocationId = Number(b.allocationId);
        if (!(allocationId > 0)) return NextResponse.json({ error: "bad_body", detail: "allocationId is required" }, { status: 400 });
        result = await updateAllocation({ consultant, allocationId,
          startDate: b.startDate ? String(b.startDate) : undefined, endDate: b.endDate ? String(b.endDate) : undefined,
          hoursPerWeek: b.hoursPerWeek === undefined || b.hoursPerWeek === null || b.hoursPerWeek === "" ? undefined : Number(b.hoursPerWeek),
          note, requestedBy: String(b.author ?? who) });
        Object.assign(log, { allocationId });
      } else {
        const project = String(b.project ?? "").trim();
        const weeks = Array.isArray(b.weeks) ? (b.weeks as Array<{ week?: unknown; hours?: unknown }>)
          .map((w) => ({ week: String(w?.week ?? ""), hours: Math.max(0, Number(w?.hours) || 0) }))
          .filter((w) => /^\d{4}-\d{2}-\d{2}$/.test(w.week)) : [];
        if (!project || !weeks.length) return NextResponse.json({ error: "bad_body", detail: "project and weeks [{week, hours}] are required" }, { status: 400 });
        result = await reshapeWeeks({ consultant, project,
          projectId: Number.isFinite(Number(b.projectId)) && Number(b.projectId) > 0 ? Number(b.projectId) : undefined,
          weeks, note, requestedBy: String(b.author ?? who) });
        Object.assign(log, { project, weeks });
      }
      const dry = (result as { dryRun?: boolean }).dryRun === true;
      Object.assign(log, dry ? { netsuitePreview: result, enteredSystem: "netsuite (dry run)" }
                             : { status: "entered", enteredTs: Date.now(), enteredBy: who, netsuite: result, enteredSystem: "netsuite" });
      const doc = await addDoc("allocations", log, who);
      return NextResponse.json({ ok: true, id: doc.id, kind: b.kind, dryRun: dry, netsuite: result });
    }

    if (typeof b.allocationId === "string" && b.allocationId) {
      const cur = await getDoc("allocations", b.allocationId);
      if (!cur) throw Object.assign(new Error("not_found"), { code: "not_found" });
      id = cur.id;
      a = cur.body as unknown as AllocDoc;
      if (a.status === "entered") return NextResponse.json({ error: "already_entered", id }, { status: 409 });
    } else if (b.kind === "remove") {
      const weeks = Array.isArray(b.weeks) ? (b.weeks as unknown[]).map(String).filter((w) => /^\d{4}-\d{2}-\d{2}$/.test(w)) : [];
      const consultant = String(b.consultant ?? "").trim();
      const project = String(b.project ?? "").trim();
      if (!consultant || !project || !weeks.length) {
        return NextResponse.json({ error: "bad_body", detail: "consultant, project and weeks (ISO Mondays) are required" }, { status: 400 });
      }
      a = {
        kind: "remove", consultant, project,
        projectId: Number.isFinite(Number(b.projectId)) && Number(b.projectId) > 0 ? Number(b.projectId) : undefined,
        roleKey: "", roleLabel: "", roleTitle: "",
        hours: Number(b.hours) > 0 ? Number(b.hours) : 0, weeks: weeks.sort(), status: "proposed", note: String(b.note ?? "").slice(0, 1000),
        key: String(b.key ?? ""), label: String(b.label ?? ""), author: String(b.author ?? who),
        ts: Date.now(), week: String(b.week ?? weeks[0]), fillOpenRole: false,
      };
      const doc = await addDoc("allocations", a as unknown as Record<string, unknown>, who);
      id = doc.id;
    } else {
      const weeks = Array.isArray(b.weeks) ? (b.weeks as unknown[]).map(String).filter((w) => /^\d{4}-\d{2}-\d{2}$/.test(w)) : [];
      const hours = Number(b.hours);
      const consultant = String(b.consultant ?? "").trim();
      const project = String(b.project ?? "").trim();
      if (!consultant || !project || !(hours > 0) || !weeks.length) {
        return NextResponse.json({ error: "bad_body", detail: "consultant, project, hours and weeks (ISO Mondays) are required" }, { status: 400 });
      }
      const roleLabel = String(b.roleLabel ?? "");
      a = {
        kind: "add", consultant, project,
        projectId: Number.isFinite(Number(b.projectId)) && Number(b.projectId) > 0 ? Number(b.projectId) : undefined,
        roleKey: String(b.roleKey ?? ""), roleLabel,
        roleTitle: String(b.roleTitle ?? "") || (roleLabel ? roleTitleOf(roleLabel) : ""),
        hours, weeks: weeks.sort(), status: "proposed", note: String(b.note ?? "").slice(0, 1000),
        key: String(b.key ?? ""), label: String(b.label ?? ""), author: String(b.author ?? who),
        ts: Date.now(), week: String(b.week ?? weeks[0]),
        fillOpenRole: b.fillOpenRole === undefined ? !!roleLabel : !!b.fillOpenRole,
      };
      const doc = await addDoc("allocations", a as unknown as Record<string, unknown>, who);
      id = doc.id;
    }

    if (!netsuiteConfigured()) {
      return NextResponse.json({ error: "netsuite_not_configured", id, status: "proposed",
        detail: "Saved as a proposal. Set NS_* in Vercel to push allocations to NetSuite." }, { status: 409 });
    }

    if (a.kind === "remove") {
      const removed = await removeAllocation({
        consultant: a.consultant, project: a.project, projectId: a.projectId, weeks: a.weeks, note: a.note, requestedBy: a.author || who,
      });
      const rpatch: Record<string, unknown> = removed.dryRun
        ? { netsuitePreview: removed, enteredSystem: "netsuite (dry run)" }
        : { status: "entered", enteredTs: Date.now(), enteredBy: who, netsuite: removed, enteredSystem: "netsuite" };
      const rdoc = await updateDoc("allocations", id, rpatch, who);
      return NextResponse.json({ ok: true, id, kind: "remove", status: rdoc.body.status, dryRun: removed.dryRun, netsuite: removed });
    }

    const result = await createAllocation({
      consultant: a.consultant, project: a.project, projectId: a.projectId, roleTitle: a.roleTitle || undefined,
      hours: a.hours, weeks: a.weeks, note: a.note, fillOpenRole: a.fillOpenRole ?? !!a.roleTitle, requestedBy: a.author || who,
    });

    const patch: Record<string, unknown> = result.dryRun
      ? { netsuitePreview: result, enteredSystem: "netsuite (dry run)" }
      : { status: "entered", enteredTs: Date.now(), enteredBy: who, netsuite: result, enteredSystem: "netsuite" };
    const doc = await updateDoc("allocations", id, patch, who);
    return NextResponse.json({ ok: true, id, status: doc.body.status, dryRun: result.dryRun, netsuite: result });
  } catch (e) {
    const code = (e as { code?: string })?.code ?? "";
    if (code.startsWith("netsuite_")) {
      console.error(code, (e as { detail?: unknown }).detail);
      return NextResponse.json({ error: code, detail: (e as { detail?: unknown }).detail ?? null }, { status: 502 });
    }
    return fail(e);
  }
}
