// Greenhouse adapter - Oct 5 2026; moved to Harvest API v3 Oct 21 2026.
//
// Pulls the recruiting picture straight from Greenhouse (Harvest API v3) instead of the weekly
// "all_jobs_status_report" export, in the same shape the dashboard's ATS JSON has used since
// September, so the page and the Monday build keep working unchanged:
//   { job, client, portfolio, department, offices, emp, openings, manager, start, opened,
//     days_open, recruiter, interviewing, update, history }
//
// COMPENSATION NEVER LEAVES THIS MODULE: custom fields whose key or name mentions salary, pay,
// rate, cost or comp are never read, and every free-text note is scrubbed of money language
// sentence by sentence (same rule as the Python ats_parse.scrub).
//
// Harvest v3 (v1/v2 were retired Aug 31 2026):
//   - OAuth 2.0 client-credentials: POST https://auth.greenhouse.io/token with HTTP Basic
//     CLIENT_ID:CLIENT_SECRET and grant_type=client_credentials (+ optional sub=<user id>) ->
//     a short-lived Bearer token, cached here until shortly before expires_in.
//   - Cursor pagination: filters and per_page only on the first request; the Link header's
//     rel="next" URL is followed as-is (cursor must be the only query parameter).
//   - Normalised records: a job carries department_id / office_ids / custom_fields{key:{name,type,value}};
//     openings, hiring managers, job owners (recruiters) and users are separate endpoints; an
//     application carries job_id, prospect and stage_name directly.
//   - Rate limit is a 30-second fixed window; a 429 is retried once after Retry-After.
//
// Env:
//   GH_CLIENT_ID / GH_CLIENT_SECRET   Harvest v3 (OAuth) credentials: Configure > Dev Center >
//                             API Credentials > "Harvest v3 (OAuth)" > Create new API credentials.
//                             Scopes (list/GET only): jobs, openings, applications, job_hiring_managers,
//                             job_owners, users, departments, offices, custom_fields.
//   GH_SUB                    optional Greenhouse user id the token is issued for (`sub`); list
//                             endpoints need a Site Admin, so leave unset to run as the integration
//                             service user unless Greenhouse says otherwise.
//   GREENHOUSE_API_KEY        the old v1 Harvest key. No longer used for requests; kept only so
//                             greenhouseConfigured() can say "v1 key set, v3 credentials missing".
//   GH_FIELD_CLIENT / GH_FIELD_PORTFOLIO / GH_FIELD_START / GH_FIELD_NOTES / GH_FIELD_EMP
//                             job custom-field keys when they differ from the defaults below
//                             (GET /api/recruiting?discover=1 lists what the account actually has)
//   GH_EXCLUDE_JOBS           regex of job names to leave out of the sync. No default since Oct 20 2026
//                             (Mark: "don't forget to include internal roles") - internal/SG&A requisitions
//                             are pulled and kept in the data; the page hides them (hide_open_roles.py).
//   GH_INTERVIEW_STAGES       regex of stage names that count as "interviewing"
//                             (default: interview|screen|onsite|panel|team|final|technical|case)
// Server-only module. Never import from a client component.

export type Req = {
  job: string; client: string; portfolio: string; department: string; offices: string; emp: string;
  openings: number; manager: string; start: string; opened: string; days_open: number; recruiter: string;
  interviewing: number; update: string; history: string[]; gh_job_id: number;
};

const BASE = "https://harvest.greenhouse.io/v3";
const TOKEN_URL = "https://auth.greenhouse.io/token";
const BANNED = /salary|\bpay\b|pay_|rate|cost|\bcomp\b|compensation|budget|bill/i;
const MONEY = /\$|\bsalary\b|\bcomp\b|\bpay\b|\brate[sd]?\b|\bk-\d|\d{2,3}k\b|\bbill(?:ing)?\b|\bcost\b|\bbudget\b/i;

