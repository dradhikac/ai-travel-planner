/**
 * Trips API client methods for fetching saved trips and trip collections.
 * Aligned with Phase 2 data contracts in docs/phase2-3/data-contracts.md.
 */

import { apiClient } from "@/lib/api/client";
import type { TripResponse, TripSummaryItem } from "@/lib/types/trip";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validates the runtime shape of a trip response payload.
 */
export function validateTripResponse(data: unknown): TripResponse {
  if (!isRecord(data)) {
    throw new Error("Invalid trip response: Expected an object payload");
  }
  if (typeof data.id !== "string" || !data.id.trim()) {
    throw new Error("Invalid trip response: Missing or empty 'id' string");
  }
  if (!isRecord(data.request)) {
    throw new Error("Invalid trip response: Missing or invalid 'request' object");
  }
  if (!isRecord(data.itinerary)) {
    throw new Error(
      "Invalid trip response: Missing or invalid 'itinerary' object"
    );
  }
  if (!Array.isArray((data.itinerary as Record<string, unknown>).days)) {
    throw new Error(
      "Invalid trip response: Itinerary 'days' must be an array"
    );
  }
  if (typeof (data.itinerary as Record<string, unknown>).summary !== "string") {
    throw new Error(
      "Invalid trip response: Itinerary 'summary' must be a string"
    );
  }
  if (data.weather !== null && data.weather !== undefined && !isRecord(data.weather)) {
    throw new Error(
      "Invalid trip response: 'weather' must be an object or null"
    );
  }
  if (!Array.isArray(data.sources)) {
    throw new Error("Invalid trip response: 'sources' must be an array");
  }
  if (!Array.isArray(data.warnings)) {
    throw new Error("Invalid trip response: 'warnings' must be an array");
  }
  if (typeof data.created_at !== "string") {
    throw new Error("Invalid trip response: Missing or invalid 'created_at'");
  }

  return data as unknown as TripResponse;
}

/**
 * Validates the runtime shape of a trip list response payload.
 */
export function validateTripListResponse(data: unknown): TripSummaryItem[] {
  if (!Array.isArray(data)) {
    throw new Error("Invalid trip list response: Expected an array of trips");
  }
  for (const item of data) {
    if (!isRecord(item)) {
      throw new Error("Invalid trip list item: Expected an object");
    }
    if (typeof item.id !== "string") {
      throw new Error("Invalid trip list item: Missing 'id'");
    }
    if (typeof item.destination !== "string") {
      throw new Error("Invalid trip list item: Missing 'destination'");
    }
    if (typeof item.start_date !== "string") {
      throw new Error("Invalid trip list item: Missing 'start_date'");
    }
    if (typeof item.end_date !== "string") {
      throw new Error("Invalid trip list item: Missing 'end_date'");
    }
    if (typeof item.created_at !== "string") {
      throw new Error("Invalid trip list item: Missing 'created_at'");
    }
  }
  return data as unknown as TripSummaryItem[];
}

/**
 * Fetch a single trip by its UUID identifier.
 */
export async function getTrip(id: string): Promise<TripResponse> {
  if (!id || !id.trim()) {
    throw new Error("Trip ID is required");
  }
  const data = await apiClient<unknown>(`/api/trips/${encodeURIComponent(id.trim())}`);
  return validateTripResponse(data);
}

export interface ListTripsOptions {
  limit?: number;
  offset?: number;
}

/**
 * Fetch a list of recent trips with pagination.
 */
export async function listTrips(
  options: ListTripsOptions = {}
): Promise<TripSummaryItem[]> {
  const { limit = 10, offset = 0 } = options;
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const data = await apiClient<unknown>(`/api/trips?${query.toString()}`);
  return validateTripListResponse(data);
}
