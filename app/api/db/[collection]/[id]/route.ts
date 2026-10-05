// /api/db/:collection/:id - one document: GET, PUT (replace), PATCH (merge), DELETE.
import { NextResponse } from "next/server";
import { actor, fail, isApprover, jsonBody, unauthorized } from "@/lib/api";
import { createAllocation, netsuiteConfigured } from "@/lib/netsuite";
import { deleteDoc, getDoc, setDoc, updateDoc } from "@/lib/store";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ collection: string; id: string }> };

export async function GET(_req: Request, ctx: Ctx) {
  if (!(await actor())) return unauthorized();
  try {
    const { collection, id } = await ctx.params;
    const doc = await getDoc(collection, id);
    return NextResponse.json(doc ? { exists: true, ...doc } : { exists: false, id }, { headers: { "cache-control": "private, no-store" } });
  } catch (e) {
    return fail(e);
  }
}

export async function PUT(req: Request, ctx: Ctx) {
  const who = await actor();
  if (!who) return unauthorized();
  try {
    const { collection, id } = await ctx.params;
    return NextResponse.json(await setDoc(collection, id, await jsonBody(req), who));
  } catch (e) {
    return fail(e);
  }
}

export async function PATCH(req: Request, ctx: Ctx) {
  const who = await actor();
  if (!who) return unauthorized();
  try {
    const { collection, id } = await ctx.params;
    let patch = await jsonBody(req);

    // Marking a proposed allocation "entered" is the moment it becomes real: when NetSuite is
    // configured, create the Resource Allocation there first and record its ids on the document.
    // If NetSuite refuses, nothing changes here and the page shows the error code. (The page's
    // Allocate button uses POST /api/allocate, which does the same in one step; this path keeps
    // the Meeting Log's "Enter in NetSuite" button honest.) Removals are still recorded only.
    if (collection === "allocations" && patch.status === "entered" && netsuiteConfigured()) {
      if (!isApprover(who)) return NextResponse.json({ error: "not_an_approver" }, { status: 403 });
      const cur = await getDoc(collection, id);
      if (!cur) throw Object.assign(new Error("not_found"), { code: "not_found" });
      const a = cur.body as Record<string, unknown>;
      if (a.kind !== "remove" && a.status !== "entered") {
        const roleLabel = String(a.roleLabel ?? "");
        const roleTitle = String(a.roleTitle ?? "") || (roleLabel.includes(": ") ? roleLabel.slice(roleLabel.indexOf(": ") + 2) : roleLabel);
        const result = await createAllocation({
          consultant: String(a.consultant ?? ""), project: String(a.project ?? ""),
          projectId: Number(a.projectId) > 0 ? Number(a.projectId) : undefined,
          roleTitle: roleTitle || undefined, hours: Number(a.hours ?? 0),
          weeks: Array.isArray(a.weeks) ? (a.weeks as string[]) : [], note: String(a.note ?? ""),
          fillOpenRole: a.fillOpenRole === undefined ? !!roleTitle : !!a.fillOpenRole, requestedBy: String(a.author ?? who),
        });
        patch = result.dryRun
          ? { ...patch, status: "proposed", netsuitePreview: result, enteredSystem: "netsuite (dry run)" }
          : { ...patch, enteredBy: who, netsuite: result, enteredSystem: "netsuite" };
      }
    }

    return NextResponse.json(await updateDoc(collection, id, patch, who));
  } catch (e) {
    const code = (e as { code?: string })?.code ?? "";
    if (code.startsWith("netsuite_")) {
      console.error(code, (e as { detail?: unknown }).detail);
      return NextResponse.json({ error: code, detail: (e as { detail?: unknown }).detail ?? null }, { status: 502 });
    }
    return fail(e);
  }
}

export async function DELETE(_req: Request, ctx: Ctx) {
  const who = await actor();
  if (!who) return unauthorized();
  try {
    const { collection, id } = await ctx.params;
    await deleteDoc(collection, id, who);
    return NextResponse.json({ ok: true });
  } catch (e) {
    return fail(e);
  }
}