const FIELD = {
  client: (process.env.GH_FIELD_CLIENT ?? "client").toLowerCase(),
  portfolio: (process.env.GH_FIELD_PORTFOLIO ?? "portfolio").toLowerCase(),
  start: (process.env.GH_FIELD_START ?? "anticipated_start_date").toLowerCase(),
  notes: (process.env.GH_FIELD_NOTES ?? "status_notes").toLowerCase(),
  emp: (process.env.GH_FIELD_EMP ?? "employment_type").toLowerCase(),
};
const EXCLUDE = process.env.GH_EXCLUDE_JOBS ? new RegExp(process.env.GH_EXCLUDE_JOBS, "i") : null;
const INTERVIEW = new RegExp(process.env.GH_INTERVIEW_STAGES ?? "interview|screen|onsite|panel|team|final|technical|case", "i");

export function greenhouseConfigured(): boolean { return !!(process.env.GH_CLIENT_ID && process.env.GH_CLIENT_SECRET); }
/** Why /api/recruiting is unavailable, for the 503 body: the v1 key alone is not enough any more. */
export function greenhouseConfigNote(): string {
  if (greenhouseConfigured()) return "";
  return process.env.GREENHOUSE_API_KEY
    ? "GREENHOUSE_API_KEY is a Harvest v1 key; v1 was retired Aug 31 2026. Set GH_CLIENT_ID and GH_CLIENT_SECRET (Harvest v3 OAuth credentials)."
    : "Set GH_CLIENT_ID and GH_CLIENT_SECRET (Harvest v3 OAuth credentials).";
}

function gerr(code: string, detail?: unknown) { return Object.assign(new Error(code), { code, detail }); }

// ---- auth: client-credentials token, cached per server instance ----------------------------

let token: { value: string; expiresAt: number } | null = null;

async function accessToken(force = false): Promise<string> {
  if (!greenhouseConfigured()) throw gerr("greenhouse_not_configured", greenhouseConfigNote());
  if (!force && token && Date.now() < token.expiresAt) return token.value;
  const body = new URLSearchParams({ grant_type: "client_credentials" });
  if (process.env.GH_SUB) body.set("sub", process.env.GH_SUB);
  const r = await fetch(TOKEN_URL, {
    method: "POST",
    headers: {
      authorization: "Basic " + Buffer.from(`${process.env.GH_CLIENT_ID}:${process.env.GH_CLIENT_SECRET}`).toString("base64"),
      "content-type": "application/x-www-form-urlencoded",
      accept: "application/json",
    },
    body: body.toString(),
    cache: "no-store",
  });
  const text = await r.text();
  let j: { access_token?: string; expires_in?: number; error?: string; error_description?: string } = {};
  try { j = text ? JSON.parse(text) : {}; } catch { /* non-JSON error page */ }
  if (r.status === 401 || r.status === 403 || j.error === "invalid_client") {
    throw gerr("greenhouse_auth_failed", { status: r.status, step: "token", error: j.error ?? null, description: j.error_description ?? text.slice(0, 300) });
  }
  if (!r.ok || !j.access_token) throw gerr("greenhouse_request_failed", { status: r.status, step: "token", body: text.slice(0, 500) });
  // refresh a minute early (or halfway through a very short token) so a long pull never straddles the expiry
  const ttl = Math.max(30, Number(j.expires_in ?? 3600));
  token = { value: j.access_token, expiresAt: Date.now() + Math.max(ttl / 2, ttl - 60) * 1000 };
  return token.value;
}

// ---- transport ----------------------------------------------------------------------------

async function gh<T>(path: string, attempt = 0): Promise<{ data: T; next: string | null }> {
  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const r = await fetch(url, {
    headers: { authorization: `Bearer ${await accessToken()}`, accept: "application/json" },
    cache: "no-store",
  });
  if (r.status === 401 && attempt === 0) {           // token revoked or expired early: mint one and retry once
    await accessToken(true);
    return gh<T>(path, attempt + 1);
  }
  if (r.status === 401 || r.status === 403) throw gerr("greenhouse_auth_failed", { status: r.status, url: url.split("?")[0] });
  if (r.status === 429) {
    const wait = Math.min(30, Math.max(1, Number(r.headers.get("retry-after") ?? 5)));
    if (attempt === 0) { await new Promise((res) => setTimeout(res, wait * 1000)); return gh<T>(path, attempt + 1); }
    throw gerr("greenhouse_rate_limited", { retryAfter: wait });
  }
  if (r.status === 422) throw gerr("greenhouse_request_failed", { status: 422, url: url.split("?")[0], body: (await r.text()).slice(0, 500), hint: "v3 rejects filters alongside cursor" });
  if (!r.ok) throw gerr("greenhouse_request_failed", { status: r.status, url: url.split("?")[0], body: (await r.text()).slice(0, 500) });
  const link = r.headers.get("link") ?? "";
  const m = /<([^>]+)>;\s*rel="next"/.exec(link);
  return { data: (await r.json()) as T, next: m ? m[1] : null };
}

