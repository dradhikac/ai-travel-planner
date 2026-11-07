import React from "react";
import type { TripRequest } from "@/lib/types/trip";
import { formatDate, formatBudget } from "@/lib/utils/formatters";

interface TripSummaryCardProps {
  request: TripRequest;
  createdAt?: string;
}

const PACE_LABELS: Record<string, string> = {
  relaxed: "Relaxed",
  balanced: "Balanced",
  packed: "Packed",
};

export function TripSummaryCard({
  request,
}: TripSummaryCardProps): React.ReactElement {
  return (
    <section
      aria-labelledby="trip-summary-heading"
      className="p-5 sm:p-6 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 dark:border-slate-800 pb-3">
        <div>
          <span className="text-xs font-semibold uppercase tracking-wider text-blue-600 dark:text-blue-400">
            Trip Overview
          </span>
          <h1
            id="trip-summary-heading"
            className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100"
          >
            {request.origin} → {request.destination}
          </h1>
        </div>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
        <div>
          <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Dates
          </dt>
          <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
            {formatDate(request.start_date)} – {formatDate(request.end_date)}
          </dd>
        </div>

        <div>
          <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Party Size
          </dt>
          <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
            {request.party_size} {request.party_size === 1 ? "traveler" : "travelers"}
          </dd>
        </div>

        <div>
          <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Budget
          </dt>
          <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
            {formatBudget(request.budget_amount, request.currency)}
          </dd>
        </div>

        <div>
          <dt className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Pace Preference
          </dt>
          <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
            {request.pace ? PACE_LABELS[request.pace] || request.pace : "Balanced"}
          </dd>
        </div>
      </dl>

      {request.interests && request.interests.length > 0 && (
        <div className="pt-3 border-t border-slate-100 dark:border-slate-800">
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400 block mb-2">
            Interests:
          </span>
          <div className="flex flex-wrap gap-1.5">
            {request.interests.map((interest) => (
              <span
                key={interest}
                className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
              >
                {interest}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export default TripSummaryCard;
