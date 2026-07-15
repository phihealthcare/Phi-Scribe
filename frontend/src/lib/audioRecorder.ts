/**
 * Pure/stateless pieces of live microphone recording — kept separate from
 * `useAudioRecorder.ts` (which owns the actual MediaRecorder/AudioContext
 * instances and React state) so the mapping/formatting logic is testable
 * without a real browser.
 */

export type RecorderStatus = "idle" | "requesting" | "recording" | "paused" | "error";

export type MicErrorCode = "denied" | "not_found" | "busy" | "unsupported" | "unknown";

export class MicError extends Error {
  code: MicErrorCode;

  constructor(code: MicErrorCode, message: string) {
    super(message);
    this.name = "MicError";
    this.code = code;
  }
}

/** Maps getUserMedia/MediaRecorder failures to a typed, pt-BR-messaged MicError. */
export function mapMicError(err: unknown): MicError {
  if (err instanceof MicError) {
    return err;
  }

  if (err instanceof DOMException) {
    switch (err.name) {
      case "NotAllowedError":
      case "PermissionDeniedError":
      case "SecurityError":
        return new MicError("denied", "Permissão de microfone negada.");
      case "NotFoundError":
      case "DevicesNotFoundError":
        return new MicError("not_found", "Nenhum microfone encontrado.");
      case "NotReadableError":
      case "TrackStartError":
        return new MicError("busy", "Não foi possível acessar o microfone. Ele pode estar em uso por outro aplicativo.");
      default:
        return new MicError("unknown", err.message || "Erro desconhecido ao acessar o microfone.");
    }
  }

  if (err instanceof Error) {
    return new MicError("unknown", err.message);
  }

  return new MicError("unknown", "Erro desconhecido ao acessar o microfone.");
}

/**
 * Priority: `webm;codecs=opus` (Chrome/Firefox/Edge default), then plain
 * `webm`, then `mp4` (Safari). Both `webm` and `mp4` are accepted by the
 * backend today (`app/routes/audio.py` — `webm` added alongside this
 * feature). Returns undefined if none are supported, in which case the
 * caller falls back to the browser's own MediaRecorder default.
 */
const CANDIDATE_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

export function pickSupportedMimeType(
  isTypeSupported: (type: string) => boolean = (type) =>
    typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(type),
): string | undefined {
  return CANDIDATE_MIME_TYPES.find((type) => isTypeSupported(type));
}

/** Only covers formats the backend accepts (see ALLOWED_EXTENSIONS in app/routes/audio.py). */
export function extensionForMimeType(mimeType: string): string | null {
  const normalized = mimeType.toLowerCase();
  if (normalized.startsWith("audio/webm")) return "webm";
  if (normalized.startsWith("audio/mp4") || normalized.startsWith("audio/aac")) return "mp4";
  if (normalized.startsWith("audio/wav") || normalized.startsWith("audio/x-wav")) return "wav";
  if (normalized.startsWith("audio/mpeg")) return "mp3";
  return null;
}

/**
 * Wraps a recorded Blob into a File the existing upload flow
 * (`uploadAudio` in `src/api/audio.ts`) already knows how to send. Throws
 * `MicError("unsupported", ...)` for a MIME type the backend has no
 * extension for, rather than silently mislabeling the file.
 */
export function blobToUploadFile(blob: Blob, mimeType: string, filenameBase = "consulta-gravada"): File {
  const extension = extensionForMimeType(mimeType);
  if (!extension) {
    throw new MicError("unsupported", `Formato de gravação (${mimeType}) não é aceito pelo servidor.`);
  }
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  return new File([blob], `${filenameBase}-${timestamp}.${extension}`, { type: mimeType });
}

/** Normalizes an AnalyserNode's byte frequency data into a 0-1 level (legacy / tests). */
export function computeInputLevel(frequencyData: Uint8Array): number {
  if (frequencyData.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < frequencyData.length; i += 1) {
    sum += frequencyData[i];
  }
  const average = sum / frequencyData.length;
  return Math.min(1, average / 255);
}

/**
 * RMS of AnalyserNode time-domain samples (128-centered), 0-1.
 * Better than frequency averaging for VU + RE-03: silence stays near zero
 * even when mics report a noisy frequency floor.
 */
export function computeInputLevelFromTimeDomain(timeDomainData: Uint8Array): number {
  if (timeDomainData.length === 0) return 0;
  let sumSquares = 0;
  for (let i = 0; i < timeDomainData.length; i += 1) {
    const centered = (timeDomainData[i] - 128) / 128;
    sumSquares += centered * centered;
  }
  return Math.min(1, Math.sqrt(sumSquares / timeDomainData.length));
}

export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

/** Thin, error-mapped wrapper around getUserMedia. Only called on explicit user action (never on page load). */
export async function requestMicrophone(deviceId?: string): Promise<MediaStream> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    throw new MicError("unsupported", "Gravação de áudio não é suportada neste navegador.");
  }
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
  } catch (err) {
    throw mapMicError(err);
  }
}
