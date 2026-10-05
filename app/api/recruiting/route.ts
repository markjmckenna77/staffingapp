// /api/recruiting - the recruiting picture, live from Greenhouse (Oct 5 2026).
//
//   GET                 { source: "greenhouse", asOf, cachedAt, reqs: [...] }  (ATS JSON shape)
//   GET ?discover=1     custom-field keys and stage names the account uses (admins) - for GH_FIELD_*
//   GET ?fresh=1        bypass the 10-minute cache
// Auth: a signed-in session, or Bearer IMPORT_TOKEN (the Monday build pulls this instead of an xlsx).
// 503 greenhouse_not_configured until GREENHOUSE_API_KEY is set; the page then keeps the build-time data.
import { NextResponse } from "next/server";
import { actor, bearerOk, isAdmin } from "@/lib/api";
import { discover, greenhouseConfigured, pullRequisitions, type Req } from "@/lib/greenhouse";

export const dynamic = "force-dynamic";

let cache: { at: number; body: { asOf: string; reqs: Req[] } } | null = null;
const TTL = 10 * 60 * 1000;

export async function GET(req: Request) {
  const who = await actor();
  if (!who && !bearerOk(req)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const u = new URL(req.url);
  if (!greenhouseConfigured()) return NextResponse.json({ error: "greenhouse_not_configured" }, { status: 503 });
  try {
    if (u.searchParams.get("discover") === "1") {
      if (!isAdmin(who)) return NextResponse.json({ error: "not_an_admin" }, { status: 403 });
      return NextResponse.json(await discover());
    }
    if (!cache || u.searchParams.get("fresh") === "1" || Date.now() - cache.at > TTL) {
      cache = { at: Date.now(), body: await pullRequisitions() };
    }
    return NextResponse.json({ source: "greenhouse", cachedAt: new Date(cache.at).toISOString(), ...cache.body },
      { headers: { "cache-control": "private, no-store" } });
  } catch (e) {
    const code = (e as { code?: string })?.code ?? "error";
    console.error(code, (e as { detail?: unknown }).detail ?? e);
    return NextResponse.json({ error: code, detail: (e as { detail?: unknown }).detail ?? null }, { status: code.startsWith("greenhouse_") ? 502 : 500 });
  }
}
