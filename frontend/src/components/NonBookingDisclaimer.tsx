import React from "react";

export function NonBookingDisclaimer(): React.ReactElement {
  return (
    <aside
      aria-label="Planning Boundary Notice"
      className="p-4 sm:p-5 rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50/80 dark:bg-amber-950/30 text-amber-950 dark:text-amber-200 space-y-2"
    >
      <div className="flex items-center gap-2">
        <span
          className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-amber-200 dark:bg-amber-900 text-amber-900 dark:text-amber-100 font-bold text-xs"
          aria-hidden="true"
        >
          !
        </span>
        <h2 className="text-sm font-semibold tracking-wide uppercase">
          Planning Itinerary — Not a Booking
        </h2>
      </div>
      <p className="text-xs sm:text-sm leading-relaxed text-amber-900/90 dark:text-amber-200/90">
        AI Travel Concierge is strictly a research and planning assistant.{" "}
        <strong>No bookings, reservations, ticketing, or payment transactions have occurred.</strong>{" "}
        No provider prices were retrieved; any cost estimates displayed are hypothetical approximations.
      </p>
    </aside>
  );
}

export default NonBookingDisclaimer;
