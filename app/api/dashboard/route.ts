// /api/dashboard - the weekly dashboard page itself (Oct 5 2026).
//   POST  body = the built dashboard HTML (text/html), header X-Note = e.g. "Oct 5 refresh".
//         Auth: Bearer IMPORT_TOKEN (the scheduled Monday refresh) or an admin session.
//   GET   metadata of the stored page (when it was uploaded, by whom, size).
// GET / (app/route.ts) serves the stored page when one exists, else dashboard/dashboard.html.
import { NextResponse } from "next/server";
import { actor, bearerOk, fail, isAdmin } from "@/lib/api";
import { getPageMeta, putPage } from "@/lib/store";

export const dynamic = "force-dynamic";
const MAX_BYTES = 6 * 1024 * 1024;

export async function GET() {
  if (!(await actor())) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  try {
    const meta = await getPageMeta("dashboard");
    return NextResponse.json(meta ?? { key: "dashboard", stored: false, note: "serving dashboard/dashboard.html from the deployment" });
  } catch (e) { return fail(e); }
}

export async function POST(req: Request) {
  const who = await actor();
  if (!bearerOk(req) && !isAdmin(who)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  try {
    const html = await req.text();
    if (html.length < 10_000 || html.length > MAX_BYTES) return NextResponse.json({ error: "bad_body", detail: `html must be 10 KB - 6 MB, got ${html.length}` }, { status: 400 });
    if (!/Cleartelligence Staffing Dashboard/.test(html) || !/id="staff-grid"/.test(html)) {
      return NextResponse.json({ error: "bad_body", detail: "does not look like the staffing dashboard page" }, { status: 400 });
    }
    // The pipeline's own guardrails, enforced once more at the door: no pay language, no excluded names.
    const text = html.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<[^>]+>/g, " ");
    const bad = /\bsalary\b|pay rate|hourly pay|\$\s?\d|\b\d{2,3}k\b|Ankitha Thirakala|Riddhima Shukla/i.exec(text);
    if (bad) return NextResponse.json({ error: "guardrail", detail: `page contains "${bad[0]}"` }, { status: 422 });
    const note = (req.headers.get("x-note") ?? "").slice(0, 200);
    const meta = await putPage("dashboard", html, who ?? "monday-refresh", note);
    return NextResponse.json({ ok: true, ...meta });
  } catch (e) { return fail(e); }
}
