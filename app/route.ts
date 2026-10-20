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
  /* Meeting Notes (Oct 20 2026): the last two Staffing Weekly meetings from Granola - public/meetings.js. */
  /* Ask bar (Oct 16 2026): natural-language questions over the staffing data - public/ask.js. */
  .sa-ask{display:flex;flex:1;max-width:560px;gap:6px;margin-left:8px}
  .sa-ask input{flex:1;min-width:0;font:inherit;font-size:13px;color:#e6edf3;background:#0b0f13;
    border:1px solid #3a424c;border-radius:6px;padding:5px 10px;outline:none}
  .sa-ask input:focus{border-color:#9ecbff}
  .sa-ask input::placeholder{color:#7d8590}
  .sa-ask button{font:inherit;color:#0b0f13;background:#9ecbff;border:0;border-radius:6px;padding:4px 12px;cursor:pointer;font-weight:600}
  .sa-ask.sa-busy button{opacity:.5;cursor:progress}
  .sa-ask-panel{position:fixed;top:var(--sa-bar-h,37px);left:50%;transform:translateX(-50%);width:min(960px,calc(100vw - 32px));
    max-height:calc(100vh - var(--sa-bar-h,37px) - 24px);overflow:auto;z-index:9998;background:#101418;color:#c9d1d9;
    border:1px solid #2a3139;border-top:0;border-radius:0 0 10px 10px;box-shadow:0 12px 32px rgba(0,0,0,.35);
    font:13px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  .sa-ask-panel[hidden]{display:none}
  .sa-ask-top{position:sticky;top:0;display:flex;gap:12px;align-items:center;padding:8px 16px;background:#101418;border-bottom:1px solid #2a3139}
  .sa-ask-top .sa-sp{flex:1}
  .sa-ask-log{padding:4px 16px 16px}
  .sa-ask-item{padding:12px 0;border-bottom:1px solid #2a3139}
  .sa-ask-item:last-child{border-bottom:0}
  .sa-ask-q{font-weight:600;color:#fff;margin-bottom:6px}
  .sa-ask-a p{margin:0 0 6px}
  .sa-ask-a ul{margin:0 0 6px;padding-left:20px}
  .sa-ask-muted{color:#7d8590}
  .sa-ask-err{color:#ff9492}
  .sa-ask-wait{animation:saPulse 1.2s ease-in-out infinite}
  @keyframes saPulse{50%{opacity:.4}}
  .sa-ask-link,.sa-ask-chip{font:inherit;cursor:pointer;background:none;color:#9ecbff;border:0;padding:0}
  .sa-ask-link:hover{text-decoration:underline}
  .sa-ask-examples{display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:10px 0}
  .sa-ask-chip{border:1px solid #3a424c;border-radius:14px;padding:3px 12px;color:#c9d1d9;text-align:left}
  .sa-ask-chip:hover{border-color:#9ecbff;color:#fff}
  .sa-ask-table{margin:10px 0 4px;border:1px solid #2a3139;border-radius:8px;overflow:hidden}
  .sa-ask-thead{display:flex;gap:10px;align-items:baseline;padding:6px 10px;background:#161b22}
  .sa-ask-thead b{color:#fff}
  .sa-ask-thead .sa-ask-link{margin-left:auto}
  .sa-ask-scroll{overflow:auto;max-height:360px}
  .sa-ask-table table{border-collapse:collapse;width:100%;font-size:12px}
  .sa-ask-table th{position:sticky;top:0;background:#161b22;color:#9da7b3;font-weight:600;text-align:left;padding:5px 10px;white-space:nowrap}
  .sa-ask-table td{padding:4px 10px;border-top:1px solid #21262d;white-space:nowrap}
  .sa-ask-table td.n{text-align:right;font-variant-numeric:tabular-nums}
  .sa-ask-sql{padding:4px 10px 8px;color:#7d8590}
  .sa-ask-sql summary{cursor:pointer;font-size:12px}
  .sa-ask-sql pre{white-space:pre-wrap;font-size:11px;margin:6px 0 0;color:#9da7b3}
  @media (max-width:700px){.sa-bar{flex-wrap:wrap;row-gap:6px}.sa-ask{order:9;flex-basis:100%;max-width:none;margin-left:0}
    .sa-bar>a[href="/live"],.sa-bar>span:not(.sa-sp),.sa-ask-top .sa-ask-muted{display:none}}
</style>
<div class="sa-bar">
  <b>Cleartelligence Staffing</b>
  <a href="/live">Live data (beta)</a>
  <form class="sa-ask" id="sa-ask" autocomplete="off" role="search">
    <input id="sa-ask-q" type="search" maxlength="1000" placeholder="Ask about staffing - e.g. who has capacity in November?" aria-label="Ask a question about staffing">
    <button type="submit">Ask</button>
  </form>
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
<div class="sa-ask-panel" id="sa-ask-panel" hidden>
  <div class="sa-ask-top"><b>Ask</b><span class="sa-ask-muted">Live from Snowflake - read-only - check anything you'll act on</span><span class="sa-sp"></span>
    <button type="button" class="sa-ask-link" id="sa-ask-new">New question</button><button type="button" class="sa-ask-link" id="sa-ask-close">Close</button></div>
  <div class="sa-ask-log" id="sa-ask-log"></div>
</div>
<script src="/sa-shim.js"></script>
<script src="/ask.js" defer></script>
<script src="/meetings.js" defer></script>`;

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
