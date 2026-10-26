import React from "react";
import type { WeatherSummary } from "@/lib/types/trip";
import { formatDate, formatDateTime } from "@/lib/utils/formatters";

interface WeatherCardProps {
  weather: WeatherSummary | null;
  unavailableMessage?: string;
}

export function WeatherCard({
  weather,
  unavailableMessage,
}: WeatherCardProps): React.ReactElement {
  if (!weather) {
    return (
      <section
        aria-labelledby="weather-heading"
        className="p-5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/40 text-slate-800 dark:text-slate-200 space-y-2"
      >
        <h2 id="weather-heading" className="text-lg font-semibold tracking-tight">
          Weather Forecast
        </h2>
        <div
          role="note"
          className="p-4 rounded border border-amber-200 dark:border-amber-900/50 bg-amber-50/60 dark:bg-amber-950/20 text-amber-900 dark:text-amber-200 text-sm leading-relaxed"
        >
          <span className="font-semibold block mb-1">Forecast Unavailable</span>
          <p>
            {unavailableMessage ||
              "Weather forecast could not be retrieved; itinerary generated with seasonal estimates."}
          </p>
        </div>
      </section>
    );
  }

  const isMock =
    weather.data_origin === "mock" || weather.source?.data_origin === "mock";
  const tempUnit = weather.units?.temperature === "celsius" ? "°C" : "°";
  const precipUnit = weather.units?.precipitation || "mm";

  return (
    <section
      aria-labelledby="weather-heading"
      className="p-5 sm:p-6 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 dark:border-slate-800 pb-3">
        <div className="space-y-1">
          <h2 id="weather-heading" className="text-lg font-semibold tracking-tight">
            Weather Forecast: {weather.location}
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Daily temperature range and precipitation probability for your trip.
          </p>
        </div>
        {isMock && (
          <span
            className="inline-flex items-center px-2.5 py-1 rounded-md text-xs font-bold border border-amber-300 dark:border-amber-700 bg-amber-100 dark:bg-amber-950/80 text-amber-900 dark:text-amber-200"
            data-testid="mock-data-badge"
          >
            Mock data
          </span>
        )}
      </div>

      {weather.horizon_note && (
        <div className="p-3 rounded border border-blue-200 dark:border-blue-900/40 bg-blue-50/60 dark:bg-blue-950/20 text-xs text-blue-900 dark:text-blue-200">
          <strong>Notice:</strong> {weather.horizon_note}
        </div>
      )}

      {weather.days && weather.days.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm border-collapse">
            <caption className="sr-only">
              Daily weather forecast table for {weather.location}
            </caption>
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800 text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
                <th scope="col" className="py-2.5 px-3 font-semibold">
                  Date
                </th>
                <th scope="col" className="py-2.5 px-3 font-semibold">
                  Condition
                </th>
                <th scope="col" className="py-2.5 px-3 font-semibold">
                  Min / Max Temp
                </th>
                <th scope="col" className="py-2.5 px-3 font-semibold">
                  Rain Chance
                </th>
                <th scope="col" className="py-2.5 px-3 font-semibold">
                  Precipitation
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {weather.days.map((day) => (
                <tr
                  key={day.date}
                  className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30"
                >
                  <td className="py-2.5 px-3 font-medium text-slate-900 dark:text-slate-100 whitespace-nowrap">
                    {formatDate(day.date)}
                  </td>
                  <td className="py-2.5 px-3 text-slate-700 dark:text-slate-300">
                    {day.condition_description}
                  </td>
                  <td className="py-2.5 px-3 text-slate-700 dark:text-slate-300 whitespace-nowrap">
                    {Math.round(day.temp_min_c)}{tempUnit} /{" "}
                    {Math.round(day.temp_max_c)}{tempUnit}
                  </td>
                  <td className="py-2.5 px-3 text-slate-700 dark:text-slate-300">
                    {day.precipitation_probability_pct}%
                  </td>
                  <td className="py-2.5 px-3 text-slate-700 dark:text-slate-300">
                    {day.precipitation_sum_mm} {precipUnit}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No daily forecast entries available for this location.
        </p>
      )}

      {/* Source attribution and freshness metadata */}
      {weather.source && (
        <footer className="pt-3 border-t border-slate-100 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
          <div>
            <span>Source: </span>
            {weather.source.url ? (
              <a
                href={weather.source.url}
                target="_blank"
                rel="noreferrer noopener"
                className="underline hover:text-blue-600 dark:hover:text-blue-400"
              >
                {weather.source.provider}
              </a>
            ) : (
              <span>{weather.source.provider}</span>
            )}
            {weather.source.attribution && (
              <span className="ml-1 text-slate-400 dark:text-slate-500">
                ({weather.source.attribution})
              </span>
            )}
          </div>
          <div>
            <span>Fetched: </span>
            <time
              dateTime={weather.source.fetched_at}
              className="font-mono text-[11px]"
            >
              {formatDateTime(weather.source.fetched_at)}
            </time>
          </div>
        </footer>
      )}
    </section>
  );
}

export default WeatherCard;
