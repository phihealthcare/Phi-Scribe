import { ApiRequestError } from "./client";

/**
 * Non-throwing counterpart to the ApiRequestError-throwing functions in
 * `audio.ts`. Prefer the throwing versions for imperative flows (e.g. inside
 * a try/catch during Fase 3 UI wiring); use `ApiResult` when the caller wants
 * to branch on success/failure without exceptions.
 */
export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string; status?: number };

export async function toApiResult<T>(promise: Promise<T>): Promise<ApiResult<T>> {
  try {
    const data = await promise;
    return { ok: true, data };
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return { ok: false, error: error.message, status: error.status };
    }
    if (error instanceof Error) {
      return { ok: false, error: error.message };
    }
    return { ok: false, error: "Unknown error" };
  }
}
