const PREFIX = "[scribe-audio]";

export function isAudioDebugEnabled(): boolean {
  return import.meta.env.DEV || import.meta.env.VITE_DEBUG_AUDIO === "true";
}

export function audioDebugLog(message: string, data?: Record<string, unknown>): void {
  if (!isAudioDebugEnabled()) return;
  if (data === undefined) {
    console.info(`${PREFIX} ${message}`);
    return;
  }
  console.info(`${PREFIX} ${message}`, data);
}

const loggedOnce = new Set<string>();

/** Logs a message once per page load (useful for capability checks). */
export function audioDebugLogOnce(key: string, message: string, data?: Record<string, unknown>): void {
  if (!isAudioDebugEnabled() || loggedOnce.has(key)) return;
  loggedOnce.add(key);
  audioDebugLog(message, data);
}
