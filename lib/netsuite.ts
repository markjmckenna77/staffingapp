// NetSuite adapter - Oct 5 2026.
//
// NetSuite is the system of record for staffing. Every line on the dashboard traces back to a
// NetSuite Resource Allocation (RAW_NETSUITE.RESOURCEALLOCATION -> STG_BI.STG_ALLOCATED_TIME ->
// CONS_BI.CONS_ALLOCATED_TIME / CONS_CONSULTANT_PROJECT_DETAIL / CONS_WEEKLY_AVAILABILITY), and an
// "open role" is an allocation whose resource is a generic resource (_Data Mgmt, _AI/ML, ...).
// So "make the allocation in all of our systems" means: create the employee's allocation in
// NetSuite (and, when asked, retire the generic one it fills). Fivetran copies the change into
// Snowflake on its next sync and the dbt build rebuilds the CONS_* tables - nothing is written
// to Snowflake directly, or dbt would overwrite it on the next run.
//
// Auth: Token-Based Authentication (OAuth 1.0a, HMAC-SHA256) against SuiteTalk REST.
//   NS_ACCOUNT_ID        e.g. 1234567 or 1234567_SB1 (as shown in Setup > Company Information)
//   NS_CONSUMER_KEY / NS_CONSUMER_SECRET     from the Integration record
//   NS_TOKEN_ID / NS_TOKEN_SECRET            from the Access Token (integration user + role)
//   NS_WRITE_ENABLED     "true" to create/update records; anything else = dry run (lookups only)
//   NS_ALLOCATION_ROLE_FIELD   default custevent_ct_allocation_role (the role title on an allocation)
//   NS_REQUESTED_BY_ID   optional employee internal id stamped as "requested by" on new allocations
// The role needs: Lists > Resource Allocations (Full), Employees (View), Projects (View);
// Setup > REST Web Services, SuiteAnalytics Workbook (for SuiteQL), Log in using Access Tokens.
import { createHmac, randomBytes } from "node:crypto";

export type NsAllocationInput = {
  consultant: string;        // employee display name as the dashboard shows it (NetSuite entityid)
  project: string;           // NetSuite project name (job.companyname); "Client / Project" is tolerated
  projectId?: number;        // when the caller already knows it
  roleTitle?: string;        // the open role's title, e.g. "US Sr. Databricks Data Engineer"
  hours: number;             // per week
  weeks: string[];           // Monday ISO dates the allocation covers
  note?: string;
  fillOpenRole?: boolean;    // retire the generic allocation this fills (default true when roleTitle given)
  requestedBy?: string;      // dashboard author, recorded in the notes
};

export type NsAllocationResult = {
  dryRun: boolean;
  employeeId: number;
  projectId: number;
  projectName: string;
  startDate: string;
  endDate: string;
  percentOfTime: number;
  allocationId?: number;
  url?: string;
  openRole?: { allocationId: number; action: "ended" | "zeroed" | "none"; title: string } | null;
};

const F = {
  roleField: process.env.NS_ALLOCATION_ROLE_FIELD ?? "custevent_ct_allocation_role",
  hardTypeId: process.env.NS_ALLOCATION_TYPE_HARD_ID ?? "1",
};

export function netsuiteConfigured(): boolean {
  return !!(process.env.NS_ACCOUNT_ID && process.env.NS_CONSUMER_KEY && process.env.NS_CONSUMER_SECRET
    && process.env.NS_TOKEN_ID && process.env.NS_TOKEN_SECRET);
}
export function netsuiteDryRun(): boolean {
  return process.env.NS_WRITE_ENABLED !== "true";
}

function nerr(code: string, detail?: unknown) {
  return Object.assign(new Error(code), { code, detail });
}

function accountHost(): string {
  // Realm keeps the account id as NetSuite shows it (1234567_SB1); the host wants 1234567-sb1.
  return process.env.NS_ACCOUNT_ID!.toLowerCase().replace(/_/g, "-");
}
function base(): string { return `https://${accountHost()}.suitetalk.api.netsuite.com`; }

