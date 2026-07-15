import type { ApiError } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:5000/api/v1/audio";

/**
 * `status` is 0 for errors that never got an HTTP response (network failure,
 * request aborted/timed out) — callers can use that to distinguish "server
 * said no" from "request never completed".
 */
export class ApiRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

function isApiError(value: unknown): value is ApiError {
  return typeof value === "object" && value !== null && "error" in value && typeof (value as ApiError).error === "string";
}

interface ApiPostOptions {
  body?: FormData;
  /**
   * `/{file_id}/transcribe` can run for minutes on real audio (ASR +
   * postprocess + SOAP draft generation are all synchronous on the backend).
   * Pass a generous timeout (e.g. 15-30 min) for that call; leave unset for
   * fast endpoints like `/upload`.
   */
  timeoutMs?: number;
}

export async function apiPost<T>(path: string, options: ApiPostOptions = {}): Promise<T> {
  const { body, timeoutMs } = options;

  const controller = new AbortController();
  const timeoutId = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : undefined;

  let response: Response;
  try {
    // No Content-Type header here on purpose: for FormData bodies the
    // browser must set it itself (including the multipart boundary).
    response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      body,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiRequestError(`Request to ${path} timed out after ${timeoutMs}ms`, 0);
    }
    const message = error instanceof Error ? error.message : "Network error";
    throw new ApiRequestError(`Failed to reach the API: ${message}`, 0);
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiRequestError(
      `Expected JSON from ${path} but got an unparseable response (status ${response.status})`,
      response.status,
    );
  }

  if (!response.ok || isApiError(data)) {
    const message = isApiError(data) ? data.error : `Request failed with status ${response.status}`;
    throw new ApiRequestError(message, response.status);
  }

  return data as T;
}
