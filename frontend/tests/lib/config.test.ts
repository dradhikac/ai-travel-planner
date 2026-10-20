import { describe, it, expect } from "vitest";
import { config, validateAndNormalizeApiBaseUrl } from "@/lib/config";

describe("Frontend Configuration", () => {
  describe("validateAndNormalizeApiBaseUrl", () => {
    it("returns default URL when input is undefined", () => {
      expect(validateAndNormalizeApiBaseUrl(undefined)).toBe("http://localhost:8000");
    });

    it("returns default URL when input is empty or whitespace", () => {
      expect(validateAndNormalizeApiBaseUrl("")).toBe("http://localhost:8000");
      expect(validateAndNormalizeApiBaseUrl("   ")).toBe("http://localhost:8000");
    });

    it("supports custom default URL argument", () => {
      expect(
        validateAndNormalizeApiBaseUrl(undefined, "https://default.example.com")
      ).toBe("https://default.example.com");
    });

    it("accepts valid http and https URL overrides", () => {
      expect(validateAndNormalizeApiBaseUrl("http://api.local:8000")).toBe(
        "http://api.local:8000"
      );
      expect(validateAndNormalizeApiBaseUrl("https://api.travel.example.com")).toBe(
        "https://api.travel.example.com"
      );
    });

    it("strips trailing slashes from provided URLs", () => {
      expect(validateAndNormalizeApiBaseUrl("http://localhost:8000/")).toBe(
        "http://localhost:8000"
      );
      expect(
        validateAndNormalizeApiBaseUrl("https://api.travel.example.com///")
      ).toBe("https://api.travel.example.com");
    });

    it("rejects non-URL strings with a descriptive error", () => {
      expect(() => validateAndNormalizeApiBaseUrl("not-a-valid-url")).toThrow(
        /Invalid NEXT_PUBLIC_API_BASE_URL/
      );
    });

    it("rejects non-http/https protocols", () => {
      expect(() => validateAndNormalizeApiBaseUrl("ftp://files.example.com")).toThrow(
        /Protocol must be "http:" or "https:"/
      );
      expect(() => validateAndNormalizeApiBaseUrl("ws://socket.example.com")).toThrow(
        /Protocol must be "http:" or "https:"/
      );
    });
  });

  describe("config export", () => {
    it("provides a valid apiBaseUrl string", () => {
      expect(typeof config.apiBaseUrl).toBe("string");
      expect(config.apiBaseUrl.length).toBeGreaterThan(0);
      expect(config.apiBaseUrl.startsWith("http")).toBe(true);
      expect(config.apiBaseUrl.endsWith("/")).toBe(false);
    });
  });
});