const enc = (s: string) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());

function oauthHeader(method: string, url: string): string {
  const u = new URL(url);
  const oauth: Record<string, string> = {
    oauth_consumer_key: process.env.NS_CONSUMER_KEY!,
    oauth_token: process.env.NS_TOKEN_ID!,
    oauth_nonce: randomBytes(16).toString("hex"),
    oauth_timestamp: Math.floor(Date.now() / 1000).toString(),
    oauth_signature_method: "HMAC-SHA256",
    oauth_version: "1.0",
  };
  const params: [string, string][] = Object.entries(oauth);
  u.searchParams.forEach((v, k) => params.push([k, v]));
  const normalized = params.map(([k, v]) => [enc(k), enc(v)] as [string, string])
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0))
    .map(([k, v]) => `${k}=${v}`).join("&");
  const baseString = [method.toUpperCase(), enc(`${u.origin}${u.pathname}`), enc(normalized)].join("&");
  const key = `${enc(process.env.NS_CONSUMER_SECRET!)}&${enc(process.env.NS_TOKEN_SECRET!)}`;
  const sig = createHmac("sha256", key).update(baseString).digest("base64");
  const parts = [`realm="${process.env.NS_ACCOUNT_ID}"`]
    .concat(Object.entries(oauth).map(([k, v]) => `${k}="${enc(v)}"`))
    .concat([`oauth_signature="${enc(sig)}"`]);
  return "OAuth " + parts.join(", ");
}

