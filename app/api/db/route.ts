// GET /api/db?c=threads,actions[&since=<ms>] - documents in one or more collections.
// With `since`, only documents changed after that server timestamp are returned, tombstones
// included, so the page's shim can poll cheaply and reconcile deletes. `now` in the response
// is the timestamp to pass as the next `since`.
import { NextResponse } from "next/server";
import { actor, fail, unauthorized } from "@/lib/api";
import { listDocs } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  if (!(await actor())) return unauthorized();
  const url = new URL(req.url);
  const cols = (url.searchParams.get("c") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  const since = Number(url.searchParams.get("since") ?? 0) || 0;
  if (!cols.length) return NextResponse.json({ error: "bad_body" }, { status: 400 });
  // Taken before the reads so a write landing mid-request is picked up by the next poll.
  const now = Date.now() - 1;
  try {
    const out: Record<string, unknown> = {};
    for (const c of cols) out[c] = await listDocs(c, since);
    return NextResponse.json({ now, since, collections: out }, { headers: { "cache-control": "private, no-store" } });
  } catch (e) {
    return fail(e);
  }
}
