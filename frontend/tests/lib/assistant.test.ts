import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { planWithAssistant, validateAssistantPlanResponse } from "@/lib/api/assistant";

describe("Assistant API Client & Response Validator", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const sampleCompletedPayload = {
    status: "completed",
    request_id: "req-test-123",
    trip: {
      id: "trip-uuid-1",
      request: {
        origin: "London",
        destination: "Rome",
        start_date: "2026-09-01",
        end_date: "2026-09-04",
        party_size: 2,
        pace: "balanced",
      },
      itinerary: {
        summary: "3 days exploring classical Rome.",
        days: [
          {
            day_number: 1,
            date: "2026-09-01",
            items: [
              {
                title: "Colosseum Tour",
                time_of_day: "morning",
                description: "Ancient amphitheatre visit.",
                provenance: "retrieved",
              },
            ],
          },
        ],
      },
      weather: {
        location: "Rome, Italy",
        days: [],
        source: {
          provider: "Open-Meteo",
          url: "https://open-meteo.com",
          attribution: "Weather data by Open-Meteo.com",
          fetched_at: "2026-08-01T12:00:00Z",
          data_origin: "live",
        },
        fetched_at: "2026-08-01T12:00:00Z",
        data_origin: "live",
      },
      sources: [],
      warnings: [],
      created_at: "2026-08-01T12:00:00Z",
    },
    tool_activity: [
      {
        tool_label: "Destination Geocoding",
        status: "ok",
        source: "https://geocoding-api.open-meteo.com/v1/search",
        fetched_at: "2026-08-01T12:00:00Z",
        data_origin: "live",
        explanation: "Resolved coordinates for Rome (41.89, 12.51)",
      },
    ],
    warnings: [],
  };

  it("planWithAssistant invokes /api/agent/plan and validates completed response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => sampleCompletedPayload,
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await planWithAssistant("Plan a trip to Rome", { origin: "London" }, false);

    expect(result.status).toBe("completed");
    expect(result.request_id).toBe("req-test-123");
    expect(result.trip?.request.destination).toBe("Rome");
    expect(result.tool_activity).toHaveLength(1);
    expect(result.tool_activity?.[0].tool_label).toBe("Destination Geocoding");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = fetchMock.mock.calls[0][0];
    expect(calledUrl).toContain("/api/agent/plan");
    const calledOptions = fetchMock.mock.calls[0][1];
    expect(calledOptions.method).toBe("POST");
    const parsedBody = JSON.parse(calledOptions.body);
    expect(parsedBody.message).toBe("Plan a trip to Rome");
    expect(parsedBody.known_fields).toEqual({ origin: "London" });
    expect(parsedBody.save).toBe(false);
  });

  it("planWithAssistant appends ?save=true when save argument is true", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => sampleCompletedPayload,
    });
    vi.stubGlobal("fetch", fetchMock);

    await planWithAssistant("Plan a trip to Rome", {}, true);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = fetchMock.mock.calls[0][0];
    expect(calledUrl).toContain("/api/agent/plan?save=true");
    const parsedBody = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(parsedBody.save).toBe(true);
  });

  it("planWithAssistant rejects empty or whitespace-only messages without fetching", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(planWithAssistant("")).rejects.toThrow(/Message is required/i);
    await expect(planWithAssistant("   ")).rejects.toThrow(/Message is required/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("validateAssistantPlanResponse normalizes clarification_required to needs_clarification", () => {
    const payload = {
      status: "clarification_required",
      request_id: "req-clarify-1",
      clarification: {
        field: "start_date",
        question: "When would you like to depart?",
      },
      missing_fields: ["start_date"],
      known_fields: { destination: "Paris" },
    };

    const res = validateAssistantPlanResponse(payload);
    expect(res.status).toBe("needs_clarification");
    expect(res.clarification_question).toBe("When would you like to depart?");
    expect(res.missing_fields).toEqual(["start_date"]);
    expect(res.known_fields).toEqual({ destination: "Paris" });
  });

  it("validateAssistantPlanResponse validates partial status with warnings", () => {
    const payload = {
      status: "partial",
      request_id: "req-part-2",
      trip: sampleCompletedPayload.trip,
      warnings: ["weather_unavailable: Weather API timed out"],
    };

    const res = validateAssistantPlanResponse(payload);
    expect(res.status).toBe("partial");
    expect(res.warnings).toContain("weather_unavailable: Weather API timed out");
  });

  it("validateAssistantPlanResponse validates failed status with error message", () => {
    const payload = {
      status: "failed",
      request_id: "req-fail-3",
      message: "Destination 'Atlantis' was not recognized by geocoding provider.",
      tool_activity: [
        {
          tool_label: "Destination Geocoding",
          status: "empty",
          source: "https://geocoding-api.open-meteo.com",
          data_origin: "live",
          explanation: "No coordinates found for Atlantis",
        },
      ],
    };

    const res = validateAssistantPlanResponse(payload);
    expect(res.status).toBe("failed");
    expect(res.message).toContain("Atlantis");
    expect(res.tool_activity?.[0].status).toBe("empty");
  });

  it("validateAssistantPlanResponse throws on invalid or unrecognized status", () => {
    expect(() => validateAssistantPlanResponse(null)).toThrow(/Expected an object/i);
    expect(() => validateAssistantPlanResponse({})).toThrow(/Unknown execution status/i);
    expect(() => validateAssistantPlanResponse({ status: "invalid_status" })).toThrow(
      /Unknown execution status 'invalid_status'/i
    );
  });
});
