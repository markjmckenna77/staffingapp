// POST /api/db/:collection - add a document with a generated id (Firestore's collection.add).
import { NextResponse } from "next/server";
import { actor, fail, jsonBody, unauthorized } from "@/lib/api";
import { addDoc } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function POST(req: Request, ctx: { params: Promise<{ collection: string }> }) {
  const who = await actor();
  if (!who) return unauthorized();
  try {
    const { collection } = await ctx.params;
    const doc = await addDoc(collection, await jsonBody(req), who);
    return NextResponse.json(doc, { status: 201 });
  } catch (e) {
    return fail(e);
  }
}
