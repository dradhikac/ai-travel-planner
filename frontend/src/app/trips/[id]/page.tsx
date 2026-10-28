"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import Navbar from "@/components/Navbar";
import TripSummaryCard from "@/components/TripSummaryCard";
import WeatherCard from "@/components/WeatherCard";
import ItineraryView from "@/components/ItineraryView";
import WarningsBanner from "@/components/WarningsBanner";
import NonBookingDisclaimer from "@/components/NonBookingDisclaimer";
import { getTrip } from "@/lib/api/trips";
import { ApiError } from "@/lib/api/client";
import type { TripResponse } from "@/lib/types/trip";

type TripState =
  | { type: "loading" }
  | { type: "not_found"; id: string }
  | { type: "unreachable"; message: string }
  | { type: "error"; message: string }
  | { type: "success"; trip: TripResponse };

interface TripDetailsViewProps {
  tripId: string;
}

export function TripDetailsView({
  tripId,
}: TripDetailsViewProps): React.ReactElement {
  const [state, setState] = useState<TripState>(() =>
    !tripId || !tripId.trim()
      ? { type: "not_found", id: "" }
      : { type: "loading" }
  );
  const [retryTrigger, setRetryTrigger] = useState(0);

  useEffect(() => {
    let ignore = false;

    if (!tripId || !tripId.trim()) {
      return;
    }

    async function loadTrip() {
      try {
        const trip = await getTrip(tripId);
        if (!ignore) {
          setState({ type: "success", trip });
        }
      } catch (err: unknown) {
        if (ignore) return;

        if (err instanceof ApiError) {
          if (err.status === 404 || err.code === "trip_not_found") {
            setState({ type: "not_found", id: tripId });
            return;
          }
          if (
            err.kind === "network_error" ||
            err.kind === "timeout_error" ||
            err.status === 503
          ) {
            setState({
              type: "unreachable",
              message:
                "The backend service is currently unreachable. Please check your network connection or verify that the backend server is running.",
            });
            return;
          }
          setState({
            type: "error",
            message: err.message || "Failed to load trip details.",
          });
          return;
        }

        setState({
          type: "error",
          message:
            err instanceof Error
              ? err.message
              : "An unexpected error occurred while loading this trip.",
        });
      }
    }

    void loadTrip();

    return () => {
      ignore = true;
    };
  }, [tripId, retryTrigger]);

  const handleRetry = () => {
    setState({ type: "loading" });
    setRetryTrigger((count) => count + 1);
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
        className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8"
      >
        {state.type === "loading" && (
          <div
            role="status"
            aria-live="polite"
            className="p-10 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex items-center justify-center gap-3 text-slate-600 dark:text-slate-400"
          >
            <span
              className="inline-block h-3.5 w-3.5 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none"
              aria-hidden="true"
            />
            <span className="text-sm font-medium">
              Loading trip details...
            </span>
          </div>
        )}

        {state.type === "not_found" && (
          <div
            data-testid="trip-not-found-state"
            className="p-10 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-center space-y-4"
          >
            <div className="space-y-1">
              <span className="inline-block text-2xl" aria-hidden="true">
                🔍
              </span>
              <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
                Trip Not Found
              </h1>
              <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md mx-auto">
                No travel itinerary was found matching ID{" "}
                <code className="font-mono text-xs bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded">
                  {state.id}
                </code>
                . It may have been deleted or the link is incorrect.
              </p>
            </div>
            <div className="flex items-center justify-center gap-3 pt-2">
              <Link
                href="/plan"
                className="inline-flex items-center px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
              >
                Plan a New Trip
              </Link>
              <Link
                href="/trips"
                className="inline-flex items-center px-4 py-2 rounded-md border border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 text-sm font-medium transition-colors"
              >
                View Saved Trips
              </Link>
            </div>
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
            <h2 className="text-base font-semibold">Error Loading Trip</h2>
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

        {state.type === "success" && (
          <div className="space-y-8" data-testid="trip-results-view">
            {/* Trip summary section */}
            <TripSummaryCard
              request={state.trip.request}
              createdAt={state.trip.created_at}
            />

            {/* Non-booking boundary disclosure */}
            <NonBookingDisclaimer />

            {/* Warnings list */}
            {state.trip.warnings && state.trip.warnings.length > 0 && (
              <WarningsBanner warnings={state.trip.warnings} />
            )}

            {/* Weather section */}
            <WeatherCard
              weather={state.trip.weather}
              unavailableMessage={
                state.trip.warnings?.find((w) =>
                  w.toLowerCase().includes("weather_unavailable")
                ) || undefined
              }
            />

            {/* Itinerary section */}
            <ItineraryView itinerary={state.trip.itinerary} />
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

function TripResultContent({
  params,
}: {
  params?: Promise<{ id: string }>;
}): React.ReactElement {
  const routerParams = useParams();
  let id = "";

  if (params) {
    const resolved = React.use(params);
    id = resolved?.id || "";
  } else if (routerParams?.id && typeof routerParams.id === "string") {
    id = routerParams.id;
  }

  return <TripDetailsView tripId={id} />;
}

export default function TripResultPage(props: {
  params?: Promise<{ id: string }>;
}): React.ReactElement {
  return (
    <React.Suspense
      fallback={
        <div
          role="status"
          aria-live="polite"
          className="min-h-screen p-10 flex items-center justify-center gap-3 text-slate-500 dark:text-slate-400"
        >
          <span
            className="inline-block h-3.5 w-3.5 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none"
            aria-hidden="true"
          />
          <span className="text-sm font-medium">Loading trip...</span>
        </div>
      }
    >
      <TripResultContent {...props} />
    </React.Suspense>
  );
}
