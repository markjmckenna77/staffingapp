// Certinia (FinancialForce) PSA adapter - Oct 2 2026 scaffold.
//
// Allocations proposed on the dashboard live in the "allocations" collection with status
// "proposed". When someone marks one entered (PATCH /api/db/allocations/:id {status:"entered"}),
// app/api/db/[collection]/[id]/route.ts calls enterAllocation() FIRST and only records the
// status change if Salesforce accepted it, so the dashboard never claims an assignment exists
// in Certinia when it does not. Snowflake picks the change up on its next load from Salesforce.
//
// Auth: OAuth 2.0 client-credentials flow with an integration user (External Client App /
// Connected App with "Client Credentials Flow" enabled and the run-as user set).
//   SF_LOGIN_URL      https://<mydomain>.my.salesforce.com
//   SF_CLIENT_ID / SF_CLIENT_SECRET
//   SF_API_VERSION    default v61.0
//   SF_ENTER_ENABLED  "true" to perform writes; anything else = dry run (lookups only)
// Object model (standard PSA namespace; confirm field API names in Setup > Object Manager):
//   Contact (pse__Is_Resource__c = true)             the consultant
//   pse__Proj__c                                     the project
//   pse__Schedule__c                                 start/end + hours per weekday
//   pse__Assignment__c                               resource x project x schedule
// Lookups are by name, matching how the dashboard labels consultants and projects.
// Field names are overridable via CERTINIA_* env vars if the org deviates from the defaults.

export type Allocation = {
  id: string;
  kind: "add" | "remove";
  consultant: string;
  project: string;      // "Client / Project" as shown on the dashboard
  roleLabel?: string;
  hours: number;        // per week
  weeks: string[];      // Monday ISO dates
  note?: string;
};

export type EnterResult = {
  dryRun: boolean;
  resourceId: string;
  projectId: string;
  scheduleId?: string;
  assignmentId?: string;
  url?: string;
};

const F = {
  projName: process.env.CERTINIA_PROJECT_NAME_FIELD ?? "Name",
  assignmentStatus: process.env.CERTINIA_ASSIGNMENT_STATUS ?? "Scheduled",
};

export function certiniaConfigured(): boolean {
  return !!(process.env.SF_LOGIN_URL && process.env.SF_CLIENT_ID && process.env.SF_CLIENT_SECRET);
}

function cerr(code: string, detail?: unknown) {
  return Object.assign(new Error(code), { code, detail });
}

let tokenCache: { token: string; instance: string; exp: number } | null = null;

async function token(): Promise<{ token: string; instance: string }> {
  if (tokenCache && tokenCache.exp > Date.now()) return tokenCache;
  const r = await fetch(`${process.env.SF_LOGIN_URL}/services/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: process.env.SF_CLIENT_ID!,
      client_secret: process.env.SF_CLIENT_SECRET!,
    }),
  });
  if (!r.ok) throw cerr("certinia_auth_failed", await r.text());
  const j = (await r.json()) as { access_token: string; instance_url: string };
  tokenCache = { token: j.access_token, instance: j.instance_url, exp: Date.now() + 50 * 60 * 1000 };
  return tokenCache;
}

async function sf<T>(method: string, path: string, body?: unknown): Promise<T> {
  const t = await token();
  const v = process.env.SF_API_VERSION ?? "v61.0";
  const r = await fetch(`${t.instance}/services/data/${v}${path}`, {
    method,
    headers: { authorization: `Bearer ${t.token}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 204) return undefined as T;
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw cerr("certinia_request_failed", j);
  return j as T;
}

