/**
 * TypeScript data contracts and models for travel research, planning,
 * itineraries, and external provider summaries.
 * Aligned with Phase 2 specifications in docs/phase2-3/data-contracts.md.
 */

export type Provenance =
  | "retrieved"
  | "generated_suggestion"
  | "estimate"
  | "unknown";

export type PacePreference = "relaxed" | "balanced" | "packed";

export type TimeOfDay = "morning" | "afternoon" | "evening";

export interface TripRequest {
  origin: string;
  destination: string;
  start_date: string;
  end_date: string;
  party_size: number;
  budget_amount?: number | null;
  currency?: string | null;
  interests?: string[];
  pace?: PacePreference;
}

export interface SourceInfo {
  provider: string;
  url: string;
  attribution: string;
  fetched_at: string;
  data_origin: "live" | "mock";
}

export interface WeatherDay {
  date: string;
  temp_min_c: number;
  temp_max_c: number;
  precipitation_probability_pct: number;
  precipitation_sum_mm: number;
  weather_code: number;
  condition_description: string;
}

export interface WeatherSummary {
  location: string;
  days: WeatherDay[];
  units?: Record<string, string>;
  source: SourceInfo;
  fetched_at: string;
  data_origin: "live" | "mock";
  horizon_note?: string | null;
}

export interface ItineraryItem {
  title: string;
  time_of_day: TimeOfDay;
  description: string;
  provenance: Provenance;
  source_ref?: string | null;
  note?: string | null;
  cost_estimate?: string | null;
}

export interface ItineraryDay {
  day_number: number;
  date: string;
  items: ItineraryItem[];
}

export interface Itinerary {
  days: ItineraryDay[];
  summary: string;
  warnings?: string[];
}

export interface TripResponse {
  id: string;
  request: TripRequest;
  itinerary: Itinerary;
  weather: WeatherSummary | null;
  sources: SourceInfo[];
  warnings: string[];
  created_at: string;
}

export interface TripSummaryItem {
  id: string;
  destination: string;
  start_date: string;
  end_date: string;
  created_at: string;
}
