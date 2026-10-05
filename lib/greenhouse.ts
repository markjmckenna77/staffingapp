// Greenhouse adapter - Oct 5 2026.
//
// Pulls the recruiting picture straight from Greenhouse (Harvest API) instead of the weekly
// "all_jobs_status_report" export, in the same shape the dashboard's ATS JSON has used since
// September, so the page and the Monday build keep working unchanged:
//   { job, client, portfolio, department, offices, emp, openings, manager, start, opened,
//     days_open, recruiter, interviewing, update, history }
//
// COMPENSATION NEVER LEAVES THIS MODULE: custom fields whose key or name mentions salary, pay,
// rate, cost or comp are never read, and every free-text note is scrubbed of money language
// sentence by sentence (same rule as the Python ats_parse.scrub).
//
// Env:
//   GREENHOUSE_API_KEY        Harvest API key (Configure > Dev Center > API Credential Management:
//                             type Harvest; permissions Jobs, Applications, Candidates, Users, Job
//                             Stages - GET only). Basic auth, key as the username.
//   GH_ON_BEHALF_OF           optional Greenhouse user id for the On-Behalf-Of header (not needed for GETs)
//   GH_FIELD_CLIENT / GH_FIELD_PORTFOLIO / GH_FIELD_START / GH_FIELD_NOTES / GH_FIELD_EMP
//                             job custom-field keys when they differ from the defaults below
//                             (GET /api/recruiting?discover=1 lists what the account actually has)
//   GH_EXCLUDE_JOBS           regex of job names to leave out (default ^internal\b - Mark, Oct 5 2026:
//                             "exclude any role that starts with Internal")
//   GH_INTERVIEW_STAGES       regex of stage names that count as "interviewing"
//                             (default: interview|screen|onsite|panel|team|final|technical|case)
// Server-only module. Never import from a client component.

export type Req = {
  job: string; client: string; portfolio: string; department: string; offices: string; emp: string;
  openings: number; manager: string; start: string; opened: string; days_open: number; recruiter: string;
  interviewing: number; update: string; history: string[]; gh_job_id: number;
};

const BASE = "https://harvest.greenhouse.io/v1";
const BANNED = /salary|\bpay\b|pay_|rate|cost|\bcomp\b|compensation|budget|bill/i;
const MONEY = /\$|\bsalary\b|\bcomp\b|\bpay\b|\brate[sd]?\b|\bk-\d|\d{2,3}k\b|\bbill(?:ing)?\b|\bcost\b|\bbudget\b/i;

const FIELD = {
  client: (process.env.GH_FIELD_CLIENT ?? "client").toLowerCase(),
  portfolio: (process.env.GH_FIELD_PORTFOLIO ?? "portfolio").toLowerCase(),
  start: (process.env.GH_FIELD_START ?? "anticipated_start_date").toLowerCase(),
  notes: (process.env.GH_FIELD_NOTES ?? "status_notes").toLowerCase(),
  emp: (process.env.GH_FIELD_EMP ?? "employment_type").toLowerCase(),
};
const EXCLUDE = new RegExp(process.env.GH_EXCLUDE_JOBS ?? "^\\s*internal\\b", "i");
const INTERVIEW = new RegExp(process.env.GH_INTERVIEW_STAGES ?? "interview|screen|onsite|panel|team|final|technical|case", "i");

export function greenhouseConfigured(): boolean { return !!process.env.GREENHOUSE_API_KEY; }

function gerr(code: string, detail?: unknown) { return Object.assign(new Error(code), { code, detail }); }

async function gh<T>(path: string): Promise<{ data: T; next: string | null }> {
  if (!greenhouseConfigured()) throw gerr("greenhouse_not_configured");
  const url = path.startsWith("http") ? path : `${BASE}${path}`;
  const headers: Record<string, string> = {
    authorization: "Basic " + Buffer.from(`${process.env.GREENHOUSE_API_KEY}:`).toString("base64"),
    accept: "application/json",
  };
  if (process.env.GH_ON_BEHALF_OF) headers["On-Behalf-Of"] = process.env.GH_ON_BEHALF_OF;
  const r = await fetch(url, { headers, cache: "no-store" });
  if (r.status === 401 || r.status === 403) throw gerr("greenhouse_auth_failed", { status: r.status, url: url.split("?")[0] });
  if (r.status === 429) throw gerr("greenhouse_rate_limited");
  if (!r.ok) throw gerr("greenhouse_request_failed", { status: r.status, url: url.split("?")[0], body: (await r.text()).slice(0, 500) });
  const link = r.headers.get("link") ?? "";
  const m = /<([^>]+)>;\s*rel="next"/.exec(link);
  return { data: (await r.json()) as T, next: m ? m[1] : null };
}

