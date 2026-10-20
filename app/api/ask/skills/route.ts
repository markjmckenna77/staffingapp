// /api/ask/skills - the skills matrix used by Ask (Oct 16 2026).
//   POST  body = the skills matrix CSV (text/csv), as exported from the Skills Matrix workbook.
//         Auth: an admin session or Bearer IMPORT_TOKEN. Stored in Postgres, never in the repo.
//   GET   how many ratings are loaded and when.
import { NextResponse } from "next/server";
import { actor, bearerOk, fail, isAdmin } from "@/lib/api";
import { getPageMeta } from "@/lib/store";
import { saveSkills, skillsFromCsv } from "@/lib/ask/skills";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!(await actor())) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  try {
    return NextResponse.json((await getPageMeta("skills")) ?? { stored: false });
  } catch (e) { return fail(e); }
}

export async function POST(req: Request) {
  const who = await actor();
  if (!bearerOk(req) && !isAdmin(who)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  try {
    const text = await req.text();
    if (text.length < 100 || text.length > 20 * 1024 * 1024) return NextResponse.json({ error: "bad_body" }, { status: 400 });
    const skills = skillsFromCsv(text);
    if (!skills.length) return NextResponse.json({ error: "bad_body", detail: "no ratings found" }, { status: 400 });
    const meta = await saveSkills(skills, who ?? "import");
    return NextResponse.json({ ok: true, kept: skills.length, people: new Set(skills.map((s) => s.name)).size, ...meta });
  } catch (e) { return fail(e); }
}
