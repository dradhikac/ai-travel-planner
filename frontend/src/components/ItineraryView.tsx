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

              {(() => {
                const activities = (day.activities && day.activities.length > 0)
                  ? day.activities
                  : (day.items ?? []);

                if (activities.length === 0) {
                  return (
                    <p className="p-5 text-sm text-slate-500 dark:text-slate-400">
                      No activities scheduled for this day.
                    </p>
                  );
                }

                return (
                  <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                    {activities.map((item, index) => {
                      const timeLabel = item.time_of_day
                        ? (TIME_OF_DAY_LABELS[item.time_of_day] || item.time_of_day)
                        : null;
                      const noteText = (
                        "uncertainty_notes" in item &&
                        Array.isArray(item.uncertainty_notes) &&
                        item.uncertainty_notes.length > 0
                      )
                        ? item.uncertainty_notes.join(" ")
                        : (item as { note?: string | null }).note;
                      const costText = (
                        "cost_note" in item && item.cost_note
                      )
                        ? item.cost_note
                        : (item as { cost_estimate?: string | null }).cost_estimate;
                      const refText = (
                        "source_refs" in item &&
                        Array.isArray(item.source_refs) &&
                        item.source_refs.length > 0
                      )
                        ? item.source_refs[0]
                        : (item as { source_ref?: string | null }).source_ref;

                      return (
                        <li
                          key={("id" in item && item.id) ? item.id : `${day.day_number}-${index}`}
                          className="p-5 space-y-2.5 hover:bg-slate-50/40 dark:hover:bg-slate-850/40 transition-colors"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              {timeLabel && (
                                <span className="inline-block text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                                  {timeLabel}
                                </span>
                              )}
                              <h4 className="font-semibold text-slate-900 dark:text-slate-100 text-base">
                                {item.title}
                              </h4>
                            </div>
                            <ProvenanceBadge provenance={item.provenance} />
                          </div>

                          {item.description && (
                            <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                              {item.description}
                            </p>
                          )}

                          {(noteText || costText || refText) && (
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-xs text-slate-500 dark:text-slate-400">
                              {noteText && (
                                <span className="italic">
                                  Tip: {noteText}
                                </span>
                              )}
                              {costText && (
                                <span>
                                  Cost estimate: <strong>{costText}</strong>
                                </span>
                              )}
                              {refText && (
                                <span>
                                  Ref: {refText}
                                </span>
                              )}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                );
              })()}
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