/** Every page of a list endpoint. Filters/per_page go on `path`; later pages follow the Link header verbatim. */
async function all<T>(path: string, cap = 20): Promise<T[]> {
  const out: T[] = [];
  let next: string | null = path, n = 0;
  while (next && n++ < cap) {
    const page: { data: T[]; next: string | null } = await gh<T[]>(next);
    out.push(...(Array.isArray(page.data) ? page.data : []));
    next = page.next;
  }
  return out;
}

/** v3 `ids`-style filters take at most 50 values: fetch in chunks and concatenate. */
async function byIds<T>(path: string, param: string, ids: number[], cap = 20): Promise<T[]> {
  const uniq = Array.from(new Set(ids.filter((x) => Number.isFinite(x))));
  const out: T[] = [];
  for (let i = 0; i < uniq.length; i += 50) {
    const sep = path.includes("?") ? "&" : "?";
    out.push(...await all<T>(`${path}${sep}${param}=${uniq.slice(i, i + 50).join(",")}`, cap));
  }
  return out;
}

export function scrub(text: string): string {
  return (text || "").split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter((s) => s && !MONEY.test(s)).join(" ");
}

// ---- v3 record shapes (only the fields read here) -----------------------------------------

type GHCustomField = { name?: string; type?: string; value?: unknown };
type GHJob = {
  id: number; name: string; status: "open" | "draft" | "closed"; created_at: string; opened_at: string | null; closed_at: string | null;
  department_id: number | null; office_ids: number[] | null;
  custom_fields: Record<string, GHCustomField> | null;
};
type GHOpening = { id: number; job_id: number; open: boolean; target_start_on?: string | null };
type GHApp = { id: number; status: string; job_id: number | null; prospect: boolean; stage_id: number | null; stage_name: string | null };
type GHHiringManager = { id: number; job_id: number; user_id: number };
type GHJobOwner = { id: number; job_id: number; user_id: number; type: "sourcer" | "recruiter" | "coordinator"; responsible: boolean };
type GHUser = { id: number; name: string | null; first_name: string | null; last_name: string | null; deactivated: boolean };
type GHNamed = { id: number; name: string };

