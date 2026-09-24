/**
 * Column allowlist for everything that leaves Snowflake through this app.
 *
 * Two layers protect cost, salary and pay-rate data:
 *   1. The Snowflake role the service account uses must not be granted those columns.
 *   2. This allowlist: every query declares the columns it selects, and every result
 *      row is filtered to them. Anything not listed is dropped before it reaches a
 *      response. A query that references a banned pattern is refused outright.
 *
 * Keep this file small and reviewed. Adding a column here is a deliberate act.
 */

export const ALLOWED_COLUMNS: Record<string, readonly string[]> = {
  CONS_WEEKLY_AVAILABILITY: [
    "EMPLOYEE_NAME",
    "PRACTICE",
    "RELATIONSHIP",
    "WEEK_START_DATE",
    "DATE_MONTH_ID",
    "DATE_YEAR_ID",
    "HRS_BILLABLE",
    "HRS_UTIL_DENOM",
    "TIME_OFF_HOURS",
    "TARGET_UTILIZATION",
    "FLAG_UNDER_TARGET",
    "ALLOCATED_BILLABLE_HOURS",
    "CUSTOMER_NAME",
    "PROJECT_NAME",
  ],
  CONS_PROJECT_TIME: [
    "EMPLOYEE_NAME",
    "PRACTICE",
    "RELATIONSHIP",
    "CUSTOMER_NAME",
    "PROJECT_NAME",
    "WORK_DATE",
    "ALLOCATED_BILLABLE_HOURS",
    "ACTUAL_BILLABLE_HOURS",
  ],
};

/** Column-name fragments that must never appear in a query issued by this app. */
export const BANNED_PATTERNS = [
  /COST/i,
  /SALARY/i,
  /PAY_?RATE/i,
  /BILL_?RATE/i,
  /WAGE/i,
  /COMP(ENSATION)?\b/i,
  /MARGIN/i,
  /REVENUE/i,
  /COGS/i,
];

export function assertQuerySafe(sql: string): void {
  for (const pattern of BANNED_PATTERNS) {
    if (pattern.test(sql)) {
      throw new Error(`Query refused: matches banned pattern ${pattern}`);
    }
  }
}

export function filterRow<T extends Record<string, unknown>>(
  table: keyof typeof ALLOWED_COLUMNS,
  row: T,
): Partial<T> {
  const allowed = new Set(ALLOWED_COLUMNS[table]);
  const out: Partial<T> = {};
  for (const key of Object.keys(row)) {
    if (allowed.has(key.toUpperCase())) out[key as keyof T] = row[key as keyof T];
  }
  return out;
}
