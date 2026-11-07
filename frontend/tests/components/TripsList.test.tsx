import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TripsListPage from "@/app/trips/page";

describe("TripsListPage Component", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const mockTripsList = [
    {
      id: "trip-1",
      destination: "Kyoto, Japan",
      start_date: "2026-09-01",
      end_date: "2026-09-07",
      created_at: "2026-08-15T10:00:00Z",
    },
    {
      id: "trip-2",
      destination: "Barcelona, Spain",
      start_date: "2026-10-10",
      end_date: "2026-10-15",
      created_at: "2026-08-16T14:30:00Z",
    },
  ];

  it("renders loading state first with role='status' and aria-live='polite'", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(new Promise(() => {}))
    );

    render(<TripsListPage />);

    const loadingElement = screen.getByRole("status");
    expect(loadingElement).toBeInTheDocument();
    expect(loadingElement).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText(/loading saved trips/i)).toBeInTheDocument();
  });

  it("renders empty state with link to /plan when no trips exist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [],
      })
    );

    render(<TripsListPage />);

    await waitFor(() => {
      expect(screen.getByTestId("trips-empty-state")).toBeInTheDocument();
    });

    expect(screen.getByText(/no saved trips found/i)).toBeInTheDocument();
    const planLinks = screen.getAllByRole("link", {
      name: /Plan (a New|Your First) Trip/i,
    });
    expect(planLinks.length).toBeGreaterThan(0);
    expect(planLinks[0]).toHaveAttribute("href", "/plan");
  });

  it("renders non-empty trips list with links to /trips/{id}", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockTripsList,
      })
    );

    render(<TripsListPage />);

    await waitFor(() => {
      expect(screen.getByTestId("trips-list-container")).toBeInTheDocument();
    });

    expect(
      screen.getByRole("heading", { name: "Kyoto, Japan" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Barcelona, Spain" })
    ).toBeInTheDocument();

    const viewLinks = screen.getAllByRole("link", {
      name: /view itinerary/i,
    });
    expect(viewLinks).toHaveLength(2);
    expect(viewLinks[0]).toHaveAttribute("href", "/trips/trip-1");
    expect(viewLinks[1]).toHaveAttribute("href", "/trips/trip-2");
  });

  it("renders error state with Retry button that re-fetches on click", async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: async () => ({
          error: {
            code: "internal_error",
            message: "Database query timed out.",
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockTripsList,
      });

    vi.stubGlobal("fetch", mockFetch);

    render(<TripsListPage />);

    // 1. Initial error
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/database query timed out/i)
    ).toBeInTheDocument();

    const retryButton = screen.getByRole("button", { name: /retry/i });
    expect(retryButton).toBeInTheDocument();

    // 2. Click retry
    await userEvent.click(retryButton);

    // 3. Second fetch succeeds
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Kyoto, Japan" })
      ).toBeInTheDocument();
    });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("renders backend service unavailable message on network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
    );

    render(<TripsListPage />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/backend service unavailable/i)
    ).toBeInTheDocument();
  });
});
