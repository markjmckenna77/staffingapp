import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { snowflakeConfigured } from "@/lib/snowflake";
import { utilizationByPractice } from "@/lib/queries/utilization";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  if (!snowflakeConfigured()) {
    return NextResponse.json({ error: "Snowflake is not configured" }, { status: 503 });
  }
  const year = Number(new URL(req.url).searchParams.get("year") ?? new Date().getFullYear());
  try {
    const rows = await utilizationByPractice(year);
    return NextResponse.json({ year, rows });
  } catch (e) {
    console.error(e);
    return NextResponse.json({ error: "query failed" }, { status: 500 });
  }
}
