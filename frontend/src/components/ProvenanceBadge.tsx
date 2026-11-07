import React from "react";
import type { Provenance } from "@/lib/types/trip";

interface ProvenanceBadgeProps {
  provenance: Provenance | string;
}

interface BadgeConfig {
  label: string;
  symbol: string;
  description: string;
  classes: string;
}

const BADGE_CONFIGS: Record<Provenance, BadgeConfig> = {
  retrieved: {
    label: "[Retrieved]",
    symbol: "✓",
    description: "Authoritative external provider fact",
    classes:
      "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300",
  },
  generated_suggestion: {
    label: "[Suggestion]",
    symbol: "✦",
    description: "Generated travel planning suggestion",
    classes:
      "border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300",
  },
  estimate: {
    label: "[Estimate]",
    symbol: "~",
    description: "Calculated time or cost estimate",
    classes:
      "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300",
  },
  unknown: {
    label: "[Unknown]",
    symbol: "?",
    description: "Unverified or undetermined value",
    classes:
      "border-slate-300 bg-slate-100 text-slate-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300",
  },
};

const DEFAULT_CONFIG: BadgeConfig = {
  label: "[Unknown]",
  symbol: "?",
  description: "Unverified value",
  classes:
    "border-slate-300 bg-slate-100 text-slate-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300",
};

/**
 * Provenance badge component displaying data origin classification.
 * Uses explicit text labels and symbols to ensure readability without relying on color alone.
 */
export function ProvenanceBadge({
  provenance,
}: ProvenanceBadgeProps): React.ReactElement {
  const config =
    (BADGE_CONFIGS as Record<string, BadgeConfig>)[provenance] ||
    DEFAULT_CONFIG;

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold border ${config.classes}`}
      title={config.description}
      aria-label={`Provenance: ${config.label}`}
    >
      <span aria-hidden="true" className="font-mono">
        {config.symbol}
      </span>
      <span>{config.label}</span>
    </span>
  );
}

export default ProvenanceBadge;
