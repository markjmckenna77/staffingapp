/**
 * Guardrails for SQL written by the Ask model (lib/ask/agent.ts).
 *
 * Layers, outermost first:
 *   1. The Snowflake role (STAFFING_APP_RO) can read only the cost-free views in
 *      PRD_BI_SUITE.STAFFING_APP. This is the real boundary.
 *   2. checkSql(): one read-only SELECT/WITH statement that reads only those views,
 *      no system functions, no banned column patterns (lib/allowlist.ts).
 *   3. The query is wrapped in an outer SELECT with a row cap.
 *   4. scrubRows(): banned-pattern columns and the standing exclusions are removed from
 *      every result before it reaches the model or the browser.
 */
import { BANNED_PATTERNS } from "@/lib/allowlist";

export const ASK_VIEWS = [
  "WEEKLY_AVAILABILITY",
  "PROJECT_TIME",
  "CONSULTANT",
  "CONSULTANT_PROJECT_DETAIL",
  "OPEN_DEMAND",
] as const;

/** Standing exclusions: never shown anywhere in the app. */
export const EXCLUDED_NAMES = ["Ankitha Thirakala", "Riddhima Shukla"];

export const ROW_CAP = 500;

const FORBIDDEN = [
  /;\s*\S/, // more than one statement
  /\binformation_schema\b/i,
  /\bsnowflake\s*\./i,
  /\baccount_usage\b/i,
  /\bresult_scan\b/i,
  /\bidentifier\s*\(/i,
  /\btable\s*\(/i,
  /\bsystem\$/i,
  /\b(insert|update|delete|merge|create|alter|drop|grant|revoke|truncate|call|copy|put|get|use|set|unset|execute|begin|commit|rollback|undrop|show|describe)\b(?!\s*\()/i,
  /\$\$/,
  /--|\/\*/, // comments can hide text from the checks below
];

export class SqlRefused extends Error {}

function stripStrings(sql: string): string {
  return sql.replace(/'(?:[^']|'')*'/g, "''");
}

export function checkSql(raw: string): string {
  let sql = raw.trim().replace(/;\s*$/, "").trim();
  if (sql.length > 8000) throw new SqlRefused("query too long");
  if (!/^(select|with)\b/i.test(sql)) throw new SqlRefused("only a single SELECT (or WITH ... SELECT) is allowed");
  const bare = stripStrings(sql);
  for (const re of FORBIDDEN) if (re.test(bare)) throw new SqlRefused(`not allowed in this tool: ${re}`);
  for (const re of BANNED_PATTERNS) if (re.test(bare)) throw new SqlRefused(`references a blocked column or schema (${re})`);

  // Every FROM / JOIN source must be one of the views (bare or schema-qualified), a CTE,
  // a subquery or LATERAL FLATTEN.
  const ctes = new Set<string>();
  for (const m of bare.matchAll(/(?:\bwith|,)\s*([A-Za-z_][\w$]*)\s+as\s*\(/gi)) ctes.add(m[1].toUpperCase());
  const allowed = new Set<string>(ASK_VIEWS);
  for (const m of bare.matchAll(/\b(from|join)\s+([^\s(),]+)/gi)) {
    const src = m[2].replace(/"/g, "").toUpperCase();
    if (src === "LATERAL") continue;
    const parts = src.split(".");
    const name = parts[parts.length - 1];
    const qual = parts.slice(0, -1).join(".");
    const okQual = qual === "" || qual === "STAFFING_APP" || qual === "PRD_BI_SUITE.STAFFING_APP";
    if (!(okQual && (allowed.has(name) || (qual === "" && ctes.has(name))))) {
      throw new SqlRefused(`can only read ${ASK_VIEWS.join(", ")} (got ${m[2]})`);
    }
  }
  // Comma joins ("FROM a, b") would slip past the FROM check - refuse them; use JOIN.
  if (/\bfrom\s+[^\s(),]+(\s+(as\s+)?[A-Za-z_][\w$]*)?\s*,/i.test(bare)) {
    throw new SqlRefused("use explicit JOINs instead of comma-separated FROM lists");
  }
  return sql;
}

export function wrap(sql: string): string {
  return `select * from (\n${sql}\n) limit ${ROW_CAP + 1}`;
}

const EXCL = new RegExp(EXCLUDED_NAMES.map((n) => n.replace(/\s+/g, "\\s+")).join("|"), "i");

export function scrubRows(rows: Record<string, unknown>[]): { rows: Record<string, unknown>[]; columns: string[] } {
  const columns = rows.length ? Object.keys(rows[0]).filter((c) => !BANNED_PATTERNS.some((re) => re.test(c))) : [];
  const out: Record<string, unknown>[] = [];
  for (const r of rows) {
    if (Object.values(r).some((v) => typeof v === "string" && EXCL.test(v))) continue;
    const o: Record<string, unknown> = {};
    for (const c of columns) {
      const v = r[c];
      o[c] = v instanceof Date ? v.toISOString().slice(0, 10) : v;
    }
    out.push(o);
  }
  return { rows: out, columns };
}
