// Shared document store for the dashboard's collaborative data (meeting log threads,
// agenda, action items, proposed allocations, weekly snapshots, archived agendas).
//
// Oct 2 2026: replaces the claude.ai artifact database. The dashboard page keeps using a
// Firestore-style API (window.claude.use("db")) - app/route.ts injects a shim that maps
// it onto /api/db, which is backed by this module. Documents are schemaless JSON so the
// page's existing shapes carry over unchanged; every write is journaled in doc_log.
import { Pool } from "pg";

export type Doc = { id: string; body: Record<string, unknown>; deleted: boolean; updated: number; updatedBy: string };

const COLLECTIONS = new Set([
  "threads", "actions", "allocations", "snapshots", "agenda", "agenda_archive", "role_comments", "meetings",
]);
const ID_RE = /^[A-Za-z0-9_.:~@+-]{1,200}$/;

let pool: Pool | null = null;
let schemaReady: Promise<void> | null = null;

function connectionString(): string {
  const url = process.env.DATABASE_URL ?? process.env.POSTGRES_URL ?? process.env.POSTGRES_PRISMA_URL;
  if (!url) throw Object.assign(new Error("store_not_configured"), { code: "store_not_configured" });
  return url;
}

function getPool(): Pool {
  if (!pool) {
    const url = connectionString();
    // Hosted Postgres (Neon / Vercel) requires TLS; a local database for tests does not.
    const local = /@(localhost|127\.0\.0\.1)[:/]/.test(url) && !/sslmode=require/.test(url);
    pool = new Pool({ connectionString: url, max: 3, ssl: local ? undefined : { rejectUnauthorized: false } });
  }
  return pool;
}

async function ensureSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const p = getPool();
      await p.query(`
        CREATE TABLE IF NOT EXISTS docs (
          collection text NOT NULL,
          id text NOT NULL,
          body jsonb NOT NULL DEFAULT '{}'::jsonb,
          deleted boolean NOT NULL DEFAULT false,
          updated bigint NOT NULL,
          updated_by text NOT NULL DEFAULT '',
          PRIMARY KEY (collection, id)
        );
        CREATE INDEX IF NOT EXISTS docs_updated_idx ON docs (collection, updated);
        CREATE TABLE IF NOT EXISTS doc_log (
          seq bigserial PRIMARY KEY,
          ts bigint NOT NULL,
          actor text NOT NULL,
          op text NOT NULL,
          collection text NOT NULL,
          id text NOT NULL,
          body jsonb
        );
      `);
    })().catch((e) => { schemaReady = null; throw e; });
  }
  return schemaReady;
}

export function assertCollection(c: string): string {
  if (!COLLECTIONS.has(c)) throw Object.assign(new Error("unknown_collection"), { code: "unknown_collection" });
  return c;
}
export function assertId(id: string): string {
  if (!ID_RE.test(id)) throw Object.assign(new Error("bad_id"), { code: "bad_id" });
  return id;
}

export function newId(): string {
  const a = Date.now().toString(36);
  const b = Math.random().toString(36).slice(2, 8);
  return `${a}-${b}`;
}

function row(r: { id: string; body: Record<string, unknown>; deleted: boolean; updated: string | number; updated_by: string }): Doc {
  return { id: r.id, body: r.body ?? {}, deleted: r.deleted, updated: Number(r.updated), updatedBy: r.updated_by };
}

/** All live documents in a collection, or (with since) every document changed after that
 *  timestamp including tombstones, so a polling client can reconcile deletes. */
export async function listDocs(collection: string, since = 0): Promise<Doc[]> {
  await ensureSchema();
  assertCollection(collection);
  const q = since > 0
    ? { text: "SELECT id, body, deleted, updated, updated_by FROM docs WHERE collection=$1 AND updated>$2 ORDER BY updated", values: [collection, since] }
    : { text: "SELECT id, body, deleted, updated, updated_by FROM docs WHERE collection=$1 AND deleted=false ORDER BY updated", values: [collection] };
  const r = await getPool().query(q);
  return r.rows.map(row);
}

export async function getDoc(collection: string, id: string): Promise<Doc | null> {
  await ensureSchema();
  assertCollection(collection); assertId(id);
  const r = await getPool().query(
    "SELECT id, body, deleted, updated, updated_by FROM docs WHERE collection=$1 AND id=$2", [collection, id]);
  if (!r.rows.length || r.rows[0].deleted) return null;
  return row(r.rows[0]);
}

async function journal(actor: string, op: string, collection: string, id: string, body: unknown) {
  await getPool().query(
    "INSERT INTO doc_log (ts, actor, op, collection, id, body) VALUES ($1,$2,$3,$4,$5,$6)",
    [Date.now(), actor, op, collection, id, body === undefined ? null : JSON.stringify(body)]);
}