function soql(q: string) {
  return sf<{ records: Array<Record<string, string>> }>("GET", `/query?q=${encodeURIComponent(q)}`);
}
const esc = (s: string) => s.replace(/\\/g, "\\\\").replace(/'/g, "\\'");

async function findResource(name: string): Promise<string> {
  const r = await soql(`SELECT Id FROM Contact WHERE pse__Is_Resource__c = true AND Name = '${esc(name)}' LIMIT 2`);
  if (r.records.length !== 1) throw cerr(r.records.length ? "certinia_resource_ambiguous" : "certinia_resource_not_found", name);
  return r.records[0].Id;
}

async function findProject(label: string): Promise<string> {
  // The dashboard shows "Client / Project"; try the project part first, then the whole label.
  const candidates = [label.split(" / ").pop()!.trim(), label.trim()];
  for (const c of candidates) {
    const r = await soql(`SELECT Id FROM pse__Proj__c WHERE ${F.projName} = '${esc(c)}' AND pse__Is_Active__c = true LIMIT 2`);
    if (r.records.length === 1) return r.records[0].Id;
    if (r.records.length > 1) throw cerr("certinia_project_ambiguous", c);
  }
  throw cerr("certinia_project_not_found", label);
}

function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Creates (or, for a removal, closes) the Certinia assignment for a dashboard allocation. */
export async function enterAllocation(a: Allocation): Promise<EnterResult> {
  if (!certiniaConfigured()) throw cerr("certinia_not_configured");
  if (!a.weeks?.length) throw cerr("bad_body", "allocation has no weeks");
  const dryRun = process.env.SF_ENTER_ENABLED !== "true";
  const weeks = a.weeks.slice().sort();
  const start = weeks[0], end = addDays(weeks[weeks.length - 1], 4);   // Monday .. Friday of last week
  const resourceId = await findResource(a.consultant);
  const projectId = await findProject(a.project);

  if (a.kind === "remove") {
    const r = await soql(`SELECT Id, pse__Schedule__c FROM pse__Assignment__c WHERE pse__Resource__c = '${resourceId}' AND pse__Project__c = '${projectId}' AND pse__Status__c != 'Closed' LIMIT 1`);
    if (!r.records.length) throw cerr("certinia_assignment_not_found");
    if (dryRun) return { dryRun, resourceId, projectId, assignmentId: r.records[0].Id };
    // End the schedule the day before the removal starts and close the assignment.
    await sf("PATCH", `/sobjects/pse__Schedule__c/${r.records[0].pse__Schedule__c}`, { pse__End_Date__c: addDays(start, -1) });
    await sf("PATCH", `/sobjects/pse__Assignment__c/${r.records[0].Id}`, { pse__Status__c: "Closed" });
    return { dryRun, resourceId, projectId, assignmentId: r.records[0].Id, scheduleId: r.records[0].pse__Schedule__c, url: await recordUrl(r.records[0].Id) };
  }

  if (dryRun) return { dryRun, resourceId, projectId };
  const perDay = Math.round((a.hours / 5) * 100) / 100;
  const sched = await sf<{ id: string }>("POST", "/sobjects/pse__Schedule__c", {
    pse__Start_Date__c: start, pse__End_Date__c: end,
    pse__Monday_Hours__c: perDay, pse__Tuesday_Hours__c: perDay, pse__Wednesday_Hours__c: perDay,
    pse__Thursday_Hours__c: perDay, pse__Friday_Hours__c: perDay, pse__Saturday_Hours__c: 0, pse__Sunday_Hours__c: 0,
  });
  const asg = await sf<{ id: string }>("POST", "/sobjects/pse__Assignment__c", {
    Name: `${a.consultant} - ${a.project}`.slice(0, 80),
    pse__Resource__c: resourceId, pse__Project__c: projectId, pse__Schedule__c: sched.id,
    pse__Status__c: F.assignmentStatus, pse__Role__c: a.roleLabel || undefined,
    pse__Description__c: a.note ? `From the staffing dashboard: ${a.note}`.slice(0, 255) : "From the staffing dashboard",
  });
  return { dryRun, resourceId, projectId, scheduleId: sched.id, assignmentId: asg.id, url: await recordUrl(asg.id) };
}

async function recordUrl(id: string): Promise<string> {
  const t = await token();
  return `${t.instance}/${id}`;
}
