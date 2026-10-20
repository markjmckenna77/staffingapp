# Monday staffing refresh (GitHub Actions)

Every Monday at 7:00 AM Pacific, `.github/workflows/monday-refresh.yml` runs `pipeline/run.py`:

1. **Snowflake** (`fetch.py`): the eleven pulls from the old Claude runbook, read through the
   cost-free views in `PRD_BI_SUITE.STAFFING_APP` as the `SVC_STAFFING_APP` service user.
2. **Greenhouse**: `GET /api/recruiting` on the app (Internal reqs already excluded, pay
   language already scrubbed). If that fails it reuses last week's pull and says so.
3. **Build**: the same generators as before (`pipeline/src/`), byte-for-byte, with the week
   and month constants worked out from the date (`params.py`) instead of hand-edited.
4. **Checks**: no pay language, no standing exclusions, Alex Markow present, ~60 consultants,
   no visible Internal roles, sane page size. Any failure stops here and last week's page stays up.
5. **Publish**: archive last week's Meeting Agenda (`POST /api/agenda/archive`), then upload
   the page (`POST /api/dashboard`). No redeploy; the app serves the stored page.

The run's **Summary** tab shows the headline numbers and a "Needs a look" list. GitHub emails
you if a run fails.

## The only file you edit: `config.json`

Edit it on github.com (open the file, pencil icon, commit). The next run picks it up.

| key | what it does |
|---|---|
| `match` | Greenhouse job name -> `[client, role title]` of the demand line it staffs. Add one when the Summary lists a client requisition with no matching demand line. Salesforce renames role titles now and then; fix the right-hand side when that happens. |
| `manual_demand` | Roles you want on the page before they exist in NetSuite. Each drops off automatically once Snowflake carries a matching role for that client (`drop_when_role_matches`). |
| `hide_roles` | Extra roles to hide from Open Roles & Recruiting Activity (anything starting `Internal:` is always hidden). Optional `until` date. |
| `filled` | Hires to show under "Filled" for a given week (`week` = that Monday, YYYY-MM-DD). |

## Running it by hand

Actions tab -> **Monday staffing refresh** -> **Run workflow**. Leave *publish* unticked to
build and check only (download the page from the run's artifacts); tick it to put it live.

Locally: `pip install -r pipeline/requirements.txt`, set the same environment variables as the
workflow's secrets, then `python pipeline/run.py` (add `--publish` to upload).

## One-time setup

1. Make this repository **private** (Settings -> General -> Danger Zone -> Change visibility).
2. Have a Snowflake admin run `snowflake/pipeline_views.sql` (adds three views; no new grants).
3. Add the Actions secrets (Settings -> Secrets and variables -> Actions -> New repository secret):
   `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`,
   `SNOWFLAKE_PRIVATE_KEY` (copy each from the Vercel project's environment variables),
   `APP_URL` = `https://staffingapp-ivory.vercel.app`, and `IMPORT_TOKEN` (the same value as the
   Vercel `IMPORT_TOKEN`; if you don't have it, generate a new random string and set it in both).
4. Run the workflow by hand once with *publish* unticked and check the Summary.

## Files

- `run.py` - orchestration, date math, checks, upload, summary
- `fetch.py` - Snowflake queries (live, or replayed from saved results for testing)
- `src/` - the dashboard generators (unchanged from the Claude pipeline except that dates,
  matches and hides come from `params.py` / `config.json`)
- `seed/ats.json` - the Oct 13 2026 ATS export, used only if Greenhouse has never answered
- `state/`, `out/` - written by runs; not committed


## Oct 20 2026 changes (Mark)
- Runs Mondays at **3:00 AM Pacific** (crons 10:07 / 11:07 UTC; the gate picks the 3 AM one).
- Greenhouse: the app no longer drops jobs starting "Internal" at sync time (`GH_EXCLUDE_JOBS` unset);
  internal/SG&A requisitions are in the data and `hide_open_roles.py` keeps them off the page.
- Utilization Summary: this month + 3 forecast months (a month whose figure is under 60% of the
  previous one is tagged "bookings still filling in"); points and segments coloured on the Outlook's
  status bands against the 90% target; a **projected month close** from `seed/org_history.json` +
  `state/org_history.json` (every run appends its org-wide figures; the projection is the median move
  between today's day-of-month and month end over earlier months with history).
- 8 Week Outlook: practice headers fold; "Include contractors" toggle (off by default) shows active
  contractors with bookings (new `contractors` pull; `OUTLOOK_CONTRACTORS` in outlook_data.py).
  Capacity vs. Need, suggestions and the under-target cohort stay employees-only; the cohort is
  judged on this month + 2 (`COHORT_MONTHS`).
- Open Roles & Recruiting: hiring manager / type (FTE or Contractor) / recruiter / target start line,
  the full latest status note (date kept) with earlier notes behind a disclosure, and
  "Considering filling this role with existing staff. Not recruiting externally yet." for roles with no requisition.
- Allocation vs Actual: account rows open the consultants on the account (who did not bill what they
  were allocated); consultant rows open the accounts they did not bill to (`S3_PAIRS`).
- The "Generated ..." footer is gone (an empty `<footer class="dash-footer">` stays as the anchor the
  utilization and collapsible-section passes insert before).
