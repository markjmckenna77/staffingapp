// POST /api/agenda/archive - runbook step 5b, done server-side so the Monday refresh task can
// call it with the bearer token (it has no browser session). Files the Meeting Agenda as it
// stands into agenda_archive/<week> (the Monday of the meeting it records, default: the most
// recent Monday before today) and deletes the agenda items that are checked off, so the live
// agenda opens with only the open items carried over. Unchecked items are never deleted.
// Body (optional JSON): { "week": "YYYY-MM-DD", "source": "archived during the Oct 12 refresh" }
import { NextResponse } from "next/server";
import { actor, bearerOk, fail, isAdmin } from "@/lib/api";
import { deleteDoc, listDocs, setDoc } from "@/lib/store";

export const dynamic = "force-dynamic";

function lastMonday(d = new Date()): string {
  const x = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dow = x.getUTCDay();                       // 0 Sun .. 6 Sat
  x.setUTCDate(x.getUTCDate() - ((dow + 6) % 7));  // this week's Monday
  if (dow === 1) x.setUTCDate(x.getUTCDate() - 7); // on a Monday, archive last week's meeting
  return x.toISOString().slice(0, 10);
}

export async function POST(req: Request) {
  const who = await actor();
  if (!bearerOk(req) && !isAdmin(who)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const by = who ? `${who} (agenda archive)` : "monday-refresh";
  try {
    let body: Record<string, unknown> = {};
    try { body = await req.json(); } catch { /* optional */ }
    const week = typeof body.week === "string" && /^\d{4}-\d{2}-\d{2}$/.test(body.week) ? body.week : lastMonday();
    const source = typeof body.source === "string" && body.source ? body.source.slice(0, 200)
      : `archived by the ${new Date().toISOString().slice(0, 10)} refresh`;
    const agenda = await listDocs("agenda");
    const items = agenda.map((d) => d.body as Record<string, unknown>)
      .map((b) => ({ text: String(b.text ?? ""), done: !!b.done, order: Number(b.order ?? 0), ts: Number(b.ts ?? 0) }))
      .sort((a, b) => a.order - b.order);
    await setDoc("agenda_archive", week, { week, archivedTs: Date.now(), source, items }, by);
    let cleared = 0;
    for (const d of agenda) {
      if ((d.body as Record<string, unknown>).done) { await deleteDoc("agenda", d.id, by); cleared++; }
    }
    return NextResponse.json({ ok: true, week, archived: items.length, cleared, carriedOver: items.length - cleared });
  } catch (e) { return fail(e); }
}