async function all<T>(path: string, cap = 20): Promise<T[]> {
  const out: T[] = [];
  let next: string | null = path, n = 0;
  while (next && n++ < cap) {
    const page: { data: T[]; next: string | null } = await gh<T[]>(next);
    out.push(...page.data);
    next = page.next;
  }
  return out;
}

export function scrub(text: string): string {
  return (text || "").split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter((s) => s && !MONEY.test(s)).join(" ");
}

type GHJob = {
  id: number; name: string; status: string; created_at: string; opened_at: string | null; closed_at: string | null;
  departments: Array<{ name: string } | null>; offices: Array<{ name: string } | null>;
  openings: Array<{ status: string }>;
  hiring_team: { hiring_managers?: Array<{ name: string }>; recruiters?: Array<{ name: string; responsible?: boolean }> };
  custom_fields: Record<string, unknown>; keyed_custom_fields?: Record<string, { name: string; type: string; value: unknown }>;
};
type GHApp = { id: number; status: string; jobs: Array<{ id: number }>; current_stage: { id: number; name: string } | null; prospect: boolean };

function cf(job: GHJob, key: string): string {
  // custom_fields is keyed by the field's immutable key; also accept a match on the display name
  const direct = job.custom_fields?.[key];
  if (direct !== undefined && direct !== null) return fmt(direct);
  const kc = job.keyed_custom_fields ?? {};
  for (const k of Object.keys(kc)) {
    if (k.toLowerCase() === key || (kc[k]?.name ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "_") === key) return fmt(kc[k].value);
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

/** Open requisitions in the dashboard's ATS shape. */
export async function pullRequisitions(): Promise<{ asOf: string; reqs: Req[] }> {
  const jobs = (await all<GHJob>("/jobs?status=open&per_page=500")).filter((j) => !EXCLUDE.test(j.name));
  const apps = await all<GHApp>("/applications?status=active&per_page=500", 40);
  const interviewing = new Map<number, number>();
  for (const a of apps) {
    if (a.prospect || !a.current_stage || !INTERVIEW.test(a.current_stage.name)) continue;
    for (const j of a.jobs ?? []) interviewing.set(j.id, (interviewing.get(j.id) ?? 0) + 1);
  }
  const now = Date.now();
  const reqs: Req[] = jobs.map((j) => {
    const opened = (j.opened_at ?? j.created_at ?? "").slice(0, 10);
    const notesRaw = cf(j, FIELD.notes);
    const history = notesRaw.split(/\r?\n/).map((l) => scrub(l.trim())).filter(Boolean);
    const recruiters = j.hiring_team?.recruiters ?? [];
    const recruiter = (recruiters.find((r) => r.responsible) ?? recruiters[0])?.name ?? "";
    return {
      job: j.name.trim(),
      client: cf(j, FIELD.client), portfolio: cf(j, FIELD.portfolio),
      department: (j.departments ?? []).filter(Boolean).map((d) => d!.name).join(", "),
      offices: (j.offices ?? []).filter(Boolean).map((o) => o!.name).join(", "),
      emp: cf(j, FIELD.emp),
      openings: (j.openings ?? []).filter((o) => o.status === "open").length,
      manager: (j.hiring_team?.hiring_managers ?? []).map((m) => m.name).join(", "),
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
    for (const [k, v] of Object.entries(j.keyed_custom_fields ?? {})) {
      if (BANNED.test(k) || BANNED.test(v?.name ?? "")) continue;        // never even list pay fields
      if (!seen.has(k)) seen.set(k, { key: k, name: v?.name ?? k, type: v?.type ?? typeof v?.value });
    }
  }
  const apps = await all<GHApp>("/applications?status=active&per_page=500", 4);
  const stages = Array.from(new Set(apps.map((a) => a.current_stage?.name ?? "").filter(Boolean))).sort();
  return { customFields: Array.from(seen.values()), stages, openJobs: jobs.length };
}
