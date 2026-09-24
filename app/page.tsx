import { auth, signOut } from "@/auth";
import { snowflakeConfigured } from "@/lib/snowflake";
import { UtilizationTable } from "@/components/UtilizationTable";

export const dynamic = "force-dynamic";

export default async function Home() {
  const session = await auth();
  const configured = snowflakeConfigured();

  return (
    <main>
      <div className="topbar">
        <div>
          <h1>Staffing</h1>
          <span className="muted">Resource management · Cleartelligence</span>
        </div>
        <form
          action={async () => {
            "use server";
            await signOut({ redirectTo: "/login" });
          }}
        >
          <span className="muted" style={{ marginRight: 12 }}>{session?.user?.email}</span>
          <button className="secondary" type="submit">Sign out</button>
        </form>
      </div>

      <section className="card">
        <h2 style={{ margin: "0 0 8px", fontSize: 16 }}>Utilization by Practice, YTD</h2>
        {configured ? (
          <UtilizationTable />
        ) : (
          <p className="muted">
            Snowflake is not configured yet. Add the SNOWFLAKE_* environment variables (see .env.example)
            and this section will populate from CONS_WEEKLY_AVAILABILITY.
          </p>
        )}
      </section>

      <section className="card">
        <h2 style={{ margin: "0 0 8px", fontSize: 16 }}>Coming in phase 1</h2>
        <p className="muted">
          Summary headline · 8 Week Outlook with open roles · Projects, Roles &amp; Open Demand ·
          Allocation vs Actual (last 4 weeks) · Action items · Meeting log
        </p>
      </section>
    </main>
  );
}
