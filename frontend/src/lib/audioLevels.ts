/**
 * RE-03: pure threshold math for the "low audio" warning, kept separate
 * from `useAudioRecorder.ts` so it's testable without a real AnalyserNode.
 */

export const LOW_INPUT_LEVEL_THRESHOLD = 0.08;
export const LOW_INPUT_LEVEL_WARNING_SECONDS = 5;
/** EMA weight for mic level (~0.2 ≈ 5 frames at 60fps); reduces bin spikes resetting RE-03. */
export const INPUT_LEVEL_SMOOTHING_ALPHA = 0.2;

export function isLevelLow(level: number, threshold: number = LOW_INPUT_LEVEL_THRESHOLD): boolean {
  return level < threshold;
}

/** Exponential moving average — first sample passes through unchanged. */
export function smoothInputLevel(
  previous: number,
  next: number,
  alpha: number = INPUT_LEVEL_SMOOTHING_ALPHA,
): number {
  if (previous === 0 && next > 0) return next;
  return alpha * next + (1 - alpha) * previous;
}

/** True once the signal has stayed below the threshold for long enough to be worth interrupting the user about. */
export function shouldWarnLowLevel(
  consecutiveLowSeconds: number,
  thresholdSeconds: number = LOW_INPUT_LEVEL_WARNING_SECONDS,
): boolean {
  return consecutiveLowSeconds >= thresholdSeconds;
}
