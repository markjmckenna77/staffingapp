# Cleartelligence Staffing App

Web app for the Monday resource-management meeting: utilization, 8-week outlook, open roles,
allocation vs actual, action items. Replaces the weekly static dashboard with live Snowflake data,
Microsoft sign-in, and (phases 2-3) in-app staffing edits and scenario planning.

Stack: Next.js 16 (App Router) · Auth.js v5 with Microsoft Entra ID · snowflake-sdk · Vercel.

## Local setup

    cp .env.example .env.local   # fill in values
    npm install
    npm run dev                  # http://localhost:3000

## Environment variables

See `.env.example`. Three groups:

- **Auth.js / Entra**: `AUTH_SECRET`, `AUTH_MICROSOFT_ENTRA_ID_ID`, `AUTH_MICROSOFT_ENTRA_ID_SECRET`,
  `AUTH_MICROSOFT_ENTRA_ID_TENANT_ID`, `ALLOWED_EMAIL_DOMAINS`.
- **Snowflake**: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`,
  `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_PRIVATE_KEY` (PEM, `\n`-escaped),
  optional `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE`.

The app runs without Snowflake configured (sections show a "not configured" note), so the login
flow can be deployed and tested before the service account exists.

## Entra app registration

1. Azure portal → Microsoft Entra ID → App registrations → New registration.
   Name: `Cleartelligence Staffing App`. Supported account types: **this organizational directory only**.
2. Redirect URIs (Web):
   - `https://<vercel-production-domain>/api/auth/callback/microsoft-entra-id`
   - `https://<project>-*.vercel.app/api/auth/callback/microsoft-entra-id` is not supported by Entra
     (no wildcards), so add each preview domain you need, or test previews with the production URL.
   - `http://localhost:3000/api/auth/callback/microsoft-entra-id` for local dev.
3. Certificates & secrets → New client secret → copy into `AUTH_MICROSOFT_ENTRA_ID_SECRET`.
4. Overview → copy Application (client) ID and Directory (tenant) ID.
5. API permissions: `openid`, `profile`, `email`, `User.Read` (delegated). Grant admin consent.

## Snowflake service account

Run `snowflake/setup.sql` as ACCOUNTADMIN. It creates role `STAFFING_APP_RO`, service user
`SVC_STAFFING_APP` (key-pair auth, public key embedded), and a schema
`PRD_BI_SUITE.STAFFING_APP` of views over `CONS_BI` that omit every cost column. The role is
granted only those views, never the raw tables.

To rotate the key: `openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -out rsa_key.p8`,
`openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub`, put the public key body in
`alter user SVC_STAFFING_APP set rsa_public_key = '...'`, and the private key (newlines
escaped as `\n`) in `SNOWFLAKE_PRIVATE_KEY`.

## Data guardrails

Cost, salary, pay-rate, margin and revenue columns never reach the browser. Enforced twice:
by the Snowflake role's grants (views only, no cost columns), and by `lib/allowlist.ts` (per-table column allowlist plus banned
name patterns checked on every query). Adding a column is a reviewed change to that file.

## Deploy

Vercel project connected to this repo; `main` deploys to production, branches get preview URLs.
Set the environment variables in Vercel → Project → Settings → Environment Variables.

## Roadmap

1. Port the existing dashboard sections onto live data (this phase).
2. In-app staffing edits (assign/unassign/hours) persisted in Postgres, shown as pending overrides.
3. Scenario planning layered on the override engine.
4. On-demand refresh, per-practice views, Teams/email notifications.
