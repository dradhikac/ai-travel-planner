/**
 * Assistant API client methods for natural-language travel planning with tool execution.
 * Aligned with Phase 3 specifications in docs/phase3/architecture.md.
 */

import { apiClient } from "@/lib/api/client";
import type {
  AssistantPlanResponse,
  AssistantRunStatus,
  ToolActivity,
  TripResponse,
} from "@/lib/types/trip";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Validates and normalizes the runtime shape of an assistant planning response.
 */
export function validateAssistantPlanResponse(data: unknown): AssistantPlanResponse {
  if (!isRecord(data)) {
    throw new Error("Invalid assistant response: Expected an object payload");
  }

  // 1. Normalize status
  const rawStatus =
    typeof data.status === "string" ? data.status.trim().toLowerCase() : "";
  let status: AssistantRunStatus;
  if (
    rawStatus === "needs_clarification" ||
    rawStatus === "clarification_required"
  ) {
    status = "needs_clarification";
  } else if (rawStatus === "completed") {
    status = "completed";
  } else if (rawStatus === "partial") {
    status = "partial";
  } else if (rawStatus === "failed") {
    status = "failed";
  } else {
    throw new Error(
      `Invalid assistant response: Unknown execution status '${data.status}'`
    );
  }

  // 2. Request ID
  const requestId =
    typeof data.request_id === "string" && data.request_id.trim()
      ? data.request_id.trim()
      : typeof data.id === "string" && data.id.trim()
      ? data.id.trim()
      : "req_unknown";

  // 3. Clarification details
  let clarificationQuestion: string | null = null;
  if (typeof data.clarification_question === "string") {
    clarificationQuestion = data.clarification_question;
  } else if (
    isRecord(data.clarification) &&
    typeof data.clarification.question === "string"
  ) {
    clarificationQuestion = data.clarification.question;
  }

  let missingFields: string[] = [];
  if (Array.isArray(data.missing_fields)) {
    missingFields = data.missing_fields.filter(
      (f): f is string => typeof f === "string"
    );
  } else if (
    isRecord(data.clarification) &&
    typeof data.clarification.field === "string"
  ) {
    missingFields = [data.clarification.field];
  }

  // 4. Known fields
  const knownFields: Record<string, unknown> = isRecord(data.known_fields)
    ? (data.known_fields as Record<string, unknown>)
    : {};

  // 5. Trip object
  let trip: TripResponse | null = null;
  if (isRecord(data.trip)) {
    trip = data.trip as unknown as TripResponse;
  } else if (isRecord(data.final_response)) {
    trip = data.final_response as unknown as TripResponse;
  } else if (isRecord(data.itinerary) && isRecord(data.request)) {
    trip = data as unknown as TripResponse;
  }

  // 6. Tool activity entries
  const toolActivity: ToolActivity[] = [];
  const rawActivities = Array.isArray(data.tool_activity)
    ? data.tool_activity
    : Array.isArray(data.tool_activities)
    ? data.tool_activities
    : trip && Array.isArray((trip as unknown as Record<string, unknown>).tool_activity)
    ? ((trip as unknown as Record<string, unknown>).tool_activity as unknown[])
    : [];

  for (const item of rawActivities) {
    if (isRecord(item)) {
      toolActivity.push({
        tool_label:
          typeof item.tool_label === "string" ? item.tool_label : "Tool",
        status: typeof item.status === "string" ? item.status : "unknown",
        source: typeof item.source === "string" ? item.source : "",
        fetched_at:
          typeof item.fetched_at === "string" ? item.fetched_at : null,
        data_origin:
          typeof item.data_origin === "string" ? item.data_origin : "none",
        explanation:
          typeof item.explanation === "string" ? item.explanation : "",
      });
    }
  }

  // 7. Warnings
  const warnings: string[] = Array.isArray(data.warnings)
    ? data.warnings.filter((w): w is string => typeof w === "string")
    : trip?.warnings || [];

  // 8. Error or explanation message
  const message =
    typeof data.message === "string"
      ? data.message
      : typeof data.error === "string"
      ? data.error
      : isRecord(data.error) && typeof data.error.message === "string"
      ? data.error.message
      : null;

  return {
    status,
    request_id: requestId,
    trip,
    clarification_question: clarificationQuestion,
    missing_fields: missingFields,
    known_fields: knownFields,
    tool_activity: toolActivity,
    warnings,
    message,
  };
}

/**
 * Invoke the assistant planning workflow with conversational message and accumulated fields.
 *
 * @param message Natural-language travel request prompt
 * @param knownFields Accumulated validated fields from prior clarification turns
 * @param save Whether to persist the generated trip in PostgreSQL
 */
export async function planWithAssistant(
  message: string,
  knownFields: Record<string, unknown> = {},
  save: boolean = false
): Promise<AssistantPlanResponse> {
  const cleanMessage = message ? message.trim() : "";
  if (!cleanMessage) {
    throw new Error("Message is required for assistant planning");
  }

  const queryParams = new URLSearchParams();
  if (save) {
    queryParams.set("save", "true");
  }
  const queryString = queryParams.toString();
  const endpoint = `/api/agent/plan${queryString ? `?${queryString}` : ""}`;

  const payload = {
    message: cleanMessage,
    query: cleanMessage,
    user_message: cleanMessage,
    known_fields: knownFields,
    save,
  };

  const rawData = await apiClient<unknown>(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return validateAssistantPlanResponse(rawData);
}
