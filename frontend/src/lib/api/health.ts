/**
 * Health and version API client methods with runtime payload validation.
 */

import { apiClient } from "@/lib/api/client";

export interface HealthStatus {
  readonly status: string;
}

export interface VersionInfo {
  readonly name: string;
  readonly version: string;
  readonly environment: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validates the runtime shape of the health response payload.
 */
export function validateHealthResponse(data: unknown): HealthStatus {
  if (!isRecord(data)) {
    throw new Error("Invalid health response: Expected an object payload");
  }
  if (typeof data.status !== "string" || !data.status.trim()) {
    throw new Error(
      "Invalid health response: Missing or empty 'status' string"
    );
  }
  return {
    status: data.status,
  };
}

/**
 * Validates the runtime shape of the version response payload.
 */
export function validateVersionResponse(data: unknown): VersionInfo {
  if (!isRecord(data)) {
    throw new Error("Invalid version response: Expected an object payload");
  }
  if (typeof data.name !== "string" || !data.name.trim()) {
    throw new Error("Invalid version response: Missing or empty 'name' string");
  }
  if (typeof data.version !== "string" || !data.version.trim()) {
    throw new Error(
      "Invalid version response: Missing or empty 'version' string"
    );
  }
  if (typeof data.environment !== "string" || !data.environment.trim()) {
    throw new Error(
      "Invalid version response: Missing or empty 'environment' string"
    );
  }
  return {
    name: data.name,
    version: data.version,
    environment: data.environment,
  };
}

/**
 * Fetch health status from backend /health endpoint.
 */
export async function getHealth(): Promise<HealthStatus> {
  const data = await apiClient<unknown>("/health");
  return validateHealthResponse(data);
}

/**
 * Fetch version and environment metadata from backend /api/version endpoint.
 */
export async function getVersion(): Promise<VersionInfo> {
  const data = await apiClient<unknown>("/api/version");
  return validateVersionResponse(data);
}
