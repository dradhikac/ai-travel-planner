import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AssistantPage from "@/app/assistant/page";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
}));

describe("AssistantPage Component", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockPush.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const sampleCompletedPayload = {
    status: "completed",
    request_id: "req-comp-42",
    trip: {
      id: "trip-uuid-42",
      request: {
        origin: "London",
        destination: "Rome",
        start_date: "2026-09-01",
        end_date: "2026-09-04",
        party_size: 2,
        pace: "balanced",
      },
      itinerary: {
        summary: "A 3-day exploration of classical Rome.",
        days: [
          {
            day_number: 1,
            date: "2026-09-01",
            items: [
              {
                title: "Colosseum Guided Visit",
                time_of_day: "morning",
                description: "Tour of the ancient Flavian amphitheatre.",
                provenance: "retrieved",
                source_ref: "Rome Cultural Directory",
              },
            ],
          },
        ],
      },
      weather: {
        location: "Rome, Italy",
        days: [
          {
            date: "2026-09-01",
            temp_min_c: 19,
            temp_max_c: 28,
            precipitation_probability_pct: 10,
            precipitation_sum_mm: 0,
            weather_code: 1,
            condition_description: "Clear and sunny",
          },
        ],
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
      sources: [
        {
          provider: "Open-Meteo",
          url: "https://open-meteo.com",
          attribution: "Weather data by Open-Meteo.com",
          fetched_at: "2026-08-01T12:00:00Z",
          data_origin: "live",
        },
      ],
      warnings: [],
      created_at: "2026-08-01T12:00:00Z",
    },
    tool_activity: [
      {
        tool_label: "Destination Geocoding",
        status: "ok",
        source: "https://geocoding-api.open-meteo.com/v1/search?name=Rome",
        fetched_at: "2026-08-01T12:00:00Z",
        data_origin: "live",
        explanation: "Located coordinates for Rome (41.89, 12.51)",
      },
    ],
    warnings: [],
  };

  it("renders initial form with character counter and character limit enforcement", async () => {
    const user = userEvent.setup();
    render(<AssistantPage />);

    expect(
      screen.getByRole("heading", { name: /Travel Planning Assistant/i })
    ).toBeInTheDocument();

    const textarea = screen.getByLabelText(/What kind of trip would you like to plan\?/i);
    expect(textarea).toBeInTheDocument();
    expect(textarea).toHaveAttribute("maxlength", "2000");

    const counter = screen.getByTestId("character-counter");
    expect(counter).toHaveTextContent("0 / 2000 characters");

    await user.type(textarea, "Trip to Kyoto");
    expect(counter).toHaveTextContent("13 / 2000 characters");
  });

  it("renders clarification question and ONLY inputs for missing fields", async () => {
    const user = userEvent.setup();

    const clarificationPayload = {
      status: "needs_clarification",
      request_id: "req-clarify-99",
      clarification_question: "What dates are you planning to visit Rome?",
      missing_fields: ["start_date", "end_date"],
      known_fields: { destination: "Rome", party_size: 2 },
      tool_activity: [
        {
          tool_label: "Destination Geocoding",
          status: "ok",
          source: "https://geocoding-api.open-meteo.com",
          fetched_at: "2026-08-01T12:00:00Z",
          data_origin: "live",
          explanation: "Geocoded Rome coordinates",
        },
      ],
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => clarificationPayload,
      })
    );

    render(<AssistantPage />);

    const textarea = screen.getByLabelText(/What kind of trip would you like to plan\?/i);
    await user.type(textarea, "Plan a trip to Rome for 2 people");

    const submitBtn = screen.getByRole("button", { name: /Plan with Assistant/i });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId("clarification-container")).toBeInTheDocument();
    });

    expect(
      screen.getByText("What dates are you planning to visit Rome?")
    ).toBeInTheDocument();

    // start_date and end_date inputs must be present
    expect(screen.getByLabelText(/Start Date \*/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/End Date \*/i)).toBeInTheDocument();

    // destination and origin must NOT be present since they were not in missing_fields
    expect(screen.queryByLabelText(/Destination \*/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Departure City \(Origin\) \*/i)).not.toBeInTheDocument();

    // Focus moved to clarification heading
    const clarificationHeading = screen.getByRole("heading", {
      name: "What dates are you planning to visit Rome?",
    });
    expect(clarificationHeading).toHaveFocus();
  });

  it("clarification loop accumulates known_fields and resubmits to assistant", async () => {
    const user = userEvent.setup();

    const clarificationPayload = {
      status: "needs_clarification",
      request_id: "req-clarify-turn-1",
      clarification_question: "Where are you departing from?",
      missing_fields: ["origin"],
      known_fields: { destination: "Rome", start_date: "2026-09-01", end_date: "2026-09-04" },
    };

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => clarificationPayload,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => sampleCompletedPayload,
      });

    vi.stubGlobal("fetch", fetchMock);

    render(<AssistantPage />);

    // 1. Initial submit
    const textarea = screen.getByLabelText(/What kind of trip would you like to plan\?/i);
    await user.type(textarea, "Plan a trip to Rome in September");
    await user.click(screen.getByRole("button", { name: /Plan with Assistant/i }));

    // 2. Clarification prompt appears
    await waitFor(() => {
      expect(screen.getByLabelText(/Departure City \(Origin\) \*/i)).toBeInTheDocument();
    });

    const originInput = screen.getByLabelText(/Departure City \(Origin\) \*/i);
    await user.type(originInput, "London");

    // 3. Submit clarification
    const continueBtn = screen.getByRole("button", { name: /Submit Clarification & Continue/i });
    await user.click(continueBtn);

    // 4. Verify second request body contains accumulated origin
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    const secondCallBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(secondCallBody.known_fields.origin).toBe("London");

    // 5. Final completed result renders
    await waitFor(() => {
      expect(screen.getByTestId("assistant-results-view")).toBeInTheDocument();
    });
    expect(screen.getByText("Colosseum Guided Visit")).toBeInTheDocument();
  });

  it("renders completed status with itinerary, provenance badges, and tool activity", async () => {
    const user = userEvent.setup();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => sampleCompletedPayload,
      })
    );

    render(<AssistantPage />);

    const textarea = screen.getByLabelText(/What kind of trip would you like to plan\?/i);
    await user.type(textarea, "Complete trip to Rome");
    await user.click(screen.getByRole("button", { name: /Plan with Assistant/i }));

    await waitFor(() => {
      expect(screen.getByTestId("assistant-results-view")).toBeInTheDocument();
    });

    // Provenance badge
    expect(screen.getByText("[Retrieved]")).toBeInTheDocument();

    // Tool activity panel
    expect(screen.getByTestId("tool-activity-panel")).toBeInTheDocument();
    expect(screen.getByText("Destination Geocoding")).toBeInTheDocument();
    expect(screen.getByTestId("data-origin-live-badge")).toBeInTheDocument();

    // Focus moved to results heading
    const resultsHeading = screen.getByRole("heading", {
      name: /Your Proposed Itinerary/i,
    });
    expect(resultsHeading).toHaveFocus();
  });

  it("renders partial status with prominent warning notice explaining missing data", async () => {
    const user = userEvent.setup();

    const partialPayload = {
      ...sampleCompletedPayload,
      status: "partial",
      warnings: [
        "weather_unavailable: Weather forecast API timed out; generated with seasonal estimates.",
      ],
      trip: {
        ...sampleCompletedPayload.trip,
        weather: null,
        warnings: [
          "weather_unavailable: Weather forecast API timed out; generated with seasonal estimates.",
        ],
      },
      tool_activity: [
        {
          tool_label: "Weather Forecast",
          status: "timeout",
          source: "https://api.open-meteo.com/v1/forecast",
          fetched_at: "2026-08-01T12:00:00Z",
          data_origin: "none",
          explanation: "Weather service timed out after 3000ms",
        },
      ],
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => partialPayload,
      })
    );

    render(<AssistantPage />);

    const textarea = screen.getByLabelText(/What kind of trip would you like to plan\?/i);
    await user.type(textarea, "Trip with weather failure");
    await user.click(screen.getByRole("button", { name: /Plan with Assistant/i }));

    await waitFor(() => {
      expect(screen.getByTestId("partial-notice-banner")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Notice: Partial Itinerary Generated/i)
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/Weather forecast API timed out/i).length
    ).toBeGreaterThanOrEqual(1);

    // Tool activity shows timeout status
    expect(screen.getByText("Status: Timed out")).toBeInTheDocument();
  });

  it("renders failed status with clear safe message, retry, and rephrase actions", async () => {
    const user = userEvent.setup();

    const failedPayload = {
      status: "failed",
      request_id: "req-fail-001",
      message:
        "Destination 'Atlantis' could not be resolved by geocoding providers.",
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => failedPayload,
      })
    );

    render(<AssistantPage />);

    const textarea = screen.getByLabelText(/What kind of trip would you like to plan\?/i);
    await user.type(textarea, "Trip to Atlantis");
    await user.click(screen.getByRole("button", { name: /Plan with Assistant/i }));

    await waitFor(() => {
      expect(screen.getByTestId("assistant-failed-state")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/Destination 'Atlantis' could not be resolved/i)
    ).toBeInTheDocument();

    const rephraseBtn = screen.getByRole("button", { name: /Rephrase \/ Edit Query/i });
    expect(rephraseBtn).toBeInTheDocument();
    const retryBtn = screen.getByRole("button", { name: /^Retry$/i });
    expect(retryBtn).toBeInTheDocument();

    // Clicking rephrase resets to idle and focuses textarea
    await user.click(rephraseBtn);
    expect(textarea).toHaveFocus();
  });

  it("renders unreachable alert when backend service is down", async () => {
    const user = userEvent.setup();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
    );

    render(<AssistantPage />);

    const textarea = screen.getByLabelText(/What kind of trip would you like to plan\?/i);
    await user.type(textarea, "Trip to Rome");
    await user.click(screen.getByRole("button", { name: /Plan with Assistant/i }));

    await waitFor(() => {
      expect(screen.getByTestId("assistant-unreachable-state")).toBeInTheDocument();
    });

    expect(
      screen.getByText(/The backend assistant service is currently unreachable/i)
    ).toBeInTheDocument();
  });

  it("save button navigates to /trips/{id}", async () => {
    const user = userEvent.setup();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => sampleCompletedPayload,
      })
    );

    render(<AssistantPage />);

    const textarea = screen.getByLabelText(/What kind of trip would you like to plan\?/i);
    await user.type(textarea, "Trip to Rome");
    await user.click(screen.getByRole("button", { name: /Plan with Assistant/i }));

    await waitFor(() => {
      expect(screen.getByTestId("assistant-results-view")).toBeInTheDocument();
    });

    const saveBtns = screen.getAllByRole("button", { name: /Save this trip/i });
    expect(saveBtns.length).toBeGreaterThan(0);

    await user.click(saveBtns[0]);

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/trips/trip-uuid-42");
    });
  });
});
