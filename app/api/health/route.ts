import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { snowflakeConfigured } from "@/lib/snowflake";

export async function GET() {
  const session = await auth();
  return NextResponse.json({
    ok: true,
    time: new Date().toISOString(),
    signedIn: !!session?.user,
    user: session?.user?.email ?? null,
    snowflake: snowflakeConfigured() ? "configured" : "not configured",
    entra: process.env.AUTH_MICROSOFT_ENTRA_ID_ID ? "configured" : "not configured",
  });
}
