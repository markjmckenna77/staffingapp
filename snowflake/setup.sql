-- =====================================================================
-- Cleartelligence Staffing App: Snowflake service account setup
-- Run as ACCOUNTADMIN (or SECURITYADMIN + a role that owns PRD_BI_SUITE).
-- Account: AHOWHJS-ET65504 (Azure East US 2)
-- Prepared 2026-09-25. Safe to re-run: every statement is IF NOT EXISTS / OR REPLACE.
-- =====================================================================

use role ACCOUNTADMIN;

-- 1. Read-only role for the app
create role if not exists STAFFING_APP_RO
  comment = 'Read-only access for the Vercel staffing app (no cost/rate columns)';

-- 2. Service user with key-pair auth only (no password)
create user if not exists SVC_STAFFING_APP
  type = SERVICE
  default_role = STAFFING_APP_RO
  default_warehouse = TRANSFORMING
  comment = 'Service account for staffingapp on Vercel; owner Mark McKenna';

alter user SVC_STAFFING_APP set rsa_public_key =
'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAr3f2q+w0pQr0/9KpC8PPHH7Yjq3qy9k5XnMCJDjroas08amkhOhze0WdLqoIkPy4xjAnSMJYkxECH3RFJYM0ehZPjpdG/e3lwkaejzoqC9T32fapbNSlIVxlGS/BwR2xZHhzVHSUKk7MXI8BD+FlU7VtgPMfoxug66B1Heq2QTroQiLJESAnNzhF4BnN99VIzRm3tMWKPNszL99Zbl8i4KMTVzS4P1Cw7MwH7xwPBzRhw85TYWmVpmnOMa1OVa75QE7WzN90bsOXi2zPYzlmjvLKn/8LWOC11NcA/UyPIvDiQGIZHUf1wjA0GjVIR3TaR10Gb6LJ8KRFd/oSmq8wyQIDAQAB';

grant role STAFFING_APP_RO to user SVC_STAFFING_APP;

-- 3. A dedicated schema of views that expose only the columns the app needs.
--    The raw tables in CONS_BI are NOT granted; CONS_PROJECT_TIME carries
--    LABOR_COST / ACTUAL_TOTAL_COST / ALLOCATED_TOTAL_COST which must never reach the app.
create schema if not exists PRD_BI_SUITE.STAFFING_APP
  comment = 'Cost-free views for the staffing app';

create or replace view PRD_BI_SUITE.STAFFING_APP.WEEKLY_AVAILABILITY as
select
  WEEK_FIRST_DAY_AT, DATE_MONTH_ID, DATE_YEAR_ID,
  CONSULTANT_ID, CONSULTANT_NAME,
  TARGET_UTILIZATION, HRS_TARGET_BILLABLE, HRS_BILLABLE, HRS_UNUSED, HRS_ASSIGNED,
  HRS_TIME_OFF, HRS_AUTHORIZED_PROJECTS, HRS_OVERBURN, HRS_UTIL_DENOM,
  PRACTICE, REGION, RELATIONSHIP, EMPLOYEE_TYPE, JOB_LEVEL, COUNTRY, OFFICE, REPORTS_TO,
  STATUS_CATEGORY, PROJECT_LIST, BILLABILITY_PCT, AVAILABILITY_PCT, ASSIGNED_PCT,
  FLAG_NO_ACTIVE_PROJECT, FLAG_TIME_OFF, FLAG_OVERBURN, FLAG_UNDER_TARGET
from PRD_BI_SUITE.CONS_BI.CONS_WEEKLY_AVAILABILITY;

create or replace view PRD_BI_SUITE.STAFFING_APP.PROJECT_TIME as
select
  PROJECT_ID, DATE, CONSULTANT_ID, CONSULTANT_NAME, CONSULTANT_COUNTRY, CONSULTANT_REGION,
  RELATIONSHIP, RESOURCE_TYPE, PRACTICE, EMPLOYEE_STATUS_CATEGORY,
  HRS_UTIL_DENOM, HRS_TIME_OFF, YEAR_ID, MONTH_ID, QUARTER_ID, WEEK_FIRST_DAY_AT,
  ACTUAL_BILLABLE_HOURS, ACTUAL_NON_BILLABLE_HOURS, ACTUAL_TOTAL_HOURS,
  ALLOCATED_BILLABLE_HOURS, ALLOCATED_NON_BILLABLE_HOURS, ALLOCATED_TOTAL_HOURS,
  PROJECT_NAME, PROJECT_STATUS, OPTY_STAGE, PROJECT_TYPE, CUSTOMER_NAME, INTERNAL_FLAG,
  PROJECT_TOTAL_HOURS
from PRD_BI_SUITE.CONS_BI.CONS_PROJECT_TIME;
-- (deliberately omitted: LABOR_COST, ACTUAL_TOTAL_COST, ALLOCATED_TOTAL_COST)

-- 4. Grants: warehouse + database + the new schema's views only
grant usage on warehouse TRANSFORMING            to role STAFFING_APP_RO;
grant usage on database  PRD_BI_SUITE            to role STAFFING_APP_RO;
grant usage on schema    PRD_BI_SUITE.STAFFING_APP to role STAFFING_APP_RO;
grant select on all views in schema PRD_BI_SUITE.STAFFING_APP to role STAFFING_APP_RO;
grant select on future views in schema PRD_BI_SUITE.STAFFING_APP to role STAFFING_APP_RO;

-- 5. Verify
show grants to role STAFFING_APP_RO;
desc user SVC_STAFFING_APP;   -- RSA_PUBLIC_KEY_FP should be populated
