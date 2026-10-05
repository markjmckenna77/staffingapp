// GET / — serves the weekly staffing dashboard (dashboard/dashboard.html) to signed-in users.
//
// Option A (Oct 2 2026): the dashboard is still generated weekly by the Python pipeline
// (see staffing-dashboard-refresh-runbook.md) and committed here as a static file. This
// route wraps it with a slim session bar. /live hosts the Snowflake-backed sections as they
// are ported (phase 1); each one replaces its static counterpart once verified.
//
// The wrapper also injects public/sa-shim.js, which gives the page the window.claude.use("db")
// store it was written against, backed by /api/db (Postgres) instead of the claude.ai artifact.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { auth } from "@/auth";
import { getPage } from "@/lib/store";

export const dynamic = "force-dynamic";

const DASHBOARD = path.join(process.cwd(), "dashboard", "dashboard.html");

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
}

// The page's "this copy can't reach claude.ai" notes no longer describe the failure mode: the
// store is here now, so an outage means the database is unreachable or not configured yet.
const STORE_DOWN = "The shared store isn't reachable right now - check that the database is configured for this deployment.";
const OFFLINE_NOTES = [
  "Comments work on the live dashboard page on claude.ai - this copy can't save them.",
  "The shared agenda works on the live dashboard page on claude.ai - this copy can't reach it.",
  "The meeting log lives on the live dashboard page on claude.ai - this copy can't reach it.",
  "Action items live on the live dashboard page on claude.ai - this copy can't reach them.",
];

export async function GET() {
  const session = await auth();
  const email = session?.user?.email ?? "";
  const name = session?.user?.name ?? "";

  // The Monday refresh uploads the built page to /api/dashboard (stored in Postgres); the file
  // committed with the deployment is the fallback for a fresh database.
  let html: string | null = null;
  try { html = (await getPage("dashboard"))?.html ?? null; } catch { html = null; }
  if (html === null) {
    try {
      html = await readFile(DASHBOARD, "utf-8");
    } catch {
      return new Response("No dashboard has been uploaded and dashboard/dashboard.html is missing from this deployment.", { status: 500 });
    }
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
  /* The bar is sticky and above everything, so anything the dashboard pins to the top of the
     viewport must start below it: the comment/allocation drawer (its title and × close button
     were hidden under the bar, Oct 2 2026) and the 8 Week Outlook's sticky week header. */
  .ct-drawer,.ct-scrim{top:var(--sa-bar-h,37px)!important}
  #staff-grid thead th{top:var(--sa-bar-h,37px)!important}
  /* Oct 2 2026 (Mark): the standalone Action Items panel is retired - action items live in the
     Meeting Log's "Open actions" view, fed by the ✎ drawers and the Granola import. */
  #action-items{display:none!important}
</style>
<div class="sa-bar">
  <b>Cleartelligence Staffing</b>
  <a href="/live">Live data (beta)</a>
  <span class="sa-sp"></span>
  <span>${esc(email)}</span>
  <a class="sa-btn" href="/api/auth/signout">Sign out</a>
</div>
<script>
window.__saUser=${JSON.stringify({ email, name })};
(function(){
  var bar=document.querySelector(".sa-bar");if(!bar)return;
  function fit(){document.documentElement.style.setProperty("--sa-bar-h",bar.offsetHeight+"px");}
  fit();window.addEventListener("resize",fit);
  if(window.ResizeObserver)new ResizeObserver(fit).observe(bar);
})();
</script>
<script src="/sa-shim.js"></script>`;

  // The pipeline emits the page as a fragment (<title>, <style>, sections) because the old
  // claude.ai artifact host added the document skeleton. Give it one here when it is missing.
  if (!/<body[\s>]/i.test(html)) {
    const t = /^\s*<title>[\s\S]*?<\/title>/i.exec(html);
    const title = t ? t[0].trim() : "<title>Cleartelligence Staffing Dashboard</title>";
    const rest = t ? html.slice(t[0].length) : html;
    html = `<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n${title}\n</head>\n<body>\n${rest}\n</body>\n</html>\n`;
  }
  let out = html.replace(/<body([^>]*)>/i, (m) => m + bar);
  for (const note of OFFLINE_NOTES) out = out.split(note).join(STORE_DOWN);

  return new Response(out, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "private, no-store",
    },
  });
}
