export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

// "webm" added in Fase 5 for live microphone recording (MediaRecorder's
// default output in Chrome/Firefox/Edge) — kept in sync with
// ALLOWED_EXTENSIONS in app/routes/audio.py.
export const ALLOWED_EXTENSIONS = ["mp3", "wav", "mp4", "webm"];

// Mirrors app/config.py's MAX_CONTENT_LENGTH default (110 MiB, sized for a
// ~90 min consultation — see the comment there). Override via
// VITE_MAX_UPLOAD_BYTES if the backend's limit changes.
export const DEFAULT_MAX_UPLOAD_BYTES = 115343360;

function resolveMaxUploadBytes(): number {
  const raw = import.meta.env.VITE_MAX_UPLOAD_BYTES;
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_MAX_UPLOAD_BYTES;
}

/**
 * Client-side checks that mirror what the backend would reject anyway
 * (extension allowlist in `app/routes/audio.py`, `MAX_CONTENT_LENGTH` in
 * `app/config.py`) — run this before touching the network so an invalid
 * file never puts the UI into an "uploading" state.
 */
export function validateAudioFile(file: File, maxBytes: number = resolveMaxUploadBytes()): void {
  if (!file || file.size === 0) {
    throw new ValidationError("Arquivo de áudio vazio ou inválido.");
  }

  const extension = file.name.split(".").pop()?.toLowerCase();
  if (!extension || !ALLOWED_EXTENSIONS.includes(extension)) {
    throw new ValidationError("Formato não suportado. Use MP3, WAV, MP4 ou WEBM.");
  }

  if (file.size > maxBytes) {
    const maxMb = Math.round(maxBytes / (1024 * 1024));
    throw new ValidationError(`Arquivo muito grande. Tamanho máximo: ${maxMb} MB.`);
  }
}
