import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { errorCode } from "@/lib/store";

export const ADMIN_EMAILS = (process.env.ADMIN_EMAILS ?? "mark.mckenna@cleartelligence.com")
  .split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);

/** Signed-in user's email, or null. Every /api/db write is attributed to it. */
export async function actor(): Promise<string | null> {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  return email || null;
}

export function isAdmin(email: string | null): boolean {
  return !!email && ADMIN_EMAILS.includes(email);
}

/** People allowed to push allocations into Certinia (APPROVER_EMAILS); admins always are. */
export const APPROVER_EMAILS = (process.env.APPROVER_EMAILS ?? "")
  .split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
export function isApprover(email: string | null): boolean {
  return isAdmin(email) || (!!email && APPROVER_EMAILS.includes(email));
}

/** Service-to-service auth for scheduled imports (Granola): a bearer token from IMPORT_TOKEN. */
export function bearerOk(req: Request): boolean {
  const want = process.env.IMPORT_TOKEN;
  if (!want) return false;
  const got = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  return got.length > 0 && got === want;
}

export function unauthorized() {
  return NextResponse.json({ error: "unauthorized" }, { status: 401 });
}

export function fail(e: unknown) {
  const code = errorCode(e);
  const status = code === "store_not_configured" ? 503
    : code === "unknown_collection" || code === "bad_id" || code === "bad_body" ? 400
    : code === "not_found" ? 404 : 500;
  if (status === 500) console.error(e);
  return NextResponse.json({ error: code }, { status });
}

export async function jsonBody(req: Request): Promise<Record<string, unknown>> {
  let b: unknown;
  try { b = await req.json(); } catch { throw Object.assign(new Error("bad_body"), { code: "bad_body" }); }
  if (!b || typeof b !== "object" || Array.isArray(b)) throw Object.assign(new Error("bad_body"), { code: "bad_body" });
  return b as Record<string, unknown>;
}
