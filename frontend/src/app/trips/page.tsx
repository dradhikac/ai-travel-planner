"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import { listTrips } from "@/lib/api/trips";
import { ApiError } from "@/lib/api/client";
import type { TripSummaryItem } from "@/lib/types/trip";
import { formatDate, formatDateTime } from "@/lib/utils/formatters";

type TripsState =
  | { type: "loading" }
  | { type: "empty" }
  | { type: "success"; trips: TripSummaryItem[] }
  | { type: "unreachable"; message: string }
  | { type: "error"; message: string };

export default function TripsListPage(): React.ReactElement {
  const [state, setState] = useState<TripsState>({ type: "loading" });
  const [retryTrigger, setRetryTrigger] = useState(0);

  useEffect(() => {
    let ignore = false;

    async function fetchTrips() {
      try {
        const trips = await listTrips({ limit: 20 });
        if (!ignore) {
          if (!trips || trips.length === 0) {
            setState({ type: "empty" });
          } else {
            setState({ type: "success", trips });
          }
        }
      } catch (err: unknown) {
        if (ignore) return;

        if (err instanceof ApiError) {
          if (
            err.kind === "network_error" ||
            err.kind === "timeout_error" ||
            err.status === 503
          ) {
            setState({
              type: "unreachable",
              message:
                "Unable to reach the backend service. Please ensure the backend server is running and try again.",
            });
            return;
          }
          setState({
            type: "error",
            message: err.message || "Failed to load saved trips.",
          });
          return;
        }

        setState({
          type: "error",
          message:
            err instanceof Error
              ? err.message
              : "An unexpected error occurred while loading trips.",
        });
      }
    }

    void fetchTrips();

    return () => {
      ignore = true;
    };
  }, [retryTrigger]);

  const handleRetry = () => {
    setState({ type: "loading" });
    setRetryTrigger((prev) => prev + 1);
  };

  return (
    <div className="min-h-screen flex flex-col justify-between">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:bg-white focus:text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-600 rounded shadow-md"
      >
        Skip to content
      </a>

      <Navbar />

      <main
        id="main-content"
        className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-6"
      >
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-800 pb-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
              Saved Trips
            </h1>
            <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
              Browse previously planned itineraries and travel research summaries.
            </p>
          </div>
          <Link
            href="/plan"
            className="inline-flex items-center px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold shadow-xs transition-colors"
          >
            Plan a New Trip
          </Link>
        </div>

        {state.type === "loading" && (
          <div
            role="status"
            aria-live="polite"
            className="p-8 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex items-center justify-center gap-3 text-slate-600 dark:text-slate-400"
          >
            <span
              className="inline-block h-3.5 w-3.5 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none"
              aria-hidden="true"
            />
            <span className="text-sm font-medium">Loading saved trips...</span>
          </div>
        )}

        {state.type === "empty" && (
          <div
            data-testid="trips-empty-state"
            className="p-10 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-center space-y-4"
          >
            <div className="space-y-1">
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                No saved trips found
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md mx-auto">
                You haven&apos;t generated any travel itineraries yet. Start by
                entering your travel destination and dates.
              </p>
            </div>
            <div>
              <Link
                href="/plan"
                className="inline-flex items-center px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
              >
                Plan Your First Trip
              </Link>
            </div>
          </div>
        )}

        {state.type === "success" && (
          <div
            data-testid="trips-list-container"
            className="grid grid-cols-1 md:grid-cols-2 gap-4"
          >
            {state.trips.map((trip) => (
              <article
                key={trip.id}
                className="p-5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs hover:border-slate-300 dark:hover:border-slate-700 transition-all flex flex-col justify-between space-y-4"
              >
                <div className="space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-blue-600 dark:text-blue-400">
                    Saved Itinerary
                  </span>
                  <h2 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
                    {trip.destination}
                  </h2>
                  <p className="text-sm text-slate-600 dark:text-slate-300">
                    {formatDate(trip.start_date)} – {formatDate(trip.end_date)}
                  </p>
                </div>

                <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                  <span>Created {formatDateTime(trip.created_at)}</span>
                  <Link
                    href={`/trips/${trip.id}`}
                    className="font-semibold text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    View Itinerary →
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )}

        {state.type === "unreachable" && (
          <div
            role="alert"
            className="p-6 rounded-lg border border-rose-200 dark:border-rose-900/60 bg-rose-50/70 dark:bg-rose-950/20 text-rose-950 dark:text-rose-200 space-y-3"
          >
            <h2 className="text-base font-semibold">Backend Service Unavailable</h2>
            <p className="text-sm text-rose-900/90 dark:text-rose-200/90 leading-relaxed">
              {state.message}
            </p>
            <button
              type="button"
              onClick={handleRetry}
              className="px-3.5 py-1.5 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold shadow-xs transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {state.type === "error" && (
          <div
            role="alert"
            className="p-6 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-950/20 text-amber-950 dark:text-amber-200 space-y-3"
          >
            <h2 className="text-base font-semibold">Unable to Load Trips</h2>
            <p className="text-sm text-amber-900/90 dark:text-amber-200/90 leading-relaxed">
              {state.message}
            </p>
            <button
              type="button"
              onClick={handleRetry}
              className="px-3.5 py-1.5 rounded-md bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold shadow-xs transition-colors"
            >
              Retry
            </button>
          </div>
        )}
      </main>

      <footer className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 py-6">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-slate-500 dark:text-slate-400">
          <p>AI Travel Concierge — Travel Discovery and Planning Assistant.</p>
          <p>Planning concierge only; no bookings or reservations.</p>
        </div>
      </footer>
    </div>
  );
}
