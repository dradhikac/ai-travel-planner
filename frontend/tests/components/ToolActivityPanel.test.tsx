import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ToolActivityPanel, {
  sanitizeSource,
  sanitizeExplanation,
  formatStatusInWords,
} from "@/components/ToolActivityPanel";
import type { ToolActivity } from "@/lib/types/trip";

describe("ToolActivityPanel Component & Sanitizers", () => {
  it("sanitizeSource strips URL query parameters and fragments", () => {
    expect(
      sanitizeSource(
        "https://api.open-meteo.com/v1/forecast?latitude=35.68&longitude=139.76&apikey=secret-token"
      )
    ).toBe("https://api.open-meteo.com/v1/forecast");

    expect(
      sanitizeSource("https://example.com/api/geocode#anchor?param=1")
    ).toBe("https://example.com/api/geocode");

    expect(sanitizeSource("Open-Meteo Weather Service")).toBe(
      "Open-Meteo Weather Service"
    );
  });

  it("sanitizeExplanation suppresses raw tracebacks and redacts credentials", () => {
    expect(
      sanitizeExplanation("Resolved coordinates for Tokyo (35.68, 139.76)")
    ).toBe("Resolved coordinates for Tokyo (35.68, 139.76)");

    // Secret redaction
    expect(
      sanitizeExplanation("Fetched forecast with api_key=secret_123456789")
    ).toContain("[REDACTED]");
    expect(
      sanitizeExplanation("Fetched forecast with api_key=secret_123456789")
    ).not.toContain("secret_123456789");

    // Traceback redaction
    const traceback =
      'Traceback (most recent call last):\n  File "client.py", line 42, in get';
    expect(sanitizeExplanation(traceback)).toBe(
      "Tool operation encountered an error."
    );
  });

  it("formatStatusInWords converts statuses into human words", () => {
    expect(formatStatusInWords("ok")).toBe("Completed");
    expect(formatStatusInWords("empty")).toBe("No results found");
    expect(formatStatusInWords("error")).toBe("Failed");
    expect(formatStatusInWords("timeout")).toBe("Timed out");
    expect(formatStatusInWords("rate_limited")).toBe("Rate limited");
    expect(formatStatusInWords("skipped")).toBe("Skipped");
  });

  it("renders tool activities with Live/Mock badges, status in words, and support reference", () => {
    const activities: ToolActivity[] = [
      {
        tool_label: "Destination Geocoding",
        status: "ok",
        source: "https://geocoding-api.open-meteo.com/v1/search?name=Tokyo&secret=123",
        fetched_at: "2026-08-01T12:00:00Z",
        data_origin: "live",
        explanation: "Located coordinates for Tokyo (35.68, 139.76)",
      },
      {
        tool_label: "Weather Forecast",
        status: "ok",
        source: "Open-Meteo Fixture Service",
        fetched_at: "2026-08-01T12:05:00Z",
        data_origin: "mock",
        explanation: "Fetched simulated weather forecast for Tokyo",
      },
    ];

    render(
      <ToolActivityPanel
        activities={activities}
        requestId="req-test-uuid-999"
      />
    );

    // Title & heading
    expect(screen.getByText(/What I checked/i)).toBeInTheDocument();

    // Human labels
    expect(screen.getByText("Destination Geocoding")).toBeInTheDocument();
    expect(screen.getByText("Weather Forecast")).toBeInTheDocument();

    // Status in words
    const statusBadges = screen.getAllByText(/Status: Completed/i);
    expect(statusBadges).toHaveLength(2);

    // Live badge
    expect(screen.getByTestId("data-origin-live-badge")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();

    // Mock badge
    expect(screen.getByTestId("data-origin-mock-badge")).toBeInTheDocument();
    expect(screen.getByText("Mock")).toBeInTheDocument();

    // Sanitized source: query params omitted
    expect(
      screen.getByText(/https:\/\/geocoding-api\.open-meteo\.com\/v1\/search/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/secret=123/)).not.toBeInTheDocument();

    // Support reference with request ID
    expect(screen.getByText(/Support reference:/i)).toBeInTheDocument();
    expect(screen.getByText("req-test-uuid-999")).toBeInTheDocument();
  });

  it("renders empty note when no activities occurred", () => {
    render(<ToolActivityPanel activities={[]} requestId="req-empty" />);
    expect(
      screen.getByText(/No external tools were checked for this request/i)
    ).toBeInTheDocument();
    expect(screen.getByText("req-empty")).toBeInTheDocument();
  });
});
