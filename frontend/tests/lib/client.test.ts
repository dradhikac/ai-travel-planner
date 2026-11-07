import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiClient, ApiError } from "@/lib/api/client";

describe("apiClient", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("successfully performs GET request and parses JSON response", async () => {
    const mockData = { message: "pong", active: true };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => mockData,
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await apiClient<typeof mockData>("/test-endpoint");

    expect(result).toEqual(mockData);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/test-endpoint$/);
    expect(init.headers).toEqual(
      expect.objectContaining({
        Accept: "application/json",
      })
    );
  });

  it("normalizes path without leading slash", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await apiClient("health");

    const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/health$/);
  });

  it("handles 204 No Content returning undefined", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await apiClient<void>("/no-content");
    expect(result).toBeUndefined();
  });

  it("throws ApiError with kind http_error and parses standard error JSON on non-2xx response", async () => {
    const errorPayload = {
      error: {
        code: "destination_not_found",
        message: "The requested destination could not be found.",
        details: { destination_id: "paris-123" },
      },
    };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => errorPayload,
    });
    vi.stubGlobal("fetch", mockFetch);

    await expect(apiClient("/destinations/paris-123")).rejects.toSatisfy(
      (err: unknown) => {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.kind).toBe("http_error");
        expect(apiErr.status).toBe(404);
        expect(apiErr.code).toBe("destination_not_found");
        expect(apiErr.message).toBe("The requested destination could not be found.");
        expect(apiErr.details).toEqual({ destination_id: "paris-123" });
        return true;
      }
    );
  });

  it("falls back to status text when non-2xx response body is not JSON", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: async () => {
        throw new Error("Invalid json body");
      },
    });
    vi.stubGlobal("fetch", mockFetch);

    await expect(apiClient("/gateway-fail")).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.kind).toBe("http_error");
      expect(apiErr.status).toBe(502);
      expect(apiErr.code).toBe("http_502");
      expect(apiErr.message).toContain("Bad Gateway");
      return true;
    });
  });

  it("throws ApiError with kind invalid_json when 200 response body cannot be parsed", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError("Unexpected token < in JSON at position 0");
      },
    });
    vi.stubGlobal("fetch", mockFetch);

    await expect(apiClient("/corrupted-json")).rejects.toSatisfy(
      (err: unknown) => {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.kind).toBe("invalid_json");
        expect(apiErr.status).toBe(200);
        expect(apiErr.message).toContain("Invalid JSON");
        return true;
      }
    );
  });

  it("throws ApiError with kind network_error when fetch throws TypeError", async () => {
    const mockFetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", mockFetch);

    await expect(apiClient("/unreachable")).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.kind).toBe("network_error");
      expect(apiErr.message).toContain("Network error: Unable to reach backend");
      return true;
    });
  });

  it("throws ApiError with kind timeout_error when request exceeds timeout (using fake timers)", async () => {
    vi.useFakeTimers();

    const mockFetch = vi.fn((_url: string, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const abortError = new Error("The operation was aborted");
          abortError.name = "AbortError";
          reject(abortError);
        });
      });
    });
    vi.stubGlobal("fetch", mockFetch);

    const clientPromise = apiClient("/slow-endpoint", { timeoutMs: 1000 });

    // Advance fake timers by 1000ms to trigger AbortController
    vi.advanceTimersByTime(1000);

    await expect(clientPromise).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.kind).toBe("timeout_error");
      expect(apiErr.message).toContain("timed out after 1000ms");
      return true;
    });
  });
});
