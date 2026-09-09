import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

// This client only ever uses the public anon key and is safe to use
// in browser code. Writes from the app go through RLS-protected tables
// (e.g. saved_events); ingestion writes use the service role key instead,
// server-side only — see /ingestion.
export const supabase = createClient(supabaseUrl, supabaseAnonKey);
