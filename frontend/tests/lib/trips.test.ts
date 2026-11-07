import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getTrip,
  listTrips,
  validateTripResponse,
  validateTripListResponse,
} from "@/lib/api/trips";
import { ApiError } from "@/lib/api/client";

describe("Trips API Client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const validTripPayload = {
    id: "trip-12345",
    request: {
      origin: "Paris",
      destination: "Rome",
      start_date: "2026-07-01",
      end_date: "2026-07-05",
      party_size: 2,
    },
    itinerary: {
      summary: "5-day Roman holiday.",
      days: [],
    },
    weather: null,
    sources: [],
    warnings: [],
    created_at: "2026-06-20T10:00:00Z",
  };

  describe("validateTripResponse", () => {
    it("validates a compliant trip payload", () => {
      const result = validateTripResponse(validTripPayload);
      expect(result.id).toBe("trip-12345");
      expect(result.request.destination).toBe("Rome");
    });

    it("rejects non-object payload", () => {
      expect(() => validateTripResponse(null)).toThrow(
        "Expected an object payload"
      );
      expect(() => validateTripResponse("string")).toThrow(
        "Expected an object payload"
      );
    });

    it("rejects payload with missing id", () => {
      const invalid = { ...validTripPayload, id: "" };
      expect(() => validateTripResponse(invalid)).toThrow("Missing or empty 'id'");
    });

    it("rejects payload with invalid itinerary", () => {
      const invalid = { ...validTripPayload, itinerary: null };
      expect(() => validateTripResponse(invalid)).toThrow(
        "Missing or invalid 'itinerary'"
      );
    });
  });

  describe("validateTripListResponse", () => {
    it("validates array of summary items", () => {
      const items = [
        {
          id: "t1",
          destination: "Rome",
          start_date: "2026-07-01",
          end_date: "2026-07-05",
          created_at: "2026-06-20T10:00:00Z",
        },
      ];
      const result = validateTripListResponse(items);
      expect(result).toHaveLength(1);
      expect(result[0].destination).toBe("Rome");
    });

    it("rejects non-array response", () => {
      expect(() => validateTripListResponse({})).toThrow(
        "Expected an array of trips"
      );
    });
  });

  describe("getTrip", () => {
    it("successfully fetches trip by id", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => validTripPayload,
      });
      vi.stubGlobal("fetch", mockFetch);

      const trip = await getTrip("trip-12345");
      expect(trip.id).toBe("trip-12345");
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/trips/trip-12345"),
        expect.any(Object)
      );
    });

    it("throws ApiError with status 404 when trip is not found", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: "Not Found",
        json: async () => ({
          error: {
            code: "trip_not_found",
            message: "Trip with id 'invalid-id' was not found.",
          },
        }),
      });
      vi.stubGlobal("fetch", mockFetch);

      await expect(getTrip("invalid-id")).rejects.toThrowError(ApiError);
    });

    it("throws Error if id is empty", async () => {
      await expect(getTrip("")).rejects.toThrow("Trip ID is required");
    });
  });

  describe("listTrips", () => {
    it("fetches trips list with query parameters", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [
          {
            id: "t1",
            destination: "Tokyo",
            start_date: "2026-08-01",
            end_date: "2026-08-05",
            created_at: "2026-07-20T10:00:00Z",
          },
        ],
      });
      vi.stubGlobal("fetch", mockFetch);

      const trips = await listTrips({ limit: 5, offset: 10 });
      expect(trips).toHaveLength(1);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/trips?limit=5&offset=10"),
        expect.any(Object)
      );
    });
  });
});
