import React from "react";
import type { Itinerary } from "@/lib/types/trip";
import { ProvenanceBadge } from "@/components/ProvenanceBadge";
import { formatDate } from "@/lib/utils/formatters";

interface ItineraryViewProps {
  itinerary: Itinerary;
}

const TIME_OF_DAY_LABELS: Record<string, string> = {
  morning: "Morning",
  afternoon: "Afternoon",
  evening: "Evening",
};

export function ItineraryView({
  itinerary,
}: ItineraryViewProps): React.ReactElement {
  return (
    <section
      aria-labelledby="itinerary-heading"
      className="space-y-6"
    >
      <div className="space-y-2 border-b border-slate-200 dark:border-slate-800 pb-4">
        <h2 id="itinerary-heading" className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          Trip Itinerary
        </h2>
        {itinerary.summary && (
          <p className="text-base text-slate-600 dark:text-slate-300 leading-relaxed">
            {itinerary.summary}
          </p>
        )}
      </div>

      {itinerary.days && itinerary.days.length > 0 ? (
        <div className="space-y-8">
          {itinerary.days.map((day) => (
            <div
              key={day.day_number}
              className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs overflow-hidden"
            >
              <div className="bg-slate-50 dark:bg-slate-800/60 px-5 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
                <h3 className="font-semibold text-base text-slate-900 dark:text-slate-100">
                  Day {day.day_number}
                </h3>
                <time
                  dateTime={day.date}
                  className="text-xs font-medium text-slate-500 dark:text-slate-400"
                >
                  {formatDate(day.date)}
                </time>
              </div>

              {day.items && day.items.length > 0 ? (
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {day.items.map((item, index) => (
                    <li
                      key={`${day.day_number}-${index}`}
                      className="p-5 space-y-2.5 hover:bg-slate-50/40 dark:hover:bg-slate-850/40 transition-colors"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="inline-block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                            {TIME_OF_DAY_LABELS[item.time_of_day] || item.time_of_day}
                          </span>
                          <h4 className="font-semibold text-slate-900 dark:text-slate-100 text-base">
                            {item.title}
                          </h4>
                        </div>
                        <ProvenanceBadge provenance={item.provenance} />
                      </div>

                      <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                        {item.description}
                      </p>

                      {(item.note || item.cost_estimate || item.source_ref) && (
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-xs text-slate-500 dark:text-slate-400">
                          {item.note && (
                            <span className="italic">
                              Tip: {item.note}
                            </span>
                          )}
                          {item.cost_estimate && (
                            <span>
                              Cost estimate: <strong>{item.cost_estimate}</strong>
                            </span>
                          )}
                          {item.source_ref && (
                            <span>
                              Ref: {item.source_ref}
                            </span>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="p-5 text-sm text-slate-500 dark:text-slate-400">
                  No activities scheduled for this day.
                </p>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No daily itinerary entries available for this trip.
        </p>
      )}
    </section>
  );
}

export default ItineraryView;
