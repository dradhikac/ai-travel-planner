/**
 * Safe formatting utilities for dates, timestamps, and currency amounts.
 */

/**
 * Format a calendar date string (YYYY-MM-DD or ISO) safely without timezone drift.
 */
export function formatDate(dateString: string): string {
  if (!dateString) return "";
  const parts = dateString.split("-");
  if (parts.length === 3 && parts[0].length === 4) {
    const year = parseInt(parts[0], 10);
    const monthIndex = parseInt(parts[1], 10) - 1;
    const day = parseInt(parts[2], 10);
    if (!isNaN(year) && !isNaN(monthIndex) && !isNaN(day)) {
      const d = new Date(year, monthIndex, day);
      return d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    }
  }
  const d = new Date(dateString);
  return isNaN(d.getTime())
    ? dateString
    : d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
}

/**
 * Format a full UTC or ISO timestamp with timezone indicator.
 */
export function formatDateTime(isoString: string): string {
  if (!isoString) return "";
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return isoString;
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/**
 * Format an optional budget amount with its ISO currency code.
 */
export function formatBudget(
  amount?: number | null,
  currency?: string | null
): string {
  if (amount === undefined || amount === null) {
    return "Not specified";
  }
  if (!currency) {
    return `${amount}`;
  }
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency.toUpperCase(),
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${currency} ${amount}`;
  }
}
