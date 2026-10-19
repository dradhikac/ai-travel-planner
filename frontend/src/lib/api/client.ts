/**
 * Typed HTTP client wrapper for backend API communication.
 */

import { config } from "@/lib/config";

export type ApiErrorKind =
  | "network_error"
  | "timeout_error"
  | "http_error"
  | "invalid_json";

export interface StandardErrorPayload {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(
    kind: ApiErrorKind,
    message: string,
    options?: { status?: number; code?: string; details?: unknown; cause?: unknown }
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options?.status;
    this.code = options?.code;
    this.details = options?.details;
    if (options?.cause) {
      this.cause = options?.cause;
    }
  }
}

export interface RequestOptions extends Omit<RequestInit, "signal"> {
  timeoutMs?: number;
}

/**
 * Perform a typed HTTP request against the backend API with a 5-second default timeout.
 */
export async function apiClient<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { timeoutMs = 5000, headers, ...restOptions } = options;

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const targetUrl = `${config.apiBaseUrl}${normalizedPath}`;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  let response: Response;
  try {
    response = await fetch(targetUrl, {
      ...restOptions,
      headers: {
        Accept: "application/json",
        ...headers,
      },
      signal: controller.signal,
    });
  } catch (err: unknown) {
    if (controller.signal.aborted) {
      throw new ApiError(
        "timeout_error",
        `Request to ${normalizedPath} timed out after ${timeoutMs}ms`,
        { cause: err }
      );
    }
    if (err instanceof TypeError) {
      throw new ApiError(
        "network_error",
        `Network error: Unable to reach backend at ${targetUrl}`,
        { cause: err }
      );
    }
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(
      "network_error",
      err instanceof Error ? err.message : "Unexpected fetch error",
      { cause: err }
    );
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    let errorPayload: StandardErrorPayload | null = null;
    try {
      errorPayload = (await response.json()) as StandardErrorPayload;
    } catch {
      // Body is not JSON or empty
    }

    const message =
      errorPayload?.error?.message ??
      `HTTP error ${response.status}: ${response.statusText || "Request failed"}`;
    const code = errorPayload?.error?.code ?? `http_${response.status}`;
    const details = errorPayload?.error?.details;

    throw new ApiError("http_error", message, {
      status: response.status,
      code,
      details,
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  try {
    return (await response.json()) as T;
  } catch (parseErr: unknown) {
    throw new ApiError(
      "invalid_json",
      `Invalid JSON received from ${normalizedPath}`,
      { status: response.status, cause: parseErr }
    );
  }
}
