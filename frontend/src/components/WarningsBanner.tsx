import React from "react";

interface WarningsBannerProps {
  warnings: string[];
}

export function WarningsBanner({
  warnings,
}: WarningsBannerProps): React.ReactElement | null {
  if (!warnings || warnings.length === 0) {
    return null;
  }

  return (
    <section
      aria-labelledby="planning-warnings-heading"
      className="p-4 sm:p-5 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-950/20 text-amber-950 dark:text-amber-200 space-y-2"
    >
      <div className="flex items-center gap-2">
        <span
          className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-amber-200 dark:bg-amber-900 text-amber-900 dark:text-amber-100 font-bold text-xs"
          aria-hidden="true"
        >
          !
        </span>
        <h2
          id="planning-warnings-heading"
          className="text-sm font-semibold tracking-wide uppercase"
        >
          Planning Notices & Warnings
        </h2>
      </div>
      <ul className="space-y-1.5 pl-6 list-disc text-xs sm:text-sm text-amber-900/90 dark:text-amber-200/90">
        {warnings.map((warning, index) => (
          <li key={index} className="leading-relaxed">
            {warning}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default WarningsBanner;
