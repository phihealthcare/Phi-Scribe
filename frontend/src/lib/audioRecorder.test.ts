import { describe, expect, it } from "vitest";
import {
  MicError,
  blobToUploadFile,
  computeInputLevel,
  computeInputLevelFromTimeDomain,
  extensionForMimeType,
  formatElapsed,
  mapMicError,
  pickSupportedMimeType,
} from "./audioRecorder";

describe("mapMicError", () => {
  it("maps NotAllowedError to a denied MicError", () => {
    const mapped = mapMicError(new DOMException("blocked", "NotAllowedError"));
    expect(mapped).toBeInstanceOf(MicError);
    expect(mapped.code).toBe("denied");
  });

  it("maps NotFoundError to not_found", () => {
    expect(mapMicError(new DOMException("no device", "NotFoundError")).code).toBe("not_found");
  });

  it("maps NotReadableError to busy", () => {
    expect(mapMicError(new DOMException("in use", "NotReadableError")).code).toBe("busy");
  });

  it("maps an unrecognized DOMException to unknown", () => {
    expect(mapMicError(new DOMException("???", "SomeWeirdError")).code).toBe("unknown");
  });

  it("passes an existing MicError through unchanged", () => {
    const original = new MicError("unsupported", "no MediaRecorder");
    expect(mapMicError(original)).toBe(original);
  });

  it("wraps a plain Error as unknown", () => {
    const mapped = mapMicError(new Error("boom"));
    expect(mapped.code).toBe("unknown");
    expect(mapped.message).toBe("boom");
  });

  it("falls back to a generic message for non-Error throwables", () => {
    expect(mapMicError("nope").code).toBe("unknown");
  });
});

describe("pickSupportedMimeType", () => {
  it("returns the first candidate reported as supported", () => {
    const isTypeSupported = (type: string) => type === "audio/mp4";
    expect(pickSupportedMimeType(isTypeSupported)).toBe("audio/mp4");
  });

  it("prefers webm;codecs=opus over plain webm or mp4", () => {
    const isTypeSupported = () => true;
    expect(pickSupportedMimeType(isTypeSupported)).toBe("audio/webm;codecs=opus");
  });

  it("returns undefined when nothing is supported", () => {
    expect(pickSupportedMimeType(() => false)).toBeUndefined();
  });
});

describe("extensionForMimeType", () => {
  it.each([
    ["audio/webm;codecs=opus", "webm"],
    ["audio/webm", "webm"],
    ["audio/mp4", "mp4"],
    ["audio/aac", "mp4"],
    ["audio/wav", "wav"],
    ["audio/mpeg", "mp3"],
  ])("maps %s to %s", (mimeType, expected) => {
    expect(extensionForMimeType(mimeType)).toBe(expected);
  });

  it("returns null for an unrecognized mime type", () => {
    expect(extensionForMimeType("audio/ogg")).toBeNull();
  });
});

describe("blobToUploadFile", () => {
  it("builds a File with the right extension and mime type", () => {
    const blob = new Blob(["fake audio bytes"], { type: "audio/webm" });
    const file = blobToUploadFile(blob, "audio/webm;codecs=opus");
    expect(file.name).toMatch(/^consulta-gravada-.*\.webm$/);
    expect(file.type).toBe("audio/webm;codecs=opus");
  });

  it("throws MicError('unsupported') for a mime type with no known extension", () => {
    const blob = new Blob(["x"], { type: "audio/ogg" });
    expect(() => blobToUploadFile(blob, "audio/ogg")).toThrow(MicError);
    try {
      blobToUploadFile(blob, "audio/ogg");
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(MicError);
      expect((err as MicError).code).toBe("unsupported");
    }
  });
});

describe("computeInputLevelFromTimeDomain", () => {
  it("returns 0 for a flat silence line at 128", () => {
    expect(computeInputLevelFromTimeDomain(new Uint8Array([128, 128, 128, 128]))).toBe(0);
  });

  it("returns close to 1 for a max-amplitude square wave", () => {
    expect(computeInputLevelFromTimeDomain(new Uint8Array([0, 255, 0, 255]))).toBeCloseTo(1, 2);
  });

  it("returns a value proportional to RMS deviation", () => {
    const level = computeInputLevelFromTimeDomain(new Uint8Array([118, 138, 118, 138]));
    expect(level).toBeGreaterThan(0);
    expect(level).toBeLessThan(0.2);
  });

  it("returns 0 for an empty array", () => {
    expect(computeInputLevelFromTimeDomain(new Uint8Array([]))).toBe(0);
  });
});

describe("computeInputLevel", () => {
  it("returns 0 for silence", () => {
    expect(computeInputLevel(new Uint8Array([0, 0, 0, 0]))).toBe(0);
  });

  it("returns close to 1 for a maxed-out signal", () => {
    expect(computeInputLevel(new Uint8Array([255, 255, 255, 255]))).toBe(1);
  });

  it("returns a value proportional to the average", () => {
    expect(computeInputLevel(new Uint8Array([127, 127]))).toBeCloseTo(127 / 255, 5);
  });

  it("returns 0 for an empty array instead of dividing by zero", () => {
    expect(computeInputLevel(new Uint8Array([]))).toBe(0);
  });
});

describe("formatElapsed", () => {
  it("formats seconds as MM:SS", () => {
    expect(formatElapsed(0)).toBe("00:00");
    expect(formatElapsed(5)).toBe("00:05");
    expect(formatElapsed(65)).toBe("01:05");
    expect(formatElapsed(724)).toBe("12:04");
  });

  it("clamps negative values to zero", () => {
    expect(formatElapsed(-3)).toBe("00:00");
  });
});
