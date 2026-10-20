// POST /api/ask - natural-language questions about staffing (Oct 16 2026).
//   body  {question: string, history?: [{q, a}]}   (history = the last few exchanges, for follow-ups)
//   200   {answer, tables: [{title, sql?, columns, rows, truncated}], steps, model}
// Any signed-in user. Read-only: see lib/ask/guard.ts for what the model's SQL may touch.
import { NextResponse } from "next/server";
import { actor, jsonBody } from "@/lib/api";
import { snowflakeConfigured } from "@/lib/snowflake";
import { ask, askConfigured, type Turn } from "@/lib/ask/agent";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

// Light per-instance throttle: 20 questions / 10 minutes per person.
const recent = new Map<string, number[]>();
function throttled(who: string): boolean {
  const now = Date.now();
  const list = (recent.get(who) ?? []).filter((t) => now - t < 10 * 60_000);
  list.push(now);
  recent.set(who, list);
  return list.length > 20;
}

export async function POST(req: Request) {
  const who = await actor();
  if (!who) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  if (!askConfigured()) return NextResponse.json({ error: "ask_not_configured", detail: "ANTHROPIC_API_KEY is not set for this deployment." }, { status: 503 });
  if (!snowflakeConfigured()) return NextResponse.json({ error: "snowflake_not_configured" }, { status: 503 });
  if (throttled(who)) return NextResponse.json({ error: "slow_down", detail: "Too many questions in the last few minutes - try again shortly." }, { status: 429 });

  let body: Record<string, unknown>;
  try { body = await jsonBody(req); } catch { return NextResponse.json({ error: "bad_body" }, { status: 400 }); }
  const question = String(body.question ?? "").trim().slice(0, 1000);
  if (question.length < 3) return NextResponse.json({ error: "bad_body", detail: "Ask a question." }, { status: 400 });
  const history: Turn[] = Array.isArray(body.history)
    ? (body.history as unknown[]).slice(-3).map((t) => {
        const o = (t ?? {}) as Record<string, unknown>;
        return { q: String(o.q ?? ""), a: String(o.a ?? "") };
      }).filter((t) => t.q)
    : [];

  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(new Date());
  const started = Date.now();
  try {
    const result = await ask(question, history, today);
    console.log(JSON.stringify({ ask: question, by: who, steps: result.steps, tables: result.tables.length, ms: Date.now() - started }));
    return NextResponse.json(result);
  } catch (e) {
    console.error("ask failed", e);
    const code = (e as { code?: string }).code ?? "ask_failed";
    return NextResponse.json({ error: code, detail: "Something went wrong answering that - try again or rephrase." }, { status: 502 });
  }
}
