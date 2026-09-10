import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  // Don't throw here: this module is imported at build time (Next.js
  // "collecting page data" step evaluates it even for a force-dynamic
  // page) as well as at request time. Throwing during the build step
  // takes down the entire deployment with an opaque error. Log loudly
  // instead and let any actual query fail at request time, where it's
  // caught and surfaced as "no events" rather than a hard crash.
  console.error(
    "Supabase env vars missing: NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY. " +
      "Set them in the Vercel project's Environment Variables (Production + Preview)."
  );
}

// This client only ever uses the public anon key and is safe to use
// in browser code. Writes from the app go through RLS-protected tables
// (e.g. saved_events); ingestion writes use the service role key instead,
// server-side only — see /ingestion.
export const supabase = createClient(
  supabaseUrl || "https://placeholder.supabase.co",
  supabaseAnonKey || "placeholder-anon-key"
);
