/**
 * Skills matrix for Ask. The matrix is a CSV owned by Dustin Cabral (not in Snowflake), so it is
 * uploaded to the app (POST /api/ask/skills) and stored as JSON in the pages table under the key
 * "skills" - nothing about it is committed to the repo.
 *
 * Everyone defaults to a baseline rating, so only real expertise is kept: rating >= 3, or 2 with
 * at least a year of experience (same rule the dashboard's staffing suggestions use).
 */
import { getPage, putPage } from "@/lib/store";
import { EXCLUDED_NAMES } from "./guard";

export type Skill = { name: string; skill: string; category: string; rating: number; interest: number; years: number };

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((x) => x.trim()));
}

export function skillsFromCsv(text: string): Skill[] {
  const [head, ...body] = parseCsv(text);
  const ix = (re: RegExp) => head.findIndex((h) => re.test(h.trim()));
  const col = {
    category: ix(/^category$/i), skill: ix(/skill$/i), rating: ix(/^skill rating$/i),
    interest: ix(/^interest/i), years: ix(/^years/i), name: ix(/^name$/i),
  };
  if (Object.values(col).some((v) => v < 0)) throw Object.assign(new Error("bad_body"), { code: "bad_body" });
  const out: Skill[] = [];
  for (const r of body) {
    const s: Skill = {
      name: (r[col.name] ?? "").trim(), skill: (r[col.skill] ?? "").trim(), category: (r[col.category] ?? "").trim(),
      rating: Number(r[col.rating]) || 0, interest: Number(r[col.interest]) || 0, years: Number(r[col.years]) || 0,
    };
    if (!s.name || !s.skill || EXCLUDED_NAMES.includes(s.name)) continue;
    if (s.rating >= 3 || (s.rating === 2 && s.years >= 1)) out.push(s);
  }
  return out;
}

export async function saveSkills(skills: Skill[], actor: string) {
  return putPage("skills", JSON.stringify(skills), actor, `${skills.length} skill ratings`);
}

let cache: { at: number; skills: Skill[] | null } | null = null;

export async function loadSkills(): Promise<Skill[] | null> {
  if (cache && Date.now() - cache.at < 10 * 60_000) return cache.skills;
  let skills: Skill[] | null = null;
  try {
    const p = await getPage("skills");
    skills = p ? (JSON.parse(p.html) as Skill[]) : null;
  } catch { skills = null; }
  cache = { at: Date.now(), skills };
  return skills;
}

/** People rated on any of the given skills (case-insensitive substring match on the skill name). */
export function findSkills(all: Skill[], terms: string[], minRating = 3) {
  const t = terms.map((x) => x.toLowerCase().trim()).filter(Boolean);
  const hits = all.filter((s) => s.rating >= Math.min(minRating, 5) && t.some((x) => s.skill.toLowerCase().includes(x)));
  hits.sort((a, b) => b.rating - a.rating || b.years - a.years || a.name.localeCompare(b.name));
  return hits.slice(0, 300).map((s) => ({
    CONSULTANT_NAME: s.name, SKILL: s.skill, CATEGORY: s.category, SKILL_RATING: s.rating, INTEREST: s.interest, YEARS: s.years,
  }));
}
