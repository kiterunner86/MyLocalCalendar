# MyLocalCalendar

A trusted, continuously updated city-event calendar for Dubai — sourced from
sites that publish `schema.org/Event` markup, ticketing platforms, and
official sources, normalized into one canonical database, deduplicated, and
monitored for changes.

This is the **skeleton** version: the architecture is wired end-to-end
(database → ingestion → frontend), but with minimal data and no
duplicate-detection, categorization, or notifications yet. The plan is to
get this skeleton running, verify each piece works, then improve
incrementally — see `/docs` in the project for the full feasibility and
architecture notes this was built from.

## Structure

```
apps/web/          Next.js frontend (reads events from Supabase)
supabase/migrations/  Database schema (Postgres + PostGIS via Supabase)
ingestion/          Python ingestion scripts (schema.org/Event parser to start)
.github/workflows/  Scheduled ingestion job (GitHub Actions cron — free tier)
```

## Stack (test-run / cheapest tier)

- **Supabase** — Postgres + PostGIS, Auth, Storage, all on the free tier
- **Vercel** — frontend hosting, free tier
- **GitHub Actions** — scheduled ingestion runs, no dedicated server needed yet
- **Anthropic API** — added later, once AI extraction is needed for messier sources

See the scale-up notes in the project's feasibility doc for what gets swapped
in as traffic grows (dedicated worker host, paid maps/geocoding, Elasticsearch,
etc.) — nothing here needs a rewrite to get there.

## Setup

### 1. Supabase

1. In your Supabase project, open the SQL editor and run
   `supabase/migrations/0001_init.sql`. This creates all tables, the PostGIS
   extension, and row-level security policies.
2. Copy your Project URL and `anon` public key from
   **Project Settings → API**.
3. Copy the `service_role` key from the same page — keep this one secret,
   it's only used server-side by the ingestion script.

### 2. Environment variables

Copy `.env.example` to `.env.local` inside `apps/web/` (for the frontend)
and to `.env` at the repo root (for local ingestion runs), and fill in the
values from step 1.

### 3. Frontend

```bash
cd apps/web
npm install
npm run dev
```

Deploy to Vercel by connecting this repo and setting the two
`NEXT_PUBLIC_SUPABASE_*` environment variables in the Vercel project
settings.

### 4. Ingestion

Edit `ingestion/sources.json` with real source URLs that publish
`schema.org/Event` JSON-LD markup, then run locally to test:

```bash
cd ingestion
pip install -r requirements.txt
export NEXT_PUBLIC_SUPABASE_URL=...
export SUPABASE_SERVICE_ROLE_KEY=...
python schema_org_ingest.py
```

For the scheduled version, add `SUPABASE_URL` and
`SUPABASE_SERVICE_ROLE_KEY` as **repository secrets**
(Settings → Secrets and variables → Actions) so
`.github/workflows/ingest.yml` can run it daily.

## What's deliberately not built yet

- Duplicate detection / canonical event matching across sources
- AI-assisted extraction for non-schema.org sources
- Categorization beyond a placeholder "other"
- Change detection and notifications
- Map/radius search UI
- Admin dashboard

These come after the skeleton is confirmed working end-to-end with at least
one real source.
