/**
 * Column allowlist for everything that leaves Snowflake through this app.
 *
 * Two layers protect cost, salary and pay-rate data:
 *   1. The Snowflake role the service account uses (STAFFING_APP_RO) is granted only the
 *      views in PRD_BI_SUITE.STAFFING_APP, which are built without the cost columns.
 *      It has no access to the raw CONS_BI tables.
 *   2. This allowlist: every query declares the columns it selects, and every result
 *      row is filtered to them. Anything not listed is dropped before it reaches a
 *      response. A query that references a banned pattern is refused outright.
 *
 * Keep this file small and reviewed. Adding a column here is a deliberate act.
 * Column names verified against PRD_BI_SUITE.CONS_BI on 2026-09-25.
 */

export const ALLOWED_COLUMNS: Record<string, readonly string[]> = {
  WEEKLY_AVAILABILITY: [
    "WEEK_FIRST_DAY_AT",
    "DATE_MONTH_ID",
    "DATE_YEAR_ID",
    "CONSULTANT_ID",
    "CONSULTANT_NAME",
    "TARGET_UTILIZATION",
    "HRS_TARGET_BILLABLE",
    "HRS_BILLABLE",
    "HRS_UNUSED",
    "HRS_ASSIGNED",
    "HRS_TIME_OFF",
    "HRS_AUTHORIZED_PROJECTS",
    "HRS_OVERBURN",
    "HRS_UTIL_DENOM",
    "PRACTICE",
    "REGION",
    "RELATIONSHIP",
    "EMPLOYEE_TYPE",
    "JOB_LEVEL",
    "COUNTRY",
    "OFFICE",
    "REPORTS_TO",
    "STATUS_CATEGORY",
    "PROJECT_LIST",
    "BILLABILITY_PCT",
    "AVAILABILITY_PCT",
    "ASSIGNED_PCT",
    "FLAG_NO_ACTIVE_PROJECT",
    "FLAG_TIME_OFF",
    "FLAG_OVERBURN",
    "FLAG_UNDER_TARGET",
  ],
  PROJECT_TIME: [
    "PROJECT_ID",
    "DATE",
    "CONSULTANT_ID",
    "CONSULTANT_NAME",
    "CONSULTANT_COUNTRY",
    "CONSULTANT_REGION",
    "RELATIONSHIP",
    "RESOURCE_TYPE",
    "PRACTICE",
    "EMPLOYEE_STATUS_CATEGORY",
    "HRS_UTIL_DENOM",
    "HRS_TIME_OFF",
    "YEAR_ID",
    "MONTH_ID",
    "QUARTER_ID",
    "WEEK_FIRST_DAY_AT",
    "ACTUAL_BILLABLE_HOURS",
    "ACTUAL_NON_BILLABLE_HOURS",
    "ACTUAL_TOTAL_HOURS",
    "ALLOCATED_BILLABLE_HOURS",
    "ALLOCATED_NON_BILLABLE_HOURS",
    "ALLOCATED_TOTAL_HOURS",
    "PROJECT_NAME",
    "PROJECT_STATUS",
    "OPTY_STAGE",
    "PROJECT_TYPE",
    "CUSTOMER_NAME",
    "INTERNAL_FLAG",
    "PROJECT_TOTAL_HOURS",
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
  /CONS_BI\./i, // raw schema: the app must only read PRD_BI_SUITE.STAFFING_APP views
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
