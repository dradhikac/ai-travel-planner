import React from "react";
import Link from "next/link";

export function Navbar(): React.ReactElement {
  return (
    <header className="border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm sticky top-0 z-40">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link
            href="/"
            className="font-semibold text-lg tracking-tight text-slate-900 dark:text-slate-50 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
          >
            AI Travel Concierge
          </Link>
          <nav aria-label="Main Navigation" className="flex items-center gap-4 text-sm font-medium">
            <Link
              href="/plan"
              className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
            >
              Plan Trip
            </Link>
            <Link
              href="/trips"
              className="text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
            >
              Saved Trips
            </Link>
          </nav>
        </div>
        <span className="inline-flex items-center rounded-full bg-blue-50 dark:bg-blue-950/60 px-2.5 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
          Phase 2
        </span>
      </div>
    </header>
  );
}

export default Navbar;
