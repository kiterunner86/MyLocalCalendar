import { supabase } from "@/lib/supabaseClient";

// This page reads live event data from Supabase. Force it to render per
// request instead of being statically prerendered at build time — the
// build sandbox may not have a network path to Supabase, and event data
// changes constantly anyway, so a build-time snapshot is the wrong model.
export const dynamic = "force-dynamic";

type Occurrence = {
  id: string;
  start_datetime: string;
  is_free: boolean;
  price_min: number | null;
};

type EventRow = {
  id: string;
  title: string;
  category: string;
  source_url: string | null;
  booking_url: string | null;
  venues: { name: string; city: string } | null;
  event_occurrences: Occurrence[];
};

async function getUpcomingEvents(): Promise<EventRow[]> {
  const { data, error } = await supabase
    .from("events")
    .select(
      "id, title, category, source_url, booking_url, venues(name, city), event_occurrences(id, start_datetime, is_free, price_min)"
    )
    .eq("status", "published")
    .order("first_seen_at", { ascending: false })
    .limit(50);

  if (error) {
    console.error("Failed to load events:", error.message);
    return [];
  }
  return (data as unknown as EventRow[]) ?? [];
}

export default async function HomePage() {
  const events = await getUpcomingEvents();

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1rem" }}>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "0.25rem" }}>MyLocalCalendar</h1>
      <p style={{ color: "#666", marginBottom: "2rem" }}>
        What&apos;s happening in Dubai, verified and sourced.
      </p>

      {events.length === 0 && (
        <p style={{ color: "#888" }}>
          No published events yet — this is the skeleton UI. Once Supabase is
          connected and an ingestion source has run, events will show up
          here.
        </p>
      )}

      <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: "1rem" }}>
        {events.map((event) => (
          <li
            key={event.id}
            style={{
              border: "1px solid #e5e5e5",
              borderRadius: 8,
              padding: "1rem",
              background: "#fff",
            }}
          >
            <div style={{ fontSize: "0.75rem", color: "#888", textTransform: "uppercase" }}>
              {event.category}
            </div>
            <h2 style={{ fontSize: "1.1rem", margin: "0.25rem 0" }}>{event.title}</h2>
            {event.venues && (
              <div style={{ fontSize: "0.9rem", color: "#555" }}>{event.venues.name}</div>
            )}
            {event.event_occurrences?.[0] && (
              <div style={{ fontSize: "0.9rem", color: "#555" }}>
                {new Date(event.event_occurrences[0].start_datetime).toLocaleString("en-AE", {
                  timeZone: "Asia/Dubai",
                })}
              </div>
            )}
            {event.source_url && (
              <a
                href={event.source_url}
                target="_blank"
                rel="noreferrer"
                style={{ fontSize: "0.85rem", color: "#2563eb" }}
              >
                View source
              </a>
            )}
          </li>
        ))}
      </ul>
    </main>
  );
}
