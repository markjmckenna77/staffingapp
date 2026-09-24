import { query } from "@/lib/snowflake";
import { filterRow } from "@/lib/allowlist";

/**
 * Utilization by practice by month, YTD. Same convention as the dashboard:
 *   month value = SUM(HRS_BILLABLE) / SUM(HRS_UTIL_DENOM)
 *   RELATIONSHIP = 'Direct', PRACTICE <> 'Grand Total'
 * Practice-name variants (AI/ML/AppDev, AI/ML) fold into AI Engineering.
 */
export type PracticeMonth = {
  PRACTICE: string;
  DATE_MONTH_ID: number;
  HRS_BILLABLE: number;
  HRS_UTIL_DENOM: number;
  UTILIZATION: number | null;
};

const PRACTICE_FOLD: Record<string, string> = {
  "AI/ML/AppDev": "AI Engineering",
  "AI/ML": "AI Engineering",
};

export async function utilizationByPractice(year: number): Promise<PracticeMonth[]> {
  const rows = await query<{
    PRACTICE: string;
    DATE_MONTH_ID: number;
    HRS_BILLABLE: number;
    HRS_UTIL_DENOM: number;
  }>(
    `
    select PRACTICE, DATE_MONTH_ID,
           sum(HRS_BILLABLE)   as HRS_BILLABLE,
           sum(HRS_UTIL_DENOM) as HRS_UTIL_DENOM
    from CONS_WEEKLY_AVAILABILITY
    where DATE_YEAR_ID = :1
      and RELATIONSHIP = 'Direct'
      and PRACTICE <> 'Grand Total'
    group by PRACTICE, DATE_MONTH_ID
    `,
    [year],
  );

  // Fold practice variants and re-aggregate.
  const agg = new Map<string, PracticeMonth>();
  for (const raw of rows) {
    const r = filterRow("CONS_WEEKLY_AVAILABILITY", raw) as typeof raw;
    const practice = PRACTICE_FOLD[r.PRACTICE] ?? r.PRACTICE;
    const key = `${practice}|${r.DATE_MONTH_ID}`;
    const cur = agg.get(key) ?? {
      PRACTICE: practice,
      DATE_MONTH_ID: Number(r.DATE_MONTH_ID),
      HRS_BILLABLE: 0,
      HRS_UTIL_DENOM: 0,
      UTILIZATION: null,
    };
    cur.HRS_BILLABLE += Number(r.HRS_BILLABLE ?? 0);
    cur.HRS_UTIL_DENOM += Number(r.HRS_UTIL_DENOM ?? 0);
    agg.set(key, cur);
  }
  for (const v of agg.values()) {
    v.UTILIZATION = v.HRS_UTIL_DENOM > 0 ? v.HRS_BILLABLE / v.HRS_UTIL_DENOM : null;
  }
  return [...agg.values()].sort(
    (a, b) => a.PRACTICE.localeCompare(b.PRACTICE) || a.DATE_MONTH_ID - b.DATE_MONTH_ID,
  );
}
