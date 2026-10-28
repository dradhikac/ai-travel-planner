import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TripDetailsView } from "@/app/trips/[id]/page";
import type { TripResponse } from "@/lib/types/trip";

describe("TripDetailsView Component", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const mockLiveTrip: TripResponse = {
    id: "trip-uuid-1",
    request: {
      origin: "San Francisco",
      destination: "Tokyo",
      start_date: "2026-06-15",
      end_date: "2026-06-17",
      party_size: 2,
      budget_amount: 3000,
      currency: "USD",
      interests: ["culture", "food"],
      pace: "balanced",
    },
    itinerary: {
      summary: "A balanced 3-day cultural and culinary exploration of Tokyo.",
      days: [
        {
          day_number: 1,
          date: "2026-06-15",
          items: [
            {
              title: "Senso-ji Temple",
              time_of_day: "morning",
              description: "Explore Tokyo's oldest Buddhist temple in Asakusa.",
              provenance: "retrieved",
              source_ref: "Open-Meteo & Geo-DB",
              note: "Arrive early to avoid large crowds.",
              cost_estimate: "Free admission",
            },
            {
              title: "Tsukiji Outer Market Food Tour",
              time_of_day: "afternoon",
              description:
                "Taste fresh seafood and street snacks along the market lanes.",
              provenance: "generated_suggestion",
              cost_estimate: "$20 - $40 per person",
            },
            {
              title: "Shibuya Crossing",
              time_of_day: "evening",
              description: "Experience the world's busiest pedestrian crossing.",
              provenance: "estimate",
              cost_estimate: "Approx. $35",
            },
          ],
        },
        {
          day_number: 2,
          date: "2026-06-16",
          items: [
            {
              title: "Meiji Shrine",
              time_of_day: "morning",
              description: "Peaceful morning walk through shrine grounds.",
              provenance: "unknown",
            },
          ],
        },
      ],
    },
    weather: {
      location: "Tokyo, Japan",
      days: [
        {
          date: "2026-06-15",
          temp_min_c: 18.2,
          temp_max_c: 24.5,
          precipitation_probability_pct: 20,
          precipitation_sum_mm: 0.5,
          weather_code: 1,
          condition_description: "Partly cloudy",
        },
      ],
      units: {
        temperature: "celsius",
        precipitation: "mm",
      },
      source: {
        provider: "Open-Meteo",
        url: "https://open-meteo.com",
        attribution: "Weather data by Open-Meteo.com",
        fetched_at: "2026-06-10T12:00:00Z",
        data_origin: "live",
      },
      fetched_at: "2026-06-10T12:00:00Z",
      data_origin: "live",
      horizon_note: null,
    },
    sources: [
      {
        provider: "Open-Meteo",
        url: "https://open-meteo.com",
        attribution: "Weather data by Open-Meteo.com",
        fetched_at: "2026-06-10T12:00:00Z",
        data_origin: "live",
      },
    ],
    warnings: [],
    created_at: "2026-06-10T12:05:00Z",
  };

  it("renders loading state with role='status' and aria-live='polite' first", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(new Promise(() => {}))
    );

    render(<TripDetailsView tripId="trip-uuid-1" />);

    const loadingStatus = screen.getByRole("status");
    expect(loadingStatus).toBeInTheDocument();
    expect(loadingStatus).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText(/loading trip details/i)).toBeInTheDocument();
  });

  it("renders success state with trip summary, provenance labels, weather, source and fetched_at", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockLiveTrip,
      })
    );

    render(<TripDetailsView tripId="trip-uuid-1" />);

    // Wait for trip summary
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /San Francisco → Tokyo/i })
      ).toBeInTheDocument();
    });

    // Check party size, budget, interests
    expect(screen.getByText(/2 travelers/i)).toBeInTheDocument();
    expect(screen.getByText(/\$3,000/i)).toBeInTheDocument();
    expect(screen.getByText(/culture/i)).toBeInTheDocument();

    // Check non-booking disclaimer is present plainly
    expect(
      screen.getByText(/planning itinerary — not a booking/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no bookings, reservations, ticketing, or payment transactions have occurred/i)
    ).toBeInTheDocument();

    // Check weather forecast table and source info
    expect(screen.getByText(/Weather Forecast: Tokyo, Japan/i)).toBeInTheDocument();
    expect(screen.getByText(/Partly cloudy/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open-Meteo" })).toBeInTheDocument();
    expect(
      screen.getByText(/Weather data by Open-Meteo\.com/i)
    ).toBeInTheDocument();

    // Check fetched_at formatted with timezone
    expect(screen.getByText(/Fetched:/i)).toBeInTheDocument();

    // Check provenance labels (Retrieved / Suggestion / Estimate / Unknown)
    expect(screen.getByText(/\[Retrieved\]/i)).toBeInTheDocument();
    expect(screen.getByText(/\[Suggestion\]/i)).toBeInTheDocument();
    expect(screen.getByText(/\[Estimate\]/i)).toBeInTheDocument();
    expect(screen.getByText(/\[Unknown\]/i)).toBeInTheDocument();
  });

  it("renders clearly visible 'Mock data' badge when weather data_origin is mock", async () => {
    const mockDataTrip: TripResponse = {
      ...mockLiveTrip,
      weather: {
        ...mockLiveTrip.weather!,
        data_origin: "mock",
        source: {
          ...mockLiveTrip.weather!.source,
          data_origin: "mock",
        },
      },
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockDataTrip,
      })
    );

    render(<TripDetailsView tripId="trip-uuid-1" />);

    await waitFor(() => {
      expect(screen.getByTestId("mock-data-badge")).toBeInTheDocument();
    });
    expect(screen.getByTestId("mock-data-badge")).toHaveTextContent("Mock data");
  });

  it("renders weather_unavailable explanation when weather is null", async () => {
    const nullWeatherTrip: TripResponse = {
      ...mockLiveTrip,
      weather: null,
      warnings: [
        "weather_unavailable: Weather forecast could not be retrieved; itinerary generated with seasonal estimates.",
      ],
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => nullWeatherTrip,
      })
    );

    render(<TripDetailsView tripId="trip-uuid-1" />);

    await waitFor(() => {
      expect(screen.getByText(/Forecast Unavailable/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("note")).toHaveTextContent(
      /Weather forecast could not be retrieved; itinerary generated with seasonal estimates/i
    );
  });

  it("renders 404 empty state with link to /plan when trip is not found", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: "Not Found",
        json: async () => ({
          error: {
            code: "trip_not_found",
            message: "Trip not found.",
          },
        }),
      })
    );

    render(<TripDetailsView tripId="missing-id" />);

    await waitFor(() => {
      expect(screen.getByTestId("trip-not-found-state")).toBeInTheDocument();
    });

    expect(screen.getByText(/Trip Not Found/i)).toBeInTheDocument();
    const planLink = screen.getByRole("link", { name: /Plan a New Trip/i });
    expect(planLink).toBeInTheDocument();
    expect(planLink).toHaveAttribute("href", "/plan");
  });

  it("renders error state with Retry button that re-triggers fetch on click", async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => ({
          error: {
            code: "internal_error",
            message: "Server encountered an error.",
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockLiveTrip,
      });

    vi.stubGlobal("fetch", mockFetch);

    render(<TripDetailsView tripId="trip-uuid-1" />);

    // 1. First fetch fails with error
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByText(/Server encountered an error/i)).toBeInTheDocument();

    const retryButton = screen.getByRole("button", { name: /Retry/i });
    expect(retryButton).toBeInTheDocument();

    // 2. Click retry
    await userEvent.click(retryButton);

    // 3. Second fetch succeeds
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /San Francisco → Tokyo/i })
      ).toBeInTheDocument();
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("renders backend unavailable message when network error occurs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
    );

    render(<TripDetailsView tripId="trip-uuid-1" />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/backend service is currently unreachable/i)
    ).toBeInTheDocument();
  });
});