export async function setDoc(collection: string, id: string, body: Record<string, unknown>, actor: string): Promise<Doc> {
  await ensureSchema();
  assertCollection(collection); assertId(id);
  const now = Date.now();
  const r = await getPool().query(
    `INSERT INTO docs (collection, id, body, deleted, updated, updated_by) VALUES ($1,$2,$3,false,$4,$5)
     ON CONFLICT (collection, id) DO UPDATE SET body=EXCLUDED.body, deleted=false, updated=EXCLUDED.updated, updated_by=EXCLUDED.updated_by
     RETURNING id, body, deleted, updated, updated_by`,
    [collection, id, JSON.stringify(body), now, actor]);
  await journal(actor, "set", collection, id, body);
  return row(r.rows[0]);
}

export async function updateDoc(collection: string, id: string, patch: Record<string, unknown>, actor: string): Promise<Doc> {
  await ensureSchema();
  assertCollection(collection); assertId(id);
  const now = Date.now();
  const r = await getPool().query(
    `UPDATE docs SET body = body || $3::jsonb, deleted=false, updated=$4, updated_by=$5
     WHERE collection=$1 AND id=$2 RETURNING id, body, deleted, updated, updated_by`,
    [collection, id, JSON.stringify(patch), now, actor]);
  if (!r.rows.length) throw Object.assign(new Error("not_found"), { code: "not_found" });
  await journal(actor, "update", collection, id, patch);
  return row(r.rows[0]);
}

export async function addDoc(collection: string, body: Record<string, unknown>, actor: string): Promise<Doc> {
  return setDoc(collection, newId(), body, actor);
}

/** Soft delete: the tombstone stays so pollers see the removal, and doc_log keeps the body. */
export async function deleteDoc(collection: string, id: string, actor: string): Promise<void> {
  await ensureSchema();
  assertCollection(collection); assertId(id);
  const now = Date.now();
  const prev = await getPool().query("SELECT body FROM docs WHERE collection=$1 AND id=$2", [collection, id]);
  await getPool().query(
    "UPDATE docs SET deleted=true, body='{}'::jsonb, updated=$3, updated_by=$4 WHERE collection=$1 AND id=$2",
    [collection, id, now, actor]);
  await journal(actor, "delete", collection, id, prev.rows[0]?.body);
}

export function errorCode(e: unknown): string {
  const c = (e as { code?: string })?.code;
  return typeof c === "string" ? c : "error";
}

// ------------------------------------------------------------------ published pages
// The weekly dashboard HTML itself (Oct 5 2026): the Monday refresh posts the built page to
// /api/dashboard and GET / serves it, so a refresh no longer needs a git commit.
export type PageMeta = { key: string; updated: number; updatedBy: string; note: string; bytes: number };

async function ensurePages(): Promise<void> {
  await ensureSchema();
  await getPool().query(`
    CREATE TABLE IF NOT EXISTS pages (
      key text PRIMARY KEY,
      html text NOT NULL,
      updated bigint NOT NULL,
      updated_by text NOT NULL DEFAULT '',
      note text NOT NULL DEFAULT ''
    );`);
}

export async function getPage(key: string): Promise<{ html: string; meta: PageMeta } | null> {
  await ensurePages();
  const r = await getPool().query("SELECT html, updated, updated_by, note FROM pages WHERE key=$1", [key]);
  if (!r.rows.length) return null;
  const row = r.rows[0];
  return { html: row.html, meta: { key, updated: Number(row.updated), updatedBy: row.updated_by, note: row.note, bytes: row.html.length } };
}

export async function getPageMeta(key: string): Promise<PageMeta | null> {
  await ensurePages();
  const r = await getPool().query("SELECT updated, updated_by, note, length(html) AS bytes FROM pages WHERE key=$1", [key]);
  if (!r.rows.length) return null;
  const row = r.rows[0];
  return { key, updated: Number(row.updated), updatedBy: row.updated_by, note: row.note, bytes: Number(row.bytes) };
}

export async function putPage(key: string, html: string, actor: string, note: string): Promise<PageMeta> {
  await ensurePages();
  const now = Date.now();
  await getPool().query(
    `INSERT INTO pages (key, html, updated, updated_by, note) VALUES ($1,$2,$3,$4,$5)
     ON CONFLICT (key) DO UPDATE SET html=EXCLUDED.html, updated=EXCLUDED.updated, updated_by=EXCLUDED.updated_by, note=EXCLUDED.note`,
    [key, html, now, actor, note]);
  await journal(actor, "page", "pages", key, { note, bytes: html.length });
  return { key, updated: now, updatedBy: actor, note, bytes: html.length };
}
