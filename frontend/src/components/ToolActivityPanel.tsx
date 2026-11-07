import React from "react";
import type { ToolActivity } from "@/lib/types/trip";
import { formatDateTime } from "@/lib/utils/formatters";

export interface ToolActivityPanelProps {
  activities?: ToolActivity[];
  requestId?: string;
  className?: string;
}

/**
 * Strip query parameters, tokens, and fragment anchors from external URLs.
 */
export function sanitizeSource(rawSource: string): string {
  if (!rawSource || typeof rawSource !== "string") {
    return "Unknown provider";
  }
  const trimmed = rawSource.trim();
  try {
    if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
      const parsed = new URL(trimmed);
      return `${parsed.origin}${parsed.pathname}`;
    }
  } catch {
    // Fall back to string splitting if not a valid URL
  }
  return trimmed.split("?")[0].split("#")[0].trim();
}

/**
 * Sanitize tool explanations to ensure no stack traces or secrets leak into the UI.
 */
export function sanitizeExplanation(text: string): string {
  if (!text || typeof text !== "string") {
    return "Tool executed for travel plan verification.";
  }
  let clean = text.trim();
  // Redact potential secret/token patterns
  clean = clean.replace(
    /(api[_-]?key|token|password|secret|credential|auth)\s*[:=]\s*\S+/gi,
    "[REDACTED]"
  );
  // Redact stack traces or tracebacks
  if (
    clean.toLowerCase().includes("traceback (most recent call last)") ||
    clean.includes("File \"")
  ) {
    return "Tool operation encountered an error.";
  }
  return clean;
}

/**
 * Convert technical tool execution status into human-readable words.
 */
export function formatStatusInWords(rawStatus: string): string {
  if (!rawStatus) return "Unknown";
  const s = rawStatus.toLowerCase().trim();
  switch (s) {
    case "ok":
    case "completed":
    case "success":
      return "Completed";
    case "empty":
      return "No results found";
    case "error":
    case "failed":
      return "Failed";
    case "timeout":
    case "timed_out":
      return "Timed out";
    case "rate_limited":
      return "Rate limited";
    case "skipped":
      return "Skipped";
    default:
      return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");
  }
}

export function ToolActivityPanel({
  activities = [],
  requestId,
  className = "",
}: ToolActivityPanelProps): React.ReactElement {
  return (
    <section
      aria-labelledby="tool-activity-heading"
      data-testid="tool-activity-panel"
      className={`p-6 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs space-y-4 ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800 pb-3">
        <div>
          <h2
            id="tool-activity-heading"
            className="text-lg font-bold tracking-tight text-slate-900 dark:text-slate-100 flex items-center gap-2"
          >
            <span aria-hidden="true">🔍</span>
            What I checked
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Audit trail of data sources, geocoding, and meteorological tools consulted during planning.
          </p>
        </div>
        {requestId && (
          <span className="text-xs text-slate-400 dark:text-slate-500 font-mono">
            Ref: {requestId}
          </span>
        )}
      </div>

      {activities.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400 italic py-2">
          No external tools were checked for this request.
        </p>
      ) : (
        <ul className="space-y-3" role="list">
          {activities.map((activity, index) => {
            const statusWord = formatStatusInWords(activity.status);
            const isMock = activity.data_origin === "mock";
            const isLive = activity.data_origin === "live";
            const cleanSource = sanitizeSource(activity.source);
            const cleanReason = sanitizeExplanation(activity.explanation);

            return (
              <li
                key={`${activity.tool_label}-${index}`}
                data-testid={`tool-activity-item-${index}`}
                className="p-3.5 rounded-md border border-slate-100 dark:border-slate-800/80 bg-slate-50/60 dark:bg-slate-950/40 space-y-2 text-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold text-slate-900 dark:text-slate-100">
                    {activity.tool_label}
                  </span>
                  <div className="flex items-center gap-2 text-xs">
                    {/* Live / Mock badge */}
                    {isLive && (
                      <span
                        data-testid="data-origin-live-badge"
                        className="inline-flex items-center px-2 py-0.5 rounded-full font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800"
                      >
                        Live
                      </span>
                    )}
                    {isMock && (
                      <span
                        data-testid="data-origin-mock-badge"
                        className="inline-flex items-center px-2 py-0.5 rounded-full font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800"
                      >
                        Mock
                      </span>
                    )}
                    {!isLive && !isMock && (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full font-medium bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
                        {activity.data_origin || "none"}
                      </span>
                    )}

                    {/* Status in words (not color-only) */}
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full font-medium ${
                        statusWord === "Completed"
                          ? "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200"
                          : "bg-rose-50 text-rose-800 dark:bg-rose-950/50 dark:text-rose-300 border border-rose-200 dark:border-rose-900"
                      }`}
                    >
                      Status: {statusWord}
                    </span>
                  </div>
                </div>

                <p className="text-slate-600 dark:text-slate-300 text-xs sm:text-sm leading-relaxed">
                  {cleanReason}
                </p>

                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400 pt-1 border-t border-slate-200/60 dark:border-slate-800/60">
                  <span>
                    Source: <span className="font-mono">{cleanSource}</span>
                  </span>
                  {activity.fetched_at && (
                    <span>
                      Fetched: {formatDateTime(activity.fetched_at)}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {requestId && (
        <div className="pt-2 border-t border-slate-100 dark:border-slate-800 text-xs text-slate-500 dark:text-slate-400">
          Support reference: <span className="font-mono font-medium">{requestId}</span>
        </div>
      )}
    </section>
  );
}

export default ToolActivityPanel;
