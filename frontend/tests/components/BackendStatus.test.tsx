import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BackendStatus } from "@/components/BackendStatus";

describe("BackendStatus Component", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows loading indicator first with role='status' and aria-live='polite', then connected state with version", async () => {
    const mockFetch = vi.fn((url: string) => {
      if (url.endsWith("/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "ok" }),
        });
      }
      if (url.endsWith("/api/version")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            name: "ai-travel-concierge-backend",
            version: "0.1.0",
            environment: "development",
          }),
        });
      }
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<BackendStatus />);

    // 1. Initial render state: checking / loading
    const statusElement = screen.getByRole("status");
    expect(statusElement).toBeInTheDocument();
    expect(statusElement).toHaveAttribute("aria-live", "polite");
    expect(
      screen.getByText(/checking backend connection status\.\.\./i)
    ).toBeInTheDocument();

    // 2. Transition to connected state
    await waitFor(() => {
      expect(
        screen.getByText(/connected to backend service/i)
      ).toBeInTheDocument();
    });

    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText(/development/i)).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("shows unreachable state without stack traces and recovers after Retry is clicked", async () => {
    const user = userEvent.setup();
    let shouldFail = true;

    const mockFetch = vi.fn((url: string) => {
      if (shouldFail) {
        return Promise.reject(new TypeError("Failed to fetch"));
      }

      if (url.endsWith("/health")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "ok" }),
        });
      }
      if (url.endsWith("/api/version")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            name: "ai-travel-concierge-backend",
            version: "0.1.0",
            environment: "test",
          }),
        });
      }
      return Promise.reject(new Error("Unexpected URL"));
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<BackendStatus />);

    // Wait for unreachable state
    await waitFor(() => {
      expect(
        screen.getByText(/backend service unreachable/i)
      ).toBeInTheDocument();
    });

    expect(
      screen.getByText(/unable to connect to the backend api service/i)
    ).toBeInTheDocument();

    // Verify no raw stack traces or internal technical error messages are rendered
    expect(screen.queryByText(/TypeError/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/at Object\./i)).not.toBeInTheDocument();

    // Find and click the Retry button
    const retryButton = screen.getByRole("button", {
      name: /retry connection/i,
    });
    expect(retryButton).toBeInTheDocument();

    // Mock now succeeds on retry
    shouldFail = false;
    await user.click(retryButton);

    // Verify recovery to connected state
    await waitFor(() => {
      expect(
        screen.getByText(/connected to backend service/i)
      ).toBeInTheDocument();
    });
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
  });

  it("shows unexpected-response state when backend returns unexpected payload format", async () => {
    const mockFetch = vi.fn((url: string) => {
      if (url.endsWith("/health")) {
        // Returns invalid payload without status field
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ unexpectedField: "malformed" }),
        });
      }
      if (url.endsWith("/api/version")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            name: "ai-travel-concierge-backend",
            version: "0.1.0",
            environment: "development",
          }),
        });
      }
      return Promise.reject(new Error("Unexpected URL"));
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<BackendStatus />);

    await waitFor(() => {
      expect(
        screen.getByText(/unexpected backend response/i)
      ).toBeInTheDocument();
    });

    expect(
      screen.getByText(
        /the backend service answered, but the payload did not match the expected schema/i
      )
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /retry connection/i })
    ).toBeInTheDocument();
  });

  it("shows unexpected-response state when backend returns an HTTP 500 error status", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => ({
        error: {
          code: "internal_error",
          message: "Database connection failed",
        },
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<BackendStatus />);

    await waitFor(() => {
      expect(
        screen.getByText(/unexpected backend response/i)
      ).toBeInTheDocument();
    });

    expect(
      screen.getByText(
        /the backend service answered, but the response was invalid or returned an error status/i
      )
    ).toBeInTheDocument();
  });
});
