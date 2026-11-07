import { describe, it, expect } from "vitest";
import {
  formatDate,
  formatDateTime,
  formatBudget,
} from "@/lib/utils/formatters";

describe("Formatters Utility", () => {
  describe("formatDate", () => {
    it("formats calendar date YYYY-MM-DD safely without timezone drift", () => {
      const formatted = formatDate("2026-06-15");
      expect(formatted).toBe("Jun 15, 2026");
    });

    it("returns empty string when input is empty", () => {
      expect(formatDate("")).toBe("");
    });

    it("formats fallback ISO strings", () => {
      const formatted = formatDate("2026-12-25T10:00:00Z");
      expect(formatted).toMatch(/Dec 25, 2026/);
    });
  });

  describe("formatDateTime", () => {
    it("formats timestamp with timezone string", () => {
      const formatted = formatDateTime("2026-06-10T12:00:00Z");
      expect(formatted).toContain("2026");
      expect(formatted).toMatch(/Jun 10/);
    });

    it("returns empty string for empty input", () => {
      expect(formatDateTime("")).toBe("");
    });
  });

  describe("formatBudget", () => {
    it("returns 'Not specified' when amount is null or undefined", () => {
      expect(formatBudget(null, "USD")).toBe("Not specified");
      expect(formatBudget(undefined, "USD")).toBe("Not specified");
    });

    it("formats budget with currency symbol", () => {
      const formatted = formatBudget(2500, "USD");
      expect(formatted).toBe("$2,500");
    });

    it("returns raw amount string when currency is missing", () => {
      expect(formatBudget(1000, null)).toBe("1000");
    });
  });
});
