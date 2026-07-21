import { describe, expect, it } from "vitest";
import {
  CAPTURE_WORKLET_NAME,
  concatFloat32,
  createCaptureWorkletModuleUrl,
  float32ToPCM16,
  resampleLinear,
} from "./realtimeAudioCapture";

describe("float32ToPCM16", () => {
  it("converts full-scale positive and negative samples to int16 extremes", () => {
    const buffer = float32ToPCM16(new Float32Array([1, -1, 0]));
    const view = new DataView(buffer);
    expect(view.getInt16(0, true)).toBe(0x7fff);
    expect(view.getInt16(2, true)).toBe(-0x8000);
    expect(view.getInt16(4, true)).toBe(0);
  });

  it("clamps out-of-range samples instead of wrapping", () => {
    const buffer = float32ToPCM16(new Float32Array([1.5, -1.5]));
    const view = new DataView(buffer);
    expect(view.getInt16(0, true)).toBe(0x7fff);
    expect(view.getInt16(2, true)).toBe(-0x8000);
  });

  it("produces 2 bytes per input sample", () => {
    const buffer = float32ToPCM16(new Float32Array(10));
    expect(buffer.byteLength).toBe(20);
  });
});

describe("resampleLinear", () => {
  it("returns the same array when rates already match", () => {
    const input = new Float32Array([1, 2, 3]);
    expect(resampleLinear(input, 16000, 16000)).toBe(input);
  });

  it("halves the sample count when downsampling by 2x", () => {
    const input = new Float32Array(320); // e.g. 20ms at 16kHz
    const output = resampleLinear(input, 32000, 16000);
    expect(output.length).toBe(160);
  });

  it("downsamples 44100 -> 16000 to approximately the expected ratio", () => {
    const input = new Float32Array(44100); // 1 second at native rate
    const output = resampleLinear(input, 44100, 16000);
    expect(output.length).toBeCloseTo(16000, -2); // within ~100 samples
  });

  it("interpolates between neighboring samples rather than just nearest-picking", () => {
    // A straight ramp 0..1 downsampled should stay monotonic and stay within range.
    const input = Float32Array.from({ length: 100 }, (_, i) => i / 99);
    const output = resampleLinear(input, 100, 50);
    for (let i = 1; i < output.length; i += 1) {
      expect(output[i]).toBeGreaterThanOrEqual(output[i - 1]);
    }
    expect(output[0]).toBeGreaterThanOrEqual(0);
    expect(output[output.length - 1]).toBeLessThanOrEqual(1);
  });

  it("handles an empty input without dividing by zero", () => {
    expect(resampleLinear(new Float32Array(0), 44100, 16000).length).toBe(0);
  });
});

describe("concatFloat32", () => {
  it("concatenates multiple chunks in order", () => {
    const result = concatFloat32([new Float32Array([1, 2]), new Float32Array([3]), new Float32Array([4, 5])]);
    expect(Array.from(result)).toEqual([1, 2, 3, 4, 5]);
  });

  it("returns an empty array for no chunks", () => {
    expect(concatFloat32([]).length).toBe(0);
  });
});

describe("createCaptureWorkletModuleUrl", () => {
  it("produces a blob: URL", () => {
    const url = createCaptureWorkletModuleUrl();
    expect(url).toMatch(/^blob:/);
  });

  it("registers the processor under CAPTURE_WORKLET_NAME", async () => {
    const url = createCaptureWorkletModuleUrl();
    const response = await fetch(url);
    const source = await response.text();
    expect(source).toContain(`registerProcessor("${CAPTURE_WORKLET_NAME}"`);
  });
});
