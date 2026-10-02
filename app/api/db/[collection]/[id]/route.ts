// /api/db/:collection/:id - one document: GET, PUT (replace), PATCH (merge), DELETE.
import { NextResponse } from "next/server";
import { actor, fail, isApprover, jsonBody, unauthorized } from "@/lib/api";
import { certiniaConfigured, enterAllocation } from "@/lib/certinia";
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

    // Marking a proposed allocation "entered" is the moment it becomes real: when Certinia is
    // configured, write the assignment to Salesforce first and record its ids on the document.
    // If Salesforce refuses, nothing changes here and the page shows the error code.
    if (collection === "allocations" && patch.status === "entered" && certiniaConfigured()) {
      if (!isApprover(who)) return NextResponse.json({ error: "not_an_approver" }, { status: 403 });
      const cur = await getDoc(collection, id);
      if (!cur) throw Object.assign(new Error("not_found"), { code: "not_found" });
      const a = cur.body as Record<string, unknown>;
      const result = await enterAllocation({
        id, kind: a.kind === "remove" ? "remove" : "add",
        consultant: String(a.consultant ?? ""), project: String(a.project ?? ""),
        roleLabel: String(a.roleLabel ?? ""), hours: Number(a.hours ?? 0),
        weeks: Array.isArray(a.weeks) ? (a.weeks as string[]) : [], note: String(a.note ?? ""),
      });
      patch = { ...patch, enteredBy: who, salesforce: result, enteredSystem: result.dryRun ? "certinia (dry run)" : "certinia" };
    }

    return NextResponse.json(await updateDoc(collection, id, patch, who));
  } catch (e) {
    const code = (e as { code?: string })?.code ?? "";
    if (code.startsWith("certinia_")) {
      console.error(e);
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
