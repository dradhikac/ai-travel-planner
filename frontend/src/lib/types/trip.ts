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

export type DurationBasis = "provider" | "heuristic" | "unknown";

export type CostStatus = "unknown" | "estimate" | "retrieved";

export interface ActivityLocation {
  name: string;
  latitude?: number | null;
  longitude?: number | null;
  source_ref?: string | null;
}

export interface DurationEstimate {
  min_minutes?: number | null;
  max_minutes?: number | null;
  basis: DurationBasis;
}

export interface ItineraryActivity {
  id: string;
  title: string;
  description?: string | null;
  time_of_day?: TimeOfDay | string | null;
  interest_tags?: string[];
  location?: ActivityLocation | null;
  duration_estimate?: DurationEstimate | null;
  source_refs?: string[];
  provenance: Provenance;
  cost_status?: CostStatus;
  cost_note?: string | null;
  uncertainty_notes?: string[];
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
  activities?: ItineraryActivity[];
  items?: ItineraryItem[];
  uncertainty_notes?: string[];
}

export interface Itinerary {
  schema_version?: number;
  days: ItineraryDay[];
  summary: string;
  sources?: SourceInfo[];
  warnings?: string[];
}

export interface ToolActivity {
  tool_label: string;
  status: string;
  source: string;
  fetched_at?: string | null;
  data_origin: "live" | "mock" | "fallback" | "none" | string;
  explanation: string;
}

export type AssistantRunStatus =
  | "needs_clarification"
  | "clarification_required"
  | "completed"
  | "partial"
  | "failed";

export interface AssistantClarification {
  field?: string;
  question: string;
}

export interface AssistantPlanRequest {
  message: string;
  known_fields?: Record<string, unknown>;
  save?: boolean;
}

export interface AssistantPlanResponse {
  status: AssistantRunStatus;
  request_id: string;
  trip?: TripResponse | null;
  clarification_question?: string | null;
  clarification?: AssistantClarification | null;
  missing_fields?: string[];
  known_fields?: Record<string, unknown>;
  tool_activity?: ToolActivity[];
  warnings?: string[];
  message?: string | null;
}

export interface TripResponse {
  id: string;
  request: TripRequest;
  itinerary: Itinerary;
  weather: WeatherSummary | null;
  sources: SourceInfo[];
  tool_activity?: ToolActivity[];
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
