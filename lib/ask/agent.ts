/**
 * Natural-language questions over the staffing data: a small tool-use loop with Claude.
 * The model writes SQL; lib/ask/guard.ts checks it; lib/snowflake.ts runs it as the read-only
 * service role; results are scrubbed before the model or the browser sees them.
 *
 * Env: ANTHROPIC_API_KEY (required), ANTHROPIC_MODEL (optional).
 */
import { query } from "@/lib/snowflake";
import { checkSql, scrubRows, wrap, ROW_CAP, SqlRefused, ASK_VIEWS } from "./guard";
import { systemPrompt } from "./prompt";
import { findSkills, loadSkills } from "./skills";

const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-4-5";
const MAX_STEPS = 8;

export type AskTable = { title: string; sql?: string; columns: string[]; rows: Record<string, unknown>[]; truncated: boolean };
export type AskResult = { answer: string; tables: AskTable[]; steps: number; model: string };
export type Turn = { q: string; a: string };

type Block =
  | { type: "text"; text: string }
  | { type: "tool_use"; id: string; name: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool_use_id: string; content: string; is_error?: boolean };
type Msg = { role: "user" | "assistant"; content: string | Block[] };

export function askConfigured(): boolean {
  return !!process.env.ANTHROPIC_API_KEY;
}

let viewCache: { at: number; views: string[] } | null = null;
async function availableViews(): Promise<string[]> {
  if (viewCache && Date.now() - viewCache.at < 10 * 60_000) return viewCache.views;
  let views: string[] = [...ASK_VIEWS];
  try {
    const rows = await query<{ TABLE_NAME: string }>(
      "select TABLE_NAME from PRD_BI_SUITE.INFORMATION_SCHEMA.VIEWS where TABLE_SCHEMA = 'STAFFING_APP'",
    );
    const have = new Set(rows.map((r) => String(r.TABLE_NAME).toUpperCase()));
    views = ASK_VIEWS.filter((v) => have.has(v));
  } catch (e) {
    console.error("ask: could not list views", e);
  }
  viewCache = { at: Date.now(), views };
  return views;
}

function tools(hasSkills: boolean) {
  const t: Record<string, unknown>[] = [
    {
      name: "run_sql",
      description: "Run one read-only Snowflake SELECT against the staffing views and get the rows back (JSON).",
      input_schema: {
        type: "object",
        properties: {
          sql: { type: "string", description: "A single SELECT or WITH ... SELECT statement." },
          show: { type: "boolean", description: "true if this result should be shown to the user as a table." },
          title: { type: "string", description: "Short table title when show is true." },
        },
        required: ["sql"],
      },
    },
  ];
  if (hasSkills) {
    t.push({
      name: "find_skills",
      description: "Find people in the skills matrix rated on any of the given skills/technologies (substring match).",
      input_schema: {
        type: "object",
        properties: {
          skills: { type: "array", items: { type: "string" }, description: "e.g. [\"Snowflake\", \"dbt\"]" },
          min_rating: { type: "integer", description: "1-5, default 3" },
          show: { type: "boolean" },
          title: { type: "string" },
        },
        required: ["skills"],
      },
    });
  }
  return t;
}

async function claude(system: string, messages: Msg[], toolDefs: Record<string, unknown>[]) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": process.env.ANTHROPIC_API_KEY as string,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 2000,
      system: [{ type: "text", text: system, cache_control: { type: "ephemeral" } }],
      tools: toolDefs,
      messages,
    }),
  });
  if (!res.ok) {
    const body = await res.text();
    console.error("ask: anthropic", res.status, body.slice(0, 500));
    throw Object.assign(new Error("model_error"), { code: "model_error", status: res.status });
  }
  return (await res.json()) as { content: Block[]; stop_reason: string };
}

function forModel(rows: Record<string, unknown>[], columns: string[], truncated: boolean): string {
  const shown = rows.slice(0, 150);
  let s = JSON.stringify({ columns, rows: shown.map((r) => columns.map((c) => r[c])), row_count: rows.length, truncated });
  if (s.length > 30_000) s = s.slice(0, 30_000) + " ...[cut - aggregate further]";
  return s;
}

export async function ask(question: string, history: Turn[], today: string): Promise<AskResult> {
  const [views, skills] = await Promise.all([availableViews(), loadSkills()]);
  const system = systemPrompt(views, !!skills?.length, today);
  const toolDefs = tools(!!skills?.length);

  const messages: Msg[] = [];
  for (const t of history.slice(-3)) {
    messages.push({ role: "user", content: t.q.slice(0, 1000) });
    messages.push({ role: "assistant", content: t.a.slice(0, 3000) || "(no answer)" });
  }
  messages.push({ role: "user", content: question });

  const tables: AskTable[] = [];
  for (let step = 1; step <= MAX_STEPS; step++) {
    const resp = await claude(system, messages, step === MAX_STEPS ? [] : toolDefs);
    messages.push({ role: "assistant", content: resp.content });
    const uses = resp.content.filter((b): b is Extract<Block, { type: "tool_use" }> => b.type === "tool_use");
    if (resp.stop_reason !== "tool_use" || !uses.length) {
      const answer = resp.content.filter((b) => b.type === "text").map((b) => (b as { text: string }).text).join("\n").trim();
      return { answer, tables: tables.slice(0, 3), steps: step, model: MODEL };
    }
    const results: Block[] = [];
    for (const u of uses) {
      const show = u.input.show === true;
      const title = String(u.input.title ?? "").slice(0, 120) || "Result";
      try {
        if (u.name === "run_sql") {
          const sql = checkSql(String(u.input.sql ?? ""));
          const raw = await query(wrap(sql));
          const truncated = raw.length > ROW_CAP;
          const { rows, columns } = scrubRows(raw.slice(0, ROW_CAP));
          if (show) tables.push({ title, sql, columns, rows, truncated });
          results.push({ type: "tool_result", tool_use_id: u.id, content: forModel(rows, columns, truncated) });
        } else if (u.name === "find_skills" && skills) {
          const terms = Array.isArray(u.input.skills) ? (u.input.skills as unknown[]).map(String) : [];
          const rows = findSkills(skills, terms, Number(u.input.min_rating) || 3);
          const columns = rows.length ? Object.keys(rows[0]) : [];
          if (show) tables.push({ title, columns, rows, truncated: false });
          results.push({ type: "tool_result", tool_use_id: u.id, content: forModel(rows, columns, false) });
        } else {
          results.push({ type: "tool_result", tool_use_id: u.id, content: `unknown tool ${u.name}`, is_error: true });
        }
      } catch (e) {
        const msg = e instanceof SqlRefused ? `Refused: ${e.message}` : `Error: ${(e as Error).message ?? e}`.slice(0, 800);
        results.push({ type: "tool_result", tool_use_id: u.id, content: msg, is_error: true });
      }
    }
    messages.push({ role: "user", content: results });
  }
  return { answer: "I couldn't finish that one - try asking a narrower question.", tables, steps: MAX_STEPS, model: MODEL };
}