async function ns<T>(method: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}): Promise<{ data: T; headers: Headers }> {
  if (!netsuiteConfigured()) throw nerr("netsuite_not_configured");
  const url = `${base()}${path}`;
  const r = await fetch(url, {
    method,
    headers: {
      authorization: oauthHeader(method, url),
      "content-type": "application/json",
      accept: "application/json",
      ...extraHeaders,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (r.status === 204) return { data: undefined as T, headers: r.headers };
  const text = await r.text();
  let j: unknown = {};
  try { j = text ? JSON.parse(text) : {}; } catch { j = { raw: text.slice(0, 2000) }; }
  if (r.status === 401 || r.status === 403) throw nerr("netsuite_auth_failed", j);
  if (!r.ok) throw nerr("netsuite_request_failed", { status: r.status, body: j });
  return { data: j as T, headers: r.headers };
}

type SuiteQL = { items: Array<Record<string, string | number | null>>; hasMore?: boolean };
async function suiteql(q: string): Promise<SuiteQL["items"]> {
  const { data } = await ns<SuiteQL>("POST", "/services/rest/query/v1/suiteql?limit=50", { q }, { Prefer: "transient" });
  return data.items ?? [];
}
const esc = (s: string) => s.replace(/'/g, "''");

// ---- lookups ----------------------------------------------------------------------------

export async function findEmployee(name: string): Promise<{ id: number; name: string }> {
  const n = name.replace(/\s+/g, " ").trim();
  let rows = await suiteql(`SELECT id, entityid FROM employee WHERE isinactive = 'F' AND UPPER(entityid) = UPPER('${esc(n)}')`);
  if (rows.length === 0) {
    // the dashboard sometimes shortens first names (Alex Markow for Alexander Markow): try last name + first initial
    const parts = n.split(" ");
    if (parts.length >= 2) {
      const last = parts[parts.length - 1], first = parts[0];
      rows = await suiteql(`SELECT id, entityid FROM employee WHERE isinactive = 'F' AND UPPER(lastname) = UPPER('${esc(last)}') AND UPPER(firstname) LIKE UPPER('${esc(first.slice(0, 3))}%')`);
    }
  }
  if (rows.length !== 1) throw nerr(rows.length ? "netsuite_employee_ambiguous" : "netsuite_employee_not_found", { name: n, matches: rows.map((r) => r.entityid) });
  return { id: Number(rows[0].id), name: String(rows[0].entityid) };
}

export async function findProject(label: string, id?: number): Promise<{ id: number; name: string }> {
  if (id) {
    const rows = await suiteql(`SELECT id, companyname FROM job WHERE id = ${Math.floor(id)}`);
    if (rows.length === 1) return { id: Number(rows[0].id), name: String(rows[0].companyname) };
  }
  // The dashboard labels projects "Client / Project" in some places; try the project part, then the whole label.
  const candidates = Array.from(new Set([label.split(" / ").pop()!.trim(), label.trim()].filter(Boolean)));
  for (const c of candidates) {
    const rows = await suiteql(`SELECT id, companyname FROM job WHERE isinactive = 'F' AND UPPER(companyname) = UPPER('${esc(c)}')`);
    if (rows.length === 1) return { id: Number(rows[0].id), name: String(rows[0].companyname) };
    if (rows.length > 1) throw nerr("netsuite_project_ambiguous", { label: c, matches: rows.map((r) => r.companyname) });
  }
  // last resort: a unique active project whose name starts with the label (trailing year/suffix differences)
  const like = await suiteql(`SELECT id, companyname FROM job WHERE isinactive = 'F' AND UPPER(companyname) LIKE UPPER('${esc(candidates[0])}%')`);
  if (like.length === 1) return { id: Number(like[0].id), name: String(like[0].companyname) };
  throw nerr("netsuite_project_not_found", { label, near: like.slice(0, 5).map((r) => r.companyname) });
}

type GenericAlloc = { id: number; title: string; startdate: string; enddate: string; numberhours: number; percentoftime: number; allocationunit: string; notes: string };

/** The generic-resource allocation (the open role) on a project, matched by role title. */
export async function findOpenRoleAllocation(projectId: number, roleTitle: string): Promise<GenericAlloc | null> {
  const rows = await suiteql(
    `SELECT ra.id, ra.${F.roleField} AS title, ra.startdate, ra.enddate, ra.numberhours, ra.percentoftime, ra.allocationunit, ra.notes ` +
    `FROM resourceallocation ra JOIN genericresource g ON g.id = ra.allocationresource ` +
    `WHERE ra.project = ${projectId} AND ra.enddate >= CURRENT_DATE ORDER BY ra.startdate`);
  const norm = (s: unknown) => String(s ?? "").toLowerCase().replace(/\s+/g, " ").trim();
  const want = norm(roleTitle);
  const hit = rows.find((r) => norm(r.title) === want) ?? rows.find((r) => want && (norm(r.title).includes(want) || want.includes(norm(r.title))));
  if (!hit) return null;
  return {
    id: Number(hit.id), title: String(hit.title ?? ""), startdate: String(hit.startdate ?? ""), enddate: String(hit.enddate ?? ""),
    numberhours: Number(hit.numberhours ?? 0), percentoftime: Number(hit.percentoftime ?? 0),
    allocationunit: String(hit.allocationunit ?? ""), notes: String(hit.notes ?? ""),
  };
}

// ---- dates ------------------------------------------------------------------------------

function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
/** NetSuite SuiteQL returns dates as M/D/YYYY in most accounts; normalise to ISO. */
function isoDate(s: string): string {
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})/.exec(s);
  if (m) return `${m[3]}-${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")}`;
  return s.slice(0, 10);
}
function today(): string { return new Date().toISOString().slice(0, 10); }

// ---- the write --------------------------------------------------------------------------

/**
 * Creates the employee's Resource Allocation for the weeks given (Monday of the first week through
 * Friday of the last), as a Hard allocation in percent of time (hours/week over 40). When
 * fillOpenRole is set and the project carries a generic allocation with that role title, the
 * generic one is ended the day before the new allocation starts - or zeroed when it has already
 * started - with a note saying who filled it from the dashboard.
 */
export async function createAllocation(a: NsAllocationInput): Promise<NsAllocationResult> {
  if (!netsuiteConfigured()) throw nerr("netsuite_not_configured");
  if (!a.weeks?.length) throw nerr("bad_body", "allocation has no weeks");
  if (!(a.hours > 0)) throw nerr("bad_body", "hours must be positive");
  const dryRun = netsuiteDryRun();
  const weeks = a.weeks.slice().sort();
  const startDate = weeks[0], endDate = addDays(weeks[weeks.length - 1], 4);
  const percentOfTime = Math.min(100, Math.round((a.hours / 40) * 1000) / 10);

  const emp = await findEmployee(a.consultant);
  const proj = await findProject(a.project, a.projectId);
  const wantFill = a.fillOpenRole ?? !!a.roleTitle;
  const generic = wantFill && a.roleTitle ? await findOpenRoleAllocation(proj.id, a.roleTitle) : null;

  const stamp = `${today()} staffing dashboard${a.requestedBy ? ` (${a.requestedBy})` : ""}`;
  const notes = [`${stamp}: ${a.hours} hrs/wk ${startDate} to ${endDate}`, a.note?.trim()].filter(Boolean).join(" - ").slice(0, 3900);

  const result: NsAllocationResult = {
    dryRun, employeeId: emp.id, projectId: proj.id, projectName: proj.name, startDate, endDate, percentOfTime,
    openRole: generic ? { allocationId: generic.id, action: "none", title: generic.title } : null,
  };
  if (dryRun) return result;

  const body: Record<string, unknown> = {
    allocationResource: { id: String(emp.id) },
    project: { id: String(proj.id) },
    startDate, endDate,
    allocationType: { id: F.hardTypeId },
    allocationUnit: { id: "P" },
    percentOfTime,
    notes,
  };
  if (a.roleTitle) body[F.roleField] = a.roleTitle.slice(0, 300);
  if (process.env.NS_REQUESTED_BY_ID) body.requestedBy = { id: process.env.NS_REQUESTED_BY_ID };

  const created = await ns<unknown>("POST", "/services/rest/record/v1/resourceAllocation", body);
  const loc = created.headers.get("location") ?? "";
  const idm = /\/resourceAllocation\/(\d+)/.exec(loc);
  if (!idm) throw nerr("netsuite_request_failed", { detail: "no Location header on create", location: loc });
  result.allocationId = Number(idm[1]);
  result.url = `https://${accountHost()}.app.netsuite.com/app/accounting/project/resourceallocation.nl?id=${result.allocationId}`;

  if (generic) {
    const gStart = isoDate(generic.startdate);
    const fillNote = `${stamp}: filled by ${emp.name} (allocation ${result.allocationId})\r\n${generic.notes}`.slice(0, 3900);
    if (gStart < startDate) {
      await ns("PATCH", `/services/rest/record/v1/resourceAllocation/${generic.id}`, { endDate: addDays(startDate, -1), notes: fillNote });
      result.openRole = { allocationId: generic.id, action: "ended", title: generic.title };
    } else {
      // already started: keep the row (recruiting history lives in its notes) but take the demand out
      await ns("PATCH", `/services/rest/record/v1/resourceAllocation/${generic.id}`, { allocationUnit: { id: "H" }, numberHours: 0, notes: fillNote });
      result.openRole = { allocationId: generic.id, action: "zeroed", title: generic.title };
    }
  }
  return result;
}

/** Health check for /api/allocate GET: can we reach NetSuite with these credentials? */
export async function netsuitePing(): Promise<{ ok: boolean; detail?: unknown }> {
  if (!netsuiteConfigured()) return { ok: false, detail: "not configured" };
  try {
    const rows = await suiteql("SELECT COUNT(*) AS n FROM resourceallocation WHERE enddate >= CURRENT_DATE");
    return { ok: true, detail: { activeAllocations: rows[0]?.n ?? null } };
  } catch (e) {
    return { ok: false, detail: (e as { detail?: unknown }).detail ?? String(e) };
  }
}
