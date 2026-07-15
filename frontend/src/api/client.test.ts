import { afterEach, describe, expect, it, vi } from "vitest";
import { apiPost, ApiRequestError } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("apiPost", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns parsed JSON on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ file_id: "abc" })));

    const result = await apiPost<{ file_id: string }>("/upload");
    expect(result).toEqual({ file_id: "abc" });
  });

  it("throws ApiRequestError when the JSON body has an error field, even on 200", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: "Invalid file type" }, 200)));

    await expect(apiPost("/upload")).rejects.toMatchObject({
      message: "Invalid file type",
      status: 200,
    });
  });

  it("throws ApiRequestError with the response status on non-2xx", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: "Transcription failed" }, 500)));

    await expect(apiPost("/some-id/transcribe")).rejects.toBeInstanceOf(ApiRequestError);
    await expect(apiPost("/some-id/transcribe")).rejects.toMatchObject({ status: 500 });
  });

  it("throws a clear ApiRequestError on unparseable (non-JSON) responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>502 Bad Gateway</html>", { status: 502 })),
    );

    await expect(apiPost("/upload")).rejects.toThrow(/unparseable response/);
  });

  it("throws a clear ApiRequestError on network failure (status 0)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiPost("/upload")).rejects.toMatchObject({
      status: 0,
    });
    await expect(apiPost("/upload")).rejects.toThrow(/Failed to reach the API/);
  });
});
