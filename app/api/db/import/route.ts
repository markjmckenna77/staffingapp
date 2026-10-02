// POST /api/db/import - one-time bulk load of the claude.ai artifact's database (admins only).
// Body: { "collections": { "<collection>": { "<id>": { ...body } } } }. Existing documents with
// the same id are replaced; nothing is deleted. The page at /admin/import posts this.
import { NextResponse } from "next/server";
import { actor, fail, isAdmin, jsonBody } from "@/lib/api";
import { assertCollection, assertId, setDoc } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const who = await actor();
  if (!isAdmin(who)) return NextResponse.json({ error: "forbidden" }, { status: 403 });
  try {
    const body = await jsonBody(req);
    const cols = body.collections;
    if (!cols || typeof cols !== "object") throw Object.assign(new Error("bad_body"), { code: "bad_body" });
    const counts: Record<string, number> = {};
    for (const [c, docs] of Object.entries(cols as Record<string, Record<string, Record<string, unknown>>>)) {
      assertCollection(c);
      counts[c] = 0;
      for (const [id, doc] of Object.entries(docs ?? {})) {
        assertId(id);
        if (!doc || typeof doc !== "object") continue;
        await setDoc(c, id, doc, `${who} (import)`);
        counts[c]++;
      }
    }
    return NextResponse.json({ ok: true, counts });
  } catch (e) {
    return fail(e);
  }
}
