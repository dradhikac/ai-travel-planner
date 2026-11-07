import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getHealth,
  getVersion,
  validateHealthResponse,
  validateVersionResponse,
} from "@/lib/api/health";

describe("Health & Version API Service", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("validateHealthResponse", () => {
    it("parses valid health payload", () => {
      const result = validateHealthResponse({ status: "ok" });
      expect(result).toEqual({ status: "ok" });
    });

    it("rejects non-object payloads", () => {
      expect(() => validateHealthResponse(null)).toThrow(/Expected an object payload/);
      expect(() => validateHealthResponse(undefined)).toThrow(/Expected an object payload/);
      expect(() => validateHealthResponse("ok")).toThrow(/Expected an object payload/);
      expect(() => validateHealthResponse(["ok"])).toThrow(/Expected an object payload/);
    });

    it("rejects payload missing status or with non-string status", () => {
      expect(() => validateHealthResponse({})).toThrow(/Missing or empty 'status'/);
      expect(() => validateHealthResponse({ status: 123 })).toThrow(
        /Missing or empty 'status'/
      );
      expect(() => validateHealthResponse({ status: null })).toThrow(
        /Missing or empty 'status'/
      );
    });

    it("rejects empty or whitespace status string", () => {
      expect(() => validateHealthResponse({ status: "" })).toThrow(
        /Missing or empty 'status'/
      );
      expect(() => validateHealthResponse({ status: "   " })).toThrow(
        /Missing or empty 'status'/
      );
    });
  });

  describe("validateVersionResponse", () => {
    it("parses valid version payload", () => {
      const payload = {
        name: "ai-travel-concierge-backend",
        version: "0.1.0",
        environment: "development",
      };
      const result = validateVersionResponse(payload);
      expect(result).toEqual(payload);
    });

    it("rejects non-object payloads", () => {
      expect(() => validateVersionResponse(null)).toThrow(/Expected an object payload/);
      expect(() => validateVersionResponse("version-string")).toThrow(
        /Expected an object payload/
      );
    });

    it("rejects payload missing or invalid name", () => {
      expect(() =>
        validateVersionResponse({
          version: "0.1.0",
          environment: "development",
        })
      ).toThrow(/Missing or empty 'name'/);
      expect(() =>
        validateVersionResponse({
          name: "",
          version: "0.1.0",
          environment: "development",
        })
      ).toThrow(/Missing or empty 'name'/);
    });

    it("rejects payload missing or invalid version", () => {
      expect(() =>
        validateVersionResponse({
          name: "backend",
          version: "",
          environment: "development",
        })
      ).toThrow(/Missing or empty 'version'/);
    });

    it("rejects payload missing or invalid environment", () => {
      expect(() =>
        validateVersionResponse({
          name: "backend",
          version: "0.1.0",
          environment: "   ",
        })
      ).toThrow(/Missing or empty 'environment'/);
    });
  });

  describe("getHealth and getVersion client methods", () => {
    it("getHealth fetches from /health and returns validated data", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ status: "ok" }),
      });
      vi.stubGlobal("fetch", mockFetch);

      const health = await getHealth();
      expect(health).toEqual({ status: "ok" });
      const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toMatch(/\/health$/);
    });

    it("getHealth rejects when payload schema does not match", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ unexpected: "data" }),
      });
      vi.stubGlobal("fetch", mockFetch);

      await expect(getHealth()).rejects.toThrow(/Missing or empty 'status'/);
    });

    it("getVersion fetches from /api/version and returns validated data", async () => {
      const versionPayload = {
        name: "ai-travel-concierge-backend",
        version: "0.1.0",
        environment: "production",
      };
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => versionPayload,
      });
      vi.stubGlobal("fetch", mockFetch);

      const version = await getVersion();
      expect(version).toEqual(versionPayload);
      const [url] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toMatch(/\/api\/version$/);
    });

    it("getVersion rejects when payload schema does not match", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ name: "backend" }),
      });
      vi.stubGlobal("fetch", mockFetch);

      await expect(getVersion()).rejects.toThrow(/Missing or empty 'version'/);
    });
  });
});
