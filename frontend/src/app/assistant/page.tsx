"use client";

import React, { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import TripSummaryCard from "@/components/TripSummaryCard";
import WeatherCard from "@/components/WeatherCard";
import ItineraryView from "@/components/ItineraryView";
import WarningsBanner from "@/components/WarningsBanner";
import NonBookingDisclaimer from "@/components/NonBookingDisclaimer";
import ToolActivityPanel from "@/components/ToolActivityPanel";
import { planWithAssistant } from "@/lib/api/assistant";
import { ApiError } from "@/lib/api/client";
import type {
  PacePreference,
  ToolActivity,
  TripResponse,
} from "@/lib/types/trip";

const MAX_MESSAGE_LENGTH = 2000;

type AssistantUiState =
  | { type: "idle" }
  | { type: "loading" }
  | {
      type: "needs_clarification";
      question: string;
      missingFields: string[];
      requestId: string;
      toolActivity?: ToolActivity[];
      warnings?: string[];
    }
  | {
      type: "completed";
      trip: TripResponse;
      requestId: string;
      toolActivity?: ToolActivity[];
      warnings?: string[];
    }
  | {
      type: "partial";
      trip: TripResponse;
      requestId: string;
      toolActivity?: ToolActivity[];
      warnings?: string[];
      notice: string;
    }
  | {
      type: "failed";
      message: string;
      requestId?: string;
      toolActivity?: ToolActivity[];
    }
  | {
      type: "unreachable";
      message: string;
    };

interface StructuredFieldsState {
  origin: string;
  destination: string;
  start_date: string;
  end_date: string;
  party_size: string;
  pace: PacePreference | "";
  budget_amount: string;
  currency: string;
  interests: string;
}

const initialStructuredFields: StructuredFieldsState = {
  origin: "",
  destination: "",
  start_date: "",
  end_date: "",
  party_size: "",
  pace: "",
  budget_amount: "",
  currency: "USD",
  interests: "",
};

export default function AssistantPage(): React.ReactElement {
  const router = useRouter();

  // Form inputs
  const [message, setMessage] = useState("");
  const [structuredFields, setStructuredFields] =
    useState<StructuredFieldsState>(initialStructuredFields);
  const [showStructuredFields, setShowStructuredFields] = useState(false);

  // Accumulated known fields across conversational turns
  const [knownFields, setKnownFields] = useState<Record<string, unknown>>({});
  const [clarificationInputs, setClarificationInputs] = useState<
    Record<string, string>
  >({});

  // UI state & screen reader announcements
  const [uiState, setUiState] = useState<AssistantUiState>({ type: "idle" });
  const [announcement, setAnnouncement] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  // Accessible focus refs
  const messageInputRef = useRef<HTMLTextAreaElement>(null);
  const clarificationHeadingRef = useRef<HTMLHeadingElement>(null);
  const resultsHeadingRef = useRef<HTMLHeadingElement>(null);
  const errorHeadingRef = useRef<HTMLHeadingElement>(null);

  // Manage programmatic focus transitions
  useEffect(() => {
    if (uiState.type === "needs_clarification") {
      clarificationHeadingRef.current?.focus();
    } else if (uiState.type === "completed" || uiState.type === "partial") {
      resultsHeadingRef.current?.focus();
    } else if (uiState.type === "failed" || uiState.type === "unreachable") {
      errorHeadingRef.current?.focus();
    }
  }, [uiState.type]);

  const handleMessageChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    if (val.length <= MAX_MESSAGE_LENGTH) {
      setMessage(val);
    }
  };

  const handleStructuredFieldChange = (
    field: keyof StructuredFieldsState,
    value: string
  ) => {
    setStructuredFields((prev) => ({ ...prev, [field]: value }));
  };

  const handleClarificationInputChange = (field: string, value: string) => {
    setClarificationInputs((prev) => ({ ...prev, [field]: value }));
  };

  const executePlanning = async (
    userMsg: string,
    fields: Record<string, unknown>,
    saveTrip: boolean = false
  ) => {
    setUiState({ type: "loading" });
    setAnnouncement("Contacting travel planning assistant...");

    try {
      const res = await planWithAssistant(userMsg, fields, saveTrip);

      if (res.status === "needs_clarification") {
        const missing = res.missing_fields || [];
        setUiState({
          type: "needs_clarification",
          question:
            res.clarification_question ||
            "Please provide a few more details to help plan your trip.",
          missingFields: missing,
          requestId: res.request_id,
          toolActivity: res.tool_activity,
          warnings: res.warnings,
        });

        // Initialize clarification inputs with existing known values if available
        const nextInputs: Record<string, string> = {};
        for (const f of missing) {
          nextInputs[f] = String(fields[f] || "");
        }
        setClarificationInputs(nextInputs);

        setAnnouncement(
          `Clarification requested: ${res.clarification_question || "Please provide details."}`
        );
      } else if (res.status === "completed") {
        if (!res.trip) {
          throw new Error("Assistant marked status as completed but returned no trip itinerary.");
        }
        setUiState({
          type: "completed",
          trip: res.trip,
          requestId: res.request_id,
          toolActivity: res.tool_activity || res.trip.tool_activity,
          warnings: res.warnings || res.trip.warnings,
        });
        setAnnouncement("Itinerary successfully synthesized.");
      } else if (res.status === "partial") {
        if (!res.trip) {
          throw new Error("Assistant marked status as partial but returned no trip itinerary.");
        }
        const notice =
          res.warnings?.find((w) => w.toLowerCase().includes("weather")) ||
          res.trip.warnings?.find((w) => w.toLowerCase().includes("weather")) ||
          "Some live data could not be retrieved. Itinerary was generated with seasonal estimates.";

        setUiState({
          type: "partial",
          trip: res.trip,
          requestId: res.request_id,
          toolActivity: res.tool_activity || res.trip.tool_activity,
          warnings: res.warnings || res.trip.warnings,
          notice,
        });
        setAnnouncement("Itinerary generated with partial warnings.");
      } else if (res.status === "failed") {
        setUiState({
          type: "failed",
          message:
            res.message ||
            "Unable to generate an itinerary. Please check the destination spelling or rephrase your request.",
          requestId: res.request_id,
          toolActivity: res.tool_activity,
        });
        setAnnouncement("Planning failed.");
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (
          err.kind === "network_error" ||
          err.kind === "timeout_error" ||
          err.status === 503
        ) {
          setUiState({
            type: "unreachable",
            message:
              "The backend assistant service is currently unreachable. Please ensure the server is running and try again.",
          });
          setAnnouncement("Backend service is unreachable.");
          return;
        }
        setUiState({
          type: "failed",
          message: err.message || "An unexpected error occurred during planning.",
        });
        setAnnouncement("Planning error.");
        return;
      }

      setUiState({
        type: "failed",
        message:
          err instanceof Error
            ? err.message
            : "An unexpected error occurred during planning.",
      });
      setAnnouncement("Planning error.");
    }
  };

  const handleInitialSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim()) return;

    // Collect any non-empty structured fields into initial known fields
    const initialKnown: Record<string, unknown> = {};
    if (structuredFields.origin.trim()) {
      initialKnown.origin = structuredFields.origin.trim();
    }
    if (structuredFields.destination.trim()) {
      initialKnown.destination = structuredFields.destination.trim();
    }
    if (structuredFields.start_date) {
      initialKnown.start_date = structuredFields.start_date;
    }
    if (structuredFields.end_date) {
      initialKnown.end_date = structuredFields.end_date;
    }
    if (structuredFields.party_size) {
      const ps = parseInt(structuredFields.party_size, 10);
      if (!isNaN(ps) && ps > 0) initialKnown.party_size = ps;
    }
    if (structuredFields.pace) {
      initialKnown.pace = structuredFields.pace;
    }
    if (structuredFields.budget_amount) {
      const b = parseFloat(structuredFields.budget_amount);
      if (!isNaN(b)) initialKnown.budget_amount = b;
    }
    if (structuredFields.currency.trim()) {
      initialKnown.currency = structuredFields.currency.trim();
    }
    if (structuredFields.interests.trim()) {
      initialKnown.interests = structuredFields.interests
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    }

    setKnownFields(initialKnown);
    await executePlanning(message, initialKnown, false);
  };

  const handleClarificationSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Accumulate the newly provided clarification inputs
    const updatedKnown: Record<string, unknown> = { ...knownFields };
    for (const [key, val] of Object.entries(clarificationInputs)) {
      const trimmed = val.trim();
      if (trimmed !== "") {
        if (key === "party_size") {
          const ps = parseInt(trimmed, 10);
          if (!isNaN(ps)) updatedKnown[key] = ps;
        } else if (key === "budget_amount") {
          const b = parseFloat(trimmed);
          if (!isNaN(b)) updatedKnown[key] = b;
        } else if (key === "interests") {
          updatedKnown[key] = trimmed
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
        } else {
          updatedKnown[key] = trimmed;
        }
      }
    }

    setKnownFields(updatedKnown);
    await executePlanning(message, updatedKnown, false);
  };

  const handleRephrase = () => {
    setUiState({ type: "idle" });
    messageInputRef.current?.focus();
  };

  const handleRetry = async () => {
    await executePlanning(message, knownFields, false);
  };

  const handleSaveTrip = async () => {
    if (uiState.type !== "completed" && uiState.type !== "partial") return;

    // If trip already has a saved UUID in DB, navigate directly
    if (
      uiState.trip.id &&
      uiState.trip.id !== "draft" &&
      !uiState.trip.id.startsWith("temp")
    ) {
      router.push(`/trips/${uiState.trip.id}`);
      return;
    }

    setIsSaving(true);
    try {
      const res = await planWithAssistant(message, knownFields, true);
      if (res.trip?.id) {
        router.push(`/trips/${res.trip.id}`);
      } else {
        router.push("/trips");
      }
    } catch {
      setIsSaving(false);
      // Fallback redirect to trips list if direct save call returns error
      router.push("/trips");
    }
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

      {/* Accessible live status announcer for screen readers */}
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>

      <main
        id="main-content"
        className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8"
      >
        {/* Page header */}
        <div className="space-y-2 border-b border-slate-200 dark:border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
              Travel Planning Assistant
            </h1>
            <span className="inline-flex items-center rounded-full bg-blue-100 dark:bg-blue-900/60 px-2.5 py-0.5 text-xs font-semibold text-blue-800 dark:text-blue-200">
              Interactive
            </span>
          </div>
          <p className="text-sm text-slate-600 dark:text-slate-400 max-w-3xl">
            Describe your journey in natural language. Our workflow verifies destinations, checks live meteorological conditions, and synthesizes a balanced, day-by-day travel plan.
          </p>
        </div>

        {/* Input prompt form */}
        <section
          aria-labelledby="assistant-input-heading"
          className="p-6 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs space-y-6"
        >
          <h2 id="assistant-input-heading" className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Tell us about your trip
          </h2>

          <form onSubmit={handleInitialSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label
                htmlFor="assistant-message"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300"
              >
                What kind of trip would you like to plan?
              </label>
              <textarea
                id="assistant-message"
                ref={messageInputRef}
                value={message}
                onChange={handleMessageChange}
                rows={4}
                required
                maxLength={MAX_MESSAGE_LENGTH}
                placeholder="e.g. Plan a 4-day trip to Rome for 2 people interested in history, architecture, and Italian food."
                className="w-full p-3 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent transition-all"
              />
              <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>Natural language query</span>
                <span data-testid="character-counter">
                  {message.length} / {MAX_MESSAGE_LENGTH} characters
                </span>
              </div>
            </div>

            {/* Optional structured fields toggle */}
            <div className="pt-2">
              <button
                type="button"
                onClick={() => setShowStructuredFields(!showStructuredFields)}
                aria-expanded={showStructuredFields}
                aria-controls="optional-structured-fields"
                className="text-xs font-semibold text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1.5"
              >
                <span>{showStructuredFields ? "▼ Hide" : "▶ Show"} optional structured details</span>
              </button>
            </div>

            {showStructuredFields && (
              <div
                id="optional-structured-fields"
                className="p-4 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 text-sm"
              >
                <div>
                  <label htmlFor="field-origin" className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                    Origin (Departure)
                  </label>
                  <input
                    id="field-origin"
                    type="text"
                    value={structuredFields.origin}
                    onChange={(e) => handleStructuredFieldChange("origin", e.target.value)}
                    placeholder="e.g. London"
                    className="w-full px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs text-slate-900 dark:text-slate-100"
                  />
                </div>

                <div>
                  <label htmlFor="field-destination" className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                    Destination
                  </label>
                  <input
                    id="field-destination"
                    type="text"
                    value={structuredFields.destination}
                    onChange={(e) => handleStructuredFieldChange("destination", e.target.value)}
                    placeholder="e.g. Tokyo"
                    className="w-full px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs text-slate-900 dark:text-slate-100"
                  />
                </div>

                <div>
                  <label htmlFor="field-start-date" className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                    Start Date
                  </label>
                  <input
                    id="field-start-date"
                    type="date"
                    value={structuredFields.start_date}
                    onChange={(e) => handleStructuredFieldChange("start_date", e.target.value)}
                    className="w-full px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs text-slate-900 dark:text-slate-100"
                  />
                </div>

                <div>
                  <label htmlFor="field-end-date" className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                    End Date
                  </label>
                  <input
                    id="field-end-date"
                    type="date"
                    value={structuredFields.end_date}
                    onChange={(e) => handleStructuredFieldChange("end_date", e.target.value)}
                    className="w-full px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs text-slate-900 dark:text-slate-100"
                  />
                </div>

                <div>
                  <label htmlFor="field-party-size" className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                    Party Size
                  </label>
                  <input
                    id="field-party-size"
                    type="number"
                    min="1"
                    max="20"
                    value={structuredFields.party_size}
                    onChange={(e) => handleStructuredFieldChange("party_size", e.target.value)}
                    placeholder="2"
                    className="w-full px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs text-slate-900 dark:text-slate-100"
                  />
                </div>

                <div>
                  <label htmlFor="field-pace" className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                    Pace
                  </label>
                  <select
                    id="field-pace"
                    value={structuredFields.pace}
                    onChange={(e) => handleStructuredFieldChange("pace", e.target.value as PacePreference)}
                    className="w-full px-3 py-1.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs text-slate-900 dark:text-slate-100"
                  >
                    <option value="">Default (Balanced)</option>
                    <option value="relaxed">Relaxed</option>
                    <option value="balanced">Balanced</option>
                    <option value="packed">Packed</option>
                  </select>
                </div>
              </div>
            )}

            <div>
              <button
                type="submit"
                disabled={!message.trim() || uiState.type === "loading"}
                className="inline-flex items-center px-5 py-2.5 rounded-md bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold shadow-xs transition-colors"
              >
                {uiState.type === "loading" ? "Planning Trip..." : "Plan with Assistant"}
              </button>
            </div>
          </form>
        </section>

        {/* Loading status */}
        {uiState.type === "loading" && (
          <div
            role="status"
            aria-live="polite"
            data-testid="assistant-loading-state"
            className="p-10 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex items-center justify-center gap-3 text-slate-600 dark:text-slate-400 shadow-xs"
          >
            <span
              className="inline-block h-4 w-4 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none"
              aria-hidden="true"
            />
            <span className="text-sm font-medium">
              Assistant is verifying destinations and consulting meteorological tools...
            </span>
          </div>
        )}

        {/* Backend unreachable error */}
        {uiState.type === "unreachable" && (
          <div
            role="alert"
            data-testid="assistant-unreachable-state"
            className="p-6 rounded-lg border border-rose-200 dark:border-rose-900/60 bg-rose-50/70 dark:bg-rose-950/20 text-rose-950 dark:text-rose-200 space-y-3"
          >
            <h2
              ref={errorHeadingRef}
              tabIndex={-1}
              className="text-base font-semibold outline-none"
            >
              Backend Service Unavailable
            </h2>
            <p className="text-sm text-rose-900/90 dark:text-rose-200/90 leading-relaxed">
              {uiState.message}
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

        {/* Planning failed */}
        {uiState.type === "failed" && (
          <div className="space-y-6">
            <div
              role="alert"
              data-testid="assistant-failed-state"
              className="p-6 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-950/20 text-amber-950 dark:text-amber-200 space-y-4"
            >
              <div className="space-y-1">
                <h2
                  ref={errorHeadingRef}
                  tabIndex={-1}
                  className="text-base font-semibold outline-none"
                >
                  Unable to Generate Itinerary
                </h2>
                <p className="text-sm text-amber-900/90 dark:text-amber-200/90 leading-relaxed">
                  {uiState.message}
                </p>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleRephrase}
                  className="px-3.5 py-1.5 rounded-md bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold shadow-xs transition-colors"
                >
                  Rephrase / Edit Query
                </button>
                <button
                  type="button"
                  onClick={handleRetry}
                  className="px-3.5 py-1.5 rounded-md border border-amber-300 dark:border-amber-800 text-amber-900 dark:text-amber-200 text-xs font-semibold hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
                >
                  Retry
                </button>
              </div>
            </div>

            {/* Show activity panel if any tools executed before failure */}
            {uiState.toolActivity && uiState.toolActivity.length > 0 && (
              <ToolActivityPanel
                activities={uiState.toolActivity}
                requestId={uiState.requestId}
              />
            )}
          </div>
        )}

        {/* Clarification required */}
        {uiState.type === "needs_clarification" && (
          <div className="space-y-6">
            <div
              data-testid="clarification-container"
              role="region"
              aria-labelledby="clarification-heading"
              className="p-6 rounded-lg border border-blue-200 dark:border-blue-900/60 bg-blue-50/70 dark:bg-blue-950/30 space-y-5"
            >
              <div className="space-y-1">
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 dark:bg-blue-900/80 dark:text-blue-200 border border-blue-200 dark:border-blue-800">
                  Clarification Needed
                </span>
                <h2
                  id="clarification-heading"
                  ref={clarificationHeadingRef}
                  tabIndex={-1}
                  className="text-lg font-bold text-slate-900 dark:text-slate-100 outline-none"
                >
                  {uiState.question}
                </h2>
                <p className="text-xs text-slate-600 dark:text-slate-400">
                  Please provide the missing trip parameters to proceed with synthesis.
                </p>
              </div>

              <form onSubmit={handleClarificationSubmit} className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {uiState.missingFields.includes("destination") && (
                    <div>
                      <label
                        htmlFor="clarify-destination"
                        className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
                      >
                        Destination *
                      </label>
                      <input
                        id="clarify-destination"
                        type="text"
                        required
                        value={clarificationInputs.destination || ""}
                        onChange={(e) =>
                          handleClarificationInputChange("destination", e.target.value)
                        }
                        placeholder="e.g. Rome"
                        className="w-full px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100"
                      />
                    </div>
                  )}

                  {uiState.missingFields.includes("origin") && (
                    <div>
                      <label
                        htmlFor="clarify-origin"
                        className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
                      >
                        Departure City (Origin) *
                      </label>
                      <input
                        id="clarify-origin"
                        type="text"
                        required
                        value={clarificationInputs.origin || ""}
                        onChange={(e) =>
                          handleClarificationInputChange("origin", e.target.value)
                        }
                        placeholder="e.g. New York"
                        className="w-full px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100"
                      />
                    </div>
                  )}

                  {uiState.missingFields.includes("start_date") && (
                    <div>
                      <label
                        htmlFor="clarify-start-date"
                        className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
                      >
                        Start Date *
                      </label>
                      <input
                        id="clarify-start-date"
                        type="date"
                        required
                        value={clarificationInputs.start_date || ""}
                        onChange={(e) =>
                          handleClarificationInputChange("start_date", e.target.value)
                        }
                        className="w-full px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100"
                      />
                    </div>
                  )}

                  {uiState.missingFields.includes("end_date") && (
                    <div>
                      <label
                        htmlFor="clarify-end-date"
                        className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
                      >
                        End Date *
                      </label>
                      <input
                        id="clarify-end-date"
                        type="date"
                        required
                        value={clarificationInputs.end_date || ""}
                        onChange={(e) =>
                          handleClarificationInputChange("end_date", e.target.value)
                        }
                        className="w-full px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100"
                      />
                    </div>
                  )}

                  {uiState.missingFields.includes("party_size") && (
                    <div>
                      <label
                        htmlFor="clarify-party-size"
                        className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1"
                      >
                        Party Size *
                      </label>
                      <input
                        id="clarify-party-size"
                        type="number"
                        min="1"
                        max="20"
                        required
                        value={clarificationInputs.party_size || ""}
                        onChange={(e) =>
                          handleClarificationInputChange("party_size", e.target.value)
                        }
                        placeholder="2"
                        className="w-full px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100"
                      />
                    </div>
                  )}

                  {/* Fallback for any other arbitrary missing field */}
                  {uiState.missingFields
                    .filter(
                      (f) =>
                        !["destination", "origin", "start_date", "end_date", "party_size"].includes(
                          f
                        )
                    )
                    .map((otherField) => (
                      <div key={otherField}>
                        <label
                          htmlFor={`clarify-${otherField}`}
                          className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1 capitalize"
                        >
                          {otherField.replace(/_/g, " ")} *
                        </label>
                        <input
                          id={`clarify-${otherField}`}
                          type="text"
                          required
                          value={clarificationInputs[otherField] || ""}
                          onChange={(e) =>
                            handleClarificationInputChange(otherField, e.target.value)
                          }
                          className="w-full px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm text-slate-900 dark:text-slate-100"
                        />
                      </div>
                    ))}
                </div>

                <div className="flex items-center gap-3 pt-2">
                  <button
                    type="submit"
                    className="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold shadow-xs transition-colors"
                  >
                    Submit Clarification &amp; Continue
                  </button>
                </div>
              </form>
            </div>

            {/* Show activity panel if available */}
            {uiState.toolActivity && uiState.toolActivity.length > 0 && (
              <ToolActivityPanel
                activities={uiState.toolActivity}
                requestId={uiState.requestId}
              />
            )}
          </div>
        )}

        {/* Completed or Partial results */}
        {(uiState.type === "completed" || uiState.type === "partial") && (
          <div className="space-y-8" data-testid="assistant-results-view">
            {/* Prominent notice for partial results */}
            {uiState.type === "partial" && (
              <div
                role="alert"
                data-testid="partial-notice-banner"
                className="p-5 rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50/90 dark:bg-amber-950/40 text-amber-950 dark:text-amber-200 space-y-1.5 shadow-xs"
              >
                <div className="flex items-center gap-2 font-bold text-sm">
                  <span aria-hidden="true">⚠️</span>
                  <span>Notice: Partial Itinerary Generated</span>
                </div>
                <p className="text-sm leading-relaxed">
                  {uiState.notice}
                </p>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 dark:border-slate-800 pb-4">
              <div>
                <h2
                  ref={resultsHeadingRef}
                  tabIndex={-1}
                  className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100 outline-none"
                >
                  {uiState.type === "completed"
                    ? "Your Proposed Itinerary"
                    : "Your Proposed Itinerary (Partial)"}
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  Generated with truthfulness guarantees and provenance badges.
                </p>
              </div>
              <button
                type="button"
                onClick={handleSaveTrip}
                disabled={isSaving}
                className="inline-flex items-center px-4 py-2 rounded-md bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-sm font-semibold shadow-xs transition-colors"
              >
                {isSaving ? "Saving..." : "Save this trip"}
              </button>
            </div>

            {/* Summary card */}
            <TripSummaryCard
              request={uiState.trip.request}
              createdAt={uiState.trip.created_at}
            />

            {/* Non-booking disclaimer */}
            <NonBookingDisclaimer />

            {/* Warnings list */}
            {uiState.warnings && uiState.warnings.length > 0 && (
              <WarningsBanner warnings={uiState.warnings} />
            )}

            {/* Weather card */}
            <WeatherCard
              weather={uiState.trip.weather}
              unavailableMessage={
                uiState.warnings?.find((w) =>
                  w.toLowerCase().includes("weather")
                ) || undefined
              }
            />

            {/* Itinerary view with provenance badges */}
            <ItineraryView itinerary={uiState.trip.itinerary} />

            {/* Tool activity panel ("What I checked") */}
            <ToolActivityPanel
              activities={uiState.toolActivity || uiState.trip.tool_activity}
              requestId={uiState.requestId}
            />

            {/* Bottom save button */}
            <div className="pt-4 border-t border-slate-200 dark:border-slate-800 flex justify-end">
              <button
                type="button"
                onClick={handleSaveTrip}
                disabled={isSaving}
                className="inline-flex items-center px-5 py-2.5 rounded-md bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-sm font-semibold shadow-xs transition-colors"
              >
                {isSaving ? "Saving..." : "Save this trip"}
              </button>
            </div>
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
