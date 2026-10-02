// POST /api/meeting-log/import - the Granola feed (Oct 2 2026).
//
// A scheduled Claude task reads the Monday resource-meeting notes from Granola and posts them
// here with `Authorization: Bearer <IMPORT_TOKEN>` (an admin session works too). The notes are
// written into the structures the Meeting Log already renders, so no new UI is needed:
//   - the summary and each decision become comments on the "s:meeting-notes" thread
//     (Meeting Log > Comments, and the ✎ drawer on the Meeting Notes heading),
//   - each action item becomes a normal action item (Meeting Log > Open actions),
//   - the raw payload is kept in meetings/<week> for audit and re-runs.
// Re-posting the same week replaces that week's Granola-sourced comments and open action items.
//
// Body: { week: "YYYY-MM-DD" (Monday), source: { title, url, date }, summary: string,
//         decisions: string[], actionItems: [{ text, owner?, due? }], discussion?: string[] }
import { NextResponse } from "next/server";
import { actor, bearerOk, fail, isAdmin, jsonBody } from "@/lib/api";
import { addDoc, deleteDoc, getDoc, listDocs, setDoc } from "@/lib/store";

export const dynamic = "force-dynamic";

const KEY = "s:meeting-notes";
const LABEL = "Meeting notes (Granola)";
const AUTHOR = "Granola";

type Comment = { id: string; text: string; author: string; ts: number; week: string; status: string; ref: unknown; source?: string };

function str(v: unknown): string { return typeof v === "string" ? v.trim() : ""; }
function strs(v: unknown): string[] { return Array.isArray(v) ? v.map(str).filter(Boolean) : []; }
function cid(): string { return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8); }

export async function POST(req: Request) {
  const who = await actor();
  if (!bearerOk(req) && !isAdmin(who)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const by = who ? `${who} (meeting import)` : "granola-import";
  try {
    const b = await jsonBody(req);
    const week = str(b.week);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(week)) throw Object.assign(new Error("bad_body"), { code: "bad_body" });
    const src = (b.source && typeof b.source === "object" ? b.source : {}) as Record<string, unknown>;
    const source = { title: str(src.title), url: str(src.url), date: str(src.date) };
    const summary = str(b.summary);
    const decisions = strs(b.decisions);
    const discussion = strs(b.discussion);
    const actionItems = (Array.isArray(b.actionItems) ? b.actionItems : [])
      .map((a) => (a && typeof a === "object" ? a : {}) as Record<string, unknown>)
      .map((a) => ({ text: str(a.text), owner: str(a.owner), due: str(a.due) }))
      .filter((a) => a.text);

    // 1. Thread comments: drop this week's earlier Granola comments, then append the new set.
    const thread = await getDoc("threads", KEY);
    const prev = (thread?.body ?? {}) as Record<string, unknown>;
    const kept = (Array.isArray(prev.comments) ? (prev.comments as Comment[]) : [])
      .filter((c) => !(c.source === "granola" && c.week === week));
    const now = Date.now();
    const fresh: Comment[] = [];
    const mk = (text: string, status: string, i: number): Comment =>
      ({ id: cid(), text, author: AUTHOR, ts: now + i, week, status, ref: source.url || null, source: "granola" });
    if (summary) fresh.push(mk(summary, "note", fresh.length));
    decisions.forEach((d) => fresh.push(mk("Decision: " + d, "note", fresh.length)));
    discussion.forEach((d) => fresh.push(mk(d, "watch", fresh.length)));
    let comments = kept.concat(fresh);
    if (comments.length > 300) comments = comments.slice(comments.length - 300);
    await setDoc("threads", KEY, {
      label: LABEL, kind: "section", comments, seeded: true, updated: now,
    }, by);

    // 2. Action items: replace this week's still-open Granola items.
    const existing = await listDocs("actions");
    for (const d of existing) {
      const x = d.body as Record<string, unknown>;
      if (x.source === "granola" && x.week === week && !x.done) await deleteDoc("actions", d.id, by);
    }
    for (const a of actionItems) {
      await addDoc("actions", {
        text: a.text, owner: a.owner || "unassigned", due: a.due, done: false, doneTs: 0,
        key: KEY, label: LABEL, kind: "section", week, author: AUTHOR, ts: Date.now(),
        source: "granola", meetingUrl: source.url,
      }, by);
    }

    // 3. Raw record for audit / re-runs.
    await setDoc("meetings", week, { week, source, summary, decisions, discussion, actionItems, importedAt: now, importedBy: by }, by);

    return NextResponse.json({ ok: true, week, comments: fresh.length, actionItems: actionItems.length });
  } catch (e) {
    return fail(e);
  }
}
