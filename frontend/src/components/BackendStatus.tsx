"use client";

import React, { useEffect, useState } from "react";
import { ApiError } from "@/lib/api/client";
import {
  getHealth,
  getVersion,
  type HealthStatus,
  type VersionInfo,
} from "@/lib/api/health";

type StatusState =
  | { type: "checking" }
  | { type: "connected"; health: HealthStatus; version: VersionInfo }
  | { type: "unreachable"; message: string }
  | { type: "unexpected-response"; message: string };

export function BackendStatus(): React.ReactElement {
  const [state, setState] = useState<StatusState>({ type: "checking" });
  const [retryTrigger, setRetryTrigger] = useState(0);

  useEffect(() => {
    let ignore = false;

    async function checkStatus() {
      try {
        const [health, version] = await Promise.all([getHealth(), getVersion()]);
        if (!ignore) {
          setState({ type: "connected", health, version });
        }
      } catch (err: unknown) {
        if (ignore) {
          return;
        }

        if (err instanceof ApiError) {
          if (err.kind === "timeout_error" || err.kind === "network_error") {
            setState({
              type: "unreachable",
              message:
                "Unable to connect to the backend API service. Please check your network connection or verify that the server is running on port 8000.",
            });
            return;
          }
          if (err.kind === "invalid_json" || err.kind === "http_error") {
            setState({
              type: "unexpected-response",
              message:
                "The backend service answered, but the response was invalid or returned an error status.",
            });
            return;
          }
        }

        if (err instanceof Error && err.message.startsWith("Invalid ")) {
          setState({
            type: "unexpected-response",
            message:
              "The backend service answered, but the payload did not match the expected schema.",
          });
          return;
        }

        setState({
          type: "unreachable",
          message:
            "Unable to reach the backend API service. Please ensure the server is active.",
        });
      }
    }

    void checkStatus();

    return () => {
      ignore = true;
    };
  }, [retryTrigger]);

  const handleRetry = () => {
    setState({ type: "checking" });
    setRetryTrigger((count) => count + 1);
  };

  if (state.type === "checking") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="p-4 sm:p-5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/40 text-slate-700 dark:text-slate-300 flex items-center gap-3"
      >
        <span
          className="inline-block h-3 w-3 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none"
          aria-hidden="true"
        />
        <span className="text-sm font-medium">
          Checking backend connection status...
        </span>
      </div>
    );
  }

  if (state.type === "connected") {
    return (
      <div className="p-4 sm:p-5 rounded-lg border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50/60 dark:bg-emerald-950/20 text-emerald-950 dark:text-emerald-200 space-y-3">
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-600 dark:bg-emerald-400"
            aria-hidden="true"
          />
          <span className="text-sm font-semibold tracking-wide">
            Connected to Backend Service
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs sm:text-sm text-slate-700 dark:text-slate-300 pt-1 border-t border-emerald-200/60 dark:border-emerald-900/40">
          <div>
            <span className="font-medium text-slate-500 dark:text-slate-400">
              Service Status:{" "}
            </span>
            <span className="font-semibold text-emerald-700 dark:text-emerald-300">
              {state.health.status}
            </span>
          </div>
          <div>
            <span className="font-medium text-slate-500 dark:text-slate-400">
              Version:{" "}
            </span>
            <span className="font-mono">{state.version.version}</span>
          </div>
          <div>
            <span className="font-medium text-slate-500 dark:text-slate-400">
              Environment:{" "}
            </span>
            <span className="capitalize">{state.version.environment}</span>
          </div>
        </div>
      </div>
    );
  }

  if (state.type === "unexpected-response") {
    return (
      <div className="p-4 sm:p-5 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50/60 dark:bg-amber-950/20 text-amber-950 dark:text-amber-200 space-y-3">
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full bg-amber-600 dark:bg-amber-400"
            aria-hidden="true"
          />
          <span className="text-sm font-semibold tracking-wide">
            Unexpected Backend Response
          </span>
        </div>
        <p className="text-xs sm:text-sm text-slate-700 dark:text-slate-300">
          {state.message}
        </p>
        <div>
          <button
            type="button"
            onClick={handleRetry}
            className="inline-flex items-center px-3.5 py-1.5 rounded-md text-xs sm:text-sm font-medium bg-slate-900 text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-600 focus:ring-offset-2 dark:focus:ring-offset-slate-900 transition-colors"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-5 rounded-lg border border-rose-200 dark:border-rose-900/60 bg-rose-50/60 dark:bg-rose-950/20 text-rose-950 dark:text-rose-200 space-y-3">
      <div className="flex items-center gap-2">
        <span
          className="inline-block h-2.5 w-2.5 rounded-full bg-rose-600 dark:bg-rose-400"
          aria-hidden="true"
        />
        <span className="text-sm font-semibold tracking-wide">
          Backend Service Unreachable
        </span>
      </div>
      <p className="text-xs sm:text-sm text-slate-700 dark:text-slate-300">
        {state.message}
      </p>
      <div>
        <button
          type="button"
          onClick={handleRetry}
          className="inline-flex items-center px-3.5 py-1.5 rounded-md text-xs sm:text-sm font-medium bg-slate-900 text-white hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-600 focus:ring-offset-2 dark:focus:ring-offset-slate-900 transition-colors"
        >
          Retry Connection
        </button>
      </div>
    </div>
  );
}

export default BackendStatus;
