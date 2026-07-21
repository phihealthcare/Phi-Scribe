import { describe, expect, it } from "vitest";
import type { TranscriptSegment } from "../api/types";
import { applySegmentEvent } from "./useRealtimeTranscription";

describe("applySegmentEvent", () => {
  it("appends a new partial segment", () => {
    const result = applySegmentEvent([], {
      type: "partial",
      start_ms: 0,
      end_ms: 1000,
      text: "Olá",
      speaker_label: null,
    });
    expect(result).toEqual([{ start_ms: 0, end_ms: 1000, text: "Olá" }]);
  });

  it("replaces a partial with a final for the same start_ms in place, not appended", () => {
    const withPartial = applySegmentEvent([], {
      type: "partial",
      start_ms: 0,
      end_ms: 800,
      text: "Olá dout",
      speaker_label: null,
    });
    const withFinal = applySegmentEvent(withPartial, {
      type: "final",
      start_ms: 0,
      end_ms: 1000,
      text: "Olá doutor",
      speaker_label: null,
    });
    expect(withFinal).toHaveLength(1);
    expect(withFinal[0]).toEqual({ start_ms: 0, end_ms: 1000, text: "Olá doutor" });
  });

  it("keeps segments in append order for distinct start_ms values", () => {
    const first = applySegmentEvent([], {
      type: "final",
      start_ms: 0,
      end_ms: 1000,
      text: "Primeiro",
      speaker_label: null,
    });
    const second = applySegmentEvent(first, {
      type: "final",
      start_ms: 1000,
      end_ms: 2000,
      text: "Segundo",
      speaker_label: null,
    });
    expect(second.map((s) => s.text)).toEqual(["Primeiro", "Segundo"]);
  });

  it("includes speaker_label only when the server provided one", () => {
    const withLabel = applySegmentEvent([], {
      type: "final",
      start_ms: 0,
      end_ms: 1000,
      text: "texto",
      speaker_label: "Médico",
    });
    expect(withLabel[0]).toEqual({ start_ms: 0, end_ms: 1000, text: "texto", speaker_label: "Médico" });

    const withoutLabel = applySegmentEvent([], {
      type: "final",
      start_ms: 0,
      end_ms: 1000,
      text: "texto",
      speaker_label: null,
    });
    expect(withoutLabel[0]).not.toHaveProperty("speaker_label");
  });

  it("patches speaker/speaker_label onto every segment whose start_ms falls inside the turn's span", () => {
    const segments = [
      { start_ms: 0, end_ms: 1000, text: "a" },
      { start_ms: 1000, end_ms: 2000, text: "b" },
      { start_ms: 2000, end_ms: 3000, text: "c" },
    ];
    const result = applySegmentEvent(segments, {
      type: "speaker_update",
      start_ms: 0,
      end_ms: 2000,
      speaker: "speaker_G0",
    });
    expect(result[0].speaker_label).toBe("speaker_G0");
    expect(result[1].speaker_label).toBe("speaker_G0");
    expect(result[2].speaker_label).toBeUndefined();
  });

  it("does not mutate the input array", () => {
    const segments: TranscriptSegment[] = [{ start_ms: 0, end_ms: 1000, text: "a" }];
    Object.freeze(segments);
    expect(() =>
      applySegmentEvent(segments, { type: "final", start_ms: 0, end_ms: 1000, text: "b", speaker_label: null }),
    ).not.toThrow();
  });
});
