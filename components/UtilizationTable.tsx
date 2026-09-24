import { utilizationByPractice, type PracticeMonth } from "@/lib/queries/utilization";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function cls(v: number | null, target = 0.9): string {
  if (v == null) return "muted";
  const gap = (target - v) * 100; // percentage points under target
  if (gap <= 0) return "wk-above";
  if (gap <= 20) return "wk-warning";
  if (gap < 50) return "wk-serious";
  return "wk-critical";
}

function pct(v: number | null): string {
  return v == null ? "–" : `${Math.round(v * 100)}%`;
}

export async function UtilizationTable() {
  const year = new Date().getFullYear();
  let rows: PracticeMonth[] = [];
  let error: string | null = null;
  try {
    rows = await utilizationByPractice(year);
  } catch (e) {
    error = e instanceof Error ? e.message : "query failed";
  }
  if (error) return <p className="muted">Could not load utilization: {error}</p>;

  const months = [...new Set(rows.map((r) => r.DATE_MONTH_ID))].sort();
  const practices = [...new Set(rows.map((r) => r.PRACTICE))].sort();
  const byKey = new Map(rows.map((r) => [`${r.PRACTICE}|${r.DATE_MONTH_ID}`, r]));

  return (
    <table>
      <thead>
        <tr>
          <th>Practice</th>
          {months.map((m) => <th key={m}>{MONTHS[(m % 100) - 1]}</th>)}
          <th>YTD</th>
        </tr>
      </thead>
      <tbody>
        {practices.map((p) => {
          let b = 0, d = 0;
          return (
            <tr key={p}>
              <td>{p}</td>
              {months.map((m) => {
                const r = byKey.get(`${p}|${m}`);
                if (r) { b += r.HRS_BILLABLE; d += r.HRS_UTIL_DENOM; }
                return <td key={m} className={cls(r?.UTILIZATION ?? null)}>{pct(r?.UTILIZATION ?? null)}</td>;
              })}
              <td className={cls(d > 0 ? b / d : null)}><strong>{pct(d > 0 ? b / d : null)}</strong></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
