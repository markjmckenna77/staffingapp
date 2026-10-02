// GET / — serves the weekly staffing dashboard (dashboard/dashboard.html) to signed-in users.
//
// Option A (Oct 2 2026): the dashboard is still generated weekly by the Python pipeline
// (see staffing-dashboard-refresh-runbook.md) and committed here as a static file. This
// route wraps it with a slim session bar. /live hosts the Snowflake-backed sections as they
// are ported (phase 1); each one replaces its static counterpart once verified.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";

const DASHBOARD = path.join(process.cwd(), "dashboard", "dashboard.html");

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
}

export async function GET() {
  const session = await auth();
  const email = session?.user?.email ?? "";

  let html: string;
  try {
    html = await readFile(DASHBOARD, "utf-8");
  } catch {
    return new Response("dashboard/dashboard.html is missing from this deployment.", { status: 500 });
  }

  // Session bar: fixed, self-contained styles (sa- prefix) so nothing collides with the dashboard CSS.
  const bar = `
<style>
  .sa-bar{position:sticky;top:0;z-index:9999;display:flex;align-items:center;gap:14px;
    padding:6px 16px;font:12px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    background:#101418;color:#c9d1d9;border-bottom:1px solid #2a3139}
  .sa-bar b{color:#fff;font-weight:600}
  .sa-bar .sa-sp{flex:1}
  .sa-bar a{color:#9ecbff;text-decoration:none}
  .sa-bar a:hover{text-decoration:underline}
  .sa-bar a.sa-btn{color:#c9d1d9;border:1px solid #3a424c;border-radius:5px;padding:3px 10px}
  .sa-bar a.sa-btn:hover{border-color:#9ecbff;color:#fff;text-decoration:none}
</style>
<div class="sa-bar">
  <b>Cleartelligence Staffing</b>
  <a href="/live">Live data (beta)</a>
  <span class="sa-sp"></span>
  <span>${esc(email)}</span>
  <a class="sa-btn" href="/api/auth/signout">Sign out</a>
</div>`;

  const out = html.replace(/<body([^>]*)>/i, (m) => m + bar);

  return new Response(out, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "private, no-store",
    },
  });
}
