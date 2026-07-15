import { describe, expect, it } from "vitest";
import {
  INPUT_LEVEL_SMOOTHING_ALPHA,
  LOW_INPUT_LEVEL_THRESHOLD,
  isLevelLow,
  shouldWarnLowLevel,
  smoothInputLevel,
} from "./audioLevels";

describe("isLevelLow", () => {
  it("is true below the threshold", () => {
    expect(isLevelLow(0.01)).toBe(true);
  });

  it("is false at or above the threshold", () => {
    expect(isLevelLow(LOW_INPUT_LEVEL_THRESHOLD)).toBe(false);
    expect(isLevelLow(0.5)).toBe(false);
  });

  it("respects a custom threshold", () => {
    expect(isLevelLow(0.2, 0.3)).toBe(true);
    expect(isLevelLow(0.4, 0.3)).toBe(false);
  });

  it("treats typical quiet-room noise below 0.08 as low", () => {
    expect(isLevelLow(0.069)).toBe(true);
  });
});

describe("smoothInputLevel", () => {
  it("passes the first non-zero sample through unchanged", () => {
    expect(smoothInputLevel(0, 0.4)).toBe(0.4);
  });

  it("applies EMA smoothing on subsequent samples", () => {
    const first = smoothInputLevel(0, 0.4);
    const second = smoothInputLevel(first, 0.2);
    expect(second).toBeCloseTo(INPUT_LEVEL_SMOOTHING_ALPHA * 0.2 + (1 - INPUT_LEVEL_SMOOTHING_ALPHA) * 0.4, 5);
  });
});

describe("shouldWarnLowLevel", () => {
  it("does not warn before the default 5s window elapses", () => {
    expect(shouldWarnLowLevel(4.9)).toBe(false);
  });

  it("warns once the window has elapsed", () => {
    expect(shouldWarnLowLevel(5)).toBe(true);
    expect(shouldWarnLowLevel(10)).toBe(true);
  });

  it("respects a custom window", () => {
    expect(shouldWarnLowLevel(2, 3)).toBe(false);
    expect(shouldWarnLowLevel(3, 3)).toBe(true);
  });
});
