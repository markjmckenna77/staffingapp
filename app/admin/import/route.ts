// GET /admin/import - a one-page tool for admins to load the exported claude.ai store
// (seed JSON) into Postgres via POST /api/db/import. Plain HTML; no React needed.
import { actor, isAdmin } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET() {
  const who = await actor();
  if (!isAdmin(who)) return new Response("Admins only.", { status: 403 });
  const html = `<!doctype html><meta charset="utf-8"><title>Import shared store</title>
<style>body{font:14px/1.5 system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 16px;color:#1f2328}
pre{background:#f6f8fa;padding:10px;border-radius:6px;white-space:pre-wrap}button{font:inherit;padding:6px 14px}</style>
<h1>Import the shared meeting-log store</h1>
<p>Pick the <code>claude-artifact-export-*.json</code> file. Documents with the same id are replaced; nothing is deleted. Safe to run more than once.</p>
<input type="file" id="f" accept="application/json"> <button id="go" disabled>Import</button>
<pre id="out">Waiting for a file…</pre>
<script>
var f=document.getElementById("f"),go=document.getElementById("go"),out=document.getElementById("out"),data=null;
f.addEventListener("change",function(){var r=new FileReader();r.onload=function(){try{data=JSON.parse(r.result);
var c=data.collections||{};out.textContent=Object.keys(c).map(function(k){return k+": "+Object.keys(c[k]).length+" documents"}).join("\\n")||"No collections in that file.";go.disabled=!Object.keys(c).length}
catch(e){out.textContent="Not valid JSON: "+e.message;go.disabled=true}};r.readAsText(f.files[0])});
go.addEventListener("click",function(){go.disabled=true;out.textContent="Importing…";
fetch("/api/db/import",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(data)})
.then(function(r){return r.json().then(function(j){return [r.status,j]})}).then(function(x){out.textContent=(x[0]===200?"Done. ":"Failed ("+x[0]+"). ")+JSON.stringify(x[1],null,1);go.disabled=false})
.catch(function(e){out.textContent="Request failed: "+e;go.disabled=false})});
</script>`;
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "private, no-store" } });
}
