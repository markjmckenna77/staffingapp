// /api/allocate - make a staffing allocation for real (Oct 5 2026).
//
//   GET   { system: "netsuite", configured, dryRun, approver, ping? }   (ping=1, admins only)
//   POST  either { allocationId }                 push an existing proposed allocation
//         or     { consultant, project, hours, weeks, roleKey?, roleLabel?, roleTitle?, projectId?,
//                  note?, key?, label?, author?, week?, fillOpenRole? }
//                                                 record it in the allocations collection and push it
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
import { createAllocation, netsuiteConfigured, netsuiteDryRun, netsuitePing } from "@/lib/netsuite";
import { addDoc, getDoc, updateDoc } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const who = await actor();
  if (!who) return unauthorized();
  const out: Record<string, unknown> = {
    system: "netsuite", configured: netsuiteConfigured(), dryRun: netsuiteDryRun(), approver: isApprover(who),
  };
  if (new URL(req.url).searchParams.get("ping") === "1" && isAdmin(who)) out.ping = await netsuitePing();
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

    if (typeof b.allocationId === "string" && b.allocationId) {
      const cur = await getDoc("allocations", b.allocationId);
      if (!cur) throw Object.assign(new Error("not_found"), { code: "not_found" });
      id = cur.id;
      a = cur.body as unknown as AllocDoc;
      if (a.kind === "remove") return NextResponse.json({ error: "bad_body", detail: "removals are not pushed from here yet" }, { status: 400 });
      if (a.status === "entered") return NextResponse.json({ error: "already_entered", id }, { status: 409 });
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