function cf(job: GHJob, key: string): string {
  // custom_fields is keyed by the field's immutable key; also accept a match on the display name
  const fields = job.custom_fields ?? {};
  const direct = fields[key];
  if (direct && direct.value !== undefined && direct.value !== null) return fmt(direct.value);
  for (const k of Object.keys(fields)) {
    if (k.toLowerCase() === key || (fields[k]?.name ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "_") === key) return fmt(fields[k]?.value);
  }
  return "";
}
function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.name === "string") return o.name;
    if (typeof o.value === "string") return o.value;
    if (Array.isArray(v)) return v.map(fmt).filter(Boolean).join(", ");
    return "";
  }
  return String(v);
}
function usDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[2]}/${m[3]}/${m[1]}` : iso || "";
}
function userName(u: GHUser | undefined): string {
  if (!u) return "";
  return (u.name ?? [u.first_name, u.last_name].filter(Boolean).join(" ")).trim();
}

/** Open requisitions in the dashboard's ATS shape. */
export async function pullRequisitions(): Promise<{ asOf: string; reqs: Req[] }> {
  const jobs = (await all<GHJob>("/jobs?status=open&per_page=500")).filter((j) => !(EXCLUDE && EXCLUDE.test(j.name)));
  const jobIds = jobs.map((j) => j.id);

  // the pieces v1 inlined on the job are their own endpoints in v3
  const [openings, hms, owners, apps, departments, offices] = await Promise.all([
    byIds<GHOpening>("/openings?open=true&per_page=500", "job_ids", jobIds),
    byIds<GHHiringManager>("/job_hiring_managers?per_page=500", "job_ids", jobIds),
    byIds<GHJobOwner>("/job_owners?type=recruiter&per_page=500", "job_ids", jobIds),
    all<GHApp>("/applications?status=active&prospect=false&per_page=500", 40),
    all<GHNamed>("/departments?per_page=500", 4),
    all<GHNamed>("/offices?per_page=500", 4),
  ]);
  const userIds = [...hms.map((h) => h.user_id), ...owners.map((o) => o.user_id)];
  const users = new Map((await byIds<GHUser>("/users?per_page=500", "ids", userIds)).map((u) => [u.id, u]));
  const deptName = new Map(departments.map((d) => [d.id, d.name]));
  const officeName = new Map(offices.map((o) => [o.id, o.name]));

  const openCount = new Map<number, number>();
  for (const o of openings) if (o.open) openCount.set(o.job_id, (openCount.get(o.job_id) ?? 0) + 1);
  const managers = new Map<number, string[]>();
  for (const h of hms) { const n = userName(users.get(h.user_id)); if (n) managers.set(h.job_id, [...(managers.get(h.job_id) ?? []), n]); }
  const recruiters = new Map<number, GHJobOwner[]>();
  for (const o of owners) recruiters.set(o.job_id, [...(recruiters.get(o.job_id) ?? []), o]);
  const interviewing = new Map<number, number>();
  for (const a of apps) {
    if (a.prospect || a.job_id === null || !a.stage_name || !INTERVIEW.test(a.stage_name)) continue;
    interviewing.set(a.job_id, (interviewing.get(a.job_id) ?? 0) + 1);
  }

  const now = Date.now();
  const reqs: Req[] = jobs.map((j) => {
    const opened = (j.opened_at ?? j.created_at ?? "").slice(0, 10);
    const notesRaw = cf(j, FIELD.notes);
    const history = notesRaw.split(/\r?\n/).map((l) => scrub(l.trim())).filter(Boolean);
    const rs = recruiters.get(j.id) ?? [];
    const recruiter = userName(users.get((rs.find((r) => r.responsible) ?? rs[0])?.user_id ?? -1));
    return {
      job: j.name.trim(),
      client: cf(j, FIELD.client), portfolio: cf(j, FIELD.portfolio),
      department: j.department_id ? (deptName.get(j.department_id) ?? "") : "",
      offices: (j.office_ids ?? []).map((id) => officeName.get(id) ?? "").filter(Boolean).join(", "),
      emp: cf(j, FIELD.emp),
      openings: openCount.get(j.id) ?? 0,
      manager: (managers.get(j.id) ?? []).join(", "),
      start: usDate(cf(j, FIELD.start)),
      opened,
      days_open: opened ? Math.max(0, Math.floor((now - Date.parse(opened)) / 86400000)) : 0,
      recruiter,
      interviewing: interviewing.get(j.id) ?? 0,
      update: history[0] ?? "",
      history,
      gh_job_id: j.id,
    };
  });
  reqs.sort((a, b) => b.days_open - a.days_open);
  return { asOf: new Date().toISOString().slice(0, 10), reqs };
}

/** What the account actually calls things - for mapping the GH_FIELD_* env on first connection. */
export async function discover(): Promise<{ customFields: Array<{ key: string; name: string; type: string }>; stages: string[]; openJobs: number }> {
  const jobs = await all<GHJob>("/jobs?status=open&per_page=50", 1);
  const seen = new Map<string, { key: string; name: string; type: string }>();
  for (const j of jobs) {
    for (const [k, v] of Object.entries(j.custom_fields ?? {})) {
      if (BANNED.test(k) || BANNED.test(v?.name ?? "")) continue;        // never even list pay fields
      if (!seen.has(k)) seen.set(k, { key: k, name: v?.name ?? k, type: v?.type ?? typeof v?.value });
    }
  }
  const apps = await all<GHApp>("/applications?status=active&prospect=false&per_page=500", 4);
  const stages = Array.from(new Set(apps.map((a) => a.stage_name ?? "").filter(Boolean))).sort();
  return { customFields: Array.from(seen.values()), stages, openJobs: jobs.length };
}
