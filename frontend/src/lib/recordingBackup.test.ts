import { describe, expect, it } from "vitest";
import { assembleRecordingBlob } from "./recordingBackup";

describe("assembleRecordingBlob", () => {
  it("concatenates chunks into a single Blob with the recorded mime type", async () => {
    const chunks = [new Blob(["abc"]), new Blob(["def"])];
    const blob = assembleRecordingBlob({
      startedAt: "2026-07-10T10:00:00.000Z",
      mimeType: "audio/webm;codecs=opus",
      deviceId: null,
      chunks,
    });

    expect(blob.type).toBe("audio/webm;codecs=opus");
    expect(blob.size).toBe(6);
    expect(await blob.text()).toBe("abcdef");
  });

  it("returns an empty Blob for a record with no chunks", async () => {
    const blob = assembleRecordingBlob({
      startedAt: "2026-07-10T10:00:00.000Z",
      mimeType: "audio/webm",
      deviceId: null,
      chunks: [],
    });
    expect(blob.size).toBe(0);
  });
});
