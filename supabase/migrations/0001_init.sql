-- MyLocalCalendar — initial schema
-- Modeled on: event series/event -> occurrences -> source observations,
-- kept separate from occurrences so recurring/multi-day events don't
-- become duplicate cards. See project docs for the full data-model rationale.

create extension if not exists postgis;
create extension if not exists pgcrypto; -- for gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Sources: every ingestion connector is registered here with health metadata.
-- ---------------------------------------------------------------------------
create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  base_url text not null,
  source_type text not null, -- 'schema_org' | 'api' | 'manual_submission' | 'ticketing_platform' | ...
  city text not null default 'Dubai',
  reliability_score numeric default 0.5,
  last_successful_crawl timestamptz,
  last_failed_crawl timestamptz,
  failure_count integer not null default 0,
  next_check_due timestamptz default now(), -- adaptive scheduling cursor
  check_interval_minutes integer not null default 1440, -- starts daily, adjusted over time
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Venues: normalized so the same physical place isn't duplicated per source.
-- ---------------------------------------------------------------------------
create table if not exists venues (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  address text,
  city text not null default 'Dubai',
  location geography(Point, 4326), -- lon/lat, for radius search
  created_at timestamptz not null default now()
);

create index if not exists venues_location_idx on venues using gist (location);

-- ---------------------------------------------------------------------------
-- Organizers
-- ---------------------------------------------------------------------------
create table if not exists organizers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Events: the canonical series/concept. One event can have many occurrences.
-- ---------------------------------------------------------------------------
create table if not exists events (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  category text not null default 'other',
  subcategories text[] default '{}',
  organizer_id uuid references organizers(id),
  venue_id uuid references venues(id),
  image_reference text,
  booking_url text,
  source_url text,
  source_id uuid references sources(id),
  confidence_score numeric default 0.5,
  status text not null default 'discovered',
  -- discovered | extracted | normalized | matched | validated | published |
  -- updated | postponed | cancelled | completed | stale
  first_seen_at timestamptz not null default now(),
  last_verified_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists events_category_idx on events(category);
create index if not exists events_status_idx on events(status);

-- ---------------------------------------------------------------------------
-- Occurrences: actual date/time instances of an event.
-- ---------------------------------------------------------------------------
create table if not exists event_occurrences (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references events(id) on delete cascade,
  start_datetime timestamptz not null,
  end_datetime timestamptz,
  timezone text not null default 'Asia/Dubai',
  status text not null default 'scheduled',
  -- scheduled | updated | postponed | cancelled | sold_out | completed | unknown
  price_min numeric,
  price_max numeric,
  is_free boolean default false,
  created_at timestamptz not null default now()
);

create index if not exists occurrences_start_idx on event_occurrences(start_datetime);
create index if not exists occurrences_event_idx on event_occurrences(event_id);

-- ---------------------------------------------------------------------------
-- Source observations: raw evidence per source, kept even after dedup so we
-- can tell which source is freshest / independently confirms a field.
-- ---------------------------------------------------------------------------
create table if not exists source_observations (
  id uuid primary key default gen_random_uuid(),
  event_id uuid references events(id) on delete cascade,
  source_id uuid not null references sources(id),
  raw_data jsonb not null,
  extraction_method text not null default 'schema_org', -- 'schema_org' | 'ai_extraction' | 'api' | 'manual'
  fetched_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Change history: auditable record of material field changes.
-- ---------------------------------------------------------------------------
create table if not exists event_change_history (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references events(id) on delete cascade,
  field_changed text not null,
  old_value text,
  new_value text,
  source_id uuid references sources(id),
  detected_at timestamptz not null default now(),
  confidence numeric default 1.0
);

-- ---------------------------------------------------------------------------
-- Saved events: per-user, backed by Supabase Auth's auth.users.
-- ---------------------------------------------------------------------------
create table if not exists saved_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  event_id uuid not null references events(id) on delete cascade,
  notify_on_change boolean not null default true,
  created_at timestamptz not null default now(),
  unique (user_id, event_id)
);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table events enable row level security;
alter table event_occurrences enable row level security;
alter table venues enable row level security;
alter table organizers enable row level security;
alter table saved_events enable row level security;

-- Published events and their occurrences/venues/organizers are public read.
create policy "public read published events" on events
  for select using (status not in ('discovered', 'extracted'));

create policy "public read occurrences" on event_occurrences
  for select using (true);

create policy "public read venues" on venues
  for select using (true);

create policy "public read organizers" on organizers
  for select using (true);

-- Users can only see/manage their own saved events.
create policy "users manage own saved events" on saved_events
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Writes to events/sources/observations happen via the service role key
-- (ingestion scripts), which bypasses RLS — no public write policies needed.
