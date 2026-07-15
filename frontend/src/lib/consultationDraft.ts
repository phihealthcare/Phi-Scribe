import type { SoapSections, TranscriptSegment } from "../api/types";

const STORAGE_KEY = "phi-scribe:consultation-draft";

// localStorage quotas are typically 5-10 MB per origin; cap our own draft
// well under that so it never crowds out other tabs/data. A very long
// consultation drops its oldest segments rather than losing the draft
// entirely — full transcript can always be re-fetched via retryTranscribe().
const MAX_DRAFT_CHARS = 4 * 1024 * 1024;
const TRUNCATED_SEGMENT_COUNT = 200;

/**
 * RNF-07: enough to resume after a reload — the last uploaded file's id,
 * locally-edited SOAP text, and (Fase 6) the transcript segments themselves
 * (including any speaker renames), so a reload doesn't lose edits made after
 * transcription.
 */
export interface ConsultationDraft {
  fileId: string | null;
  soapSections: SoapSections | null;
  segments: TranscriptSegment[] | null;
  updatedAt: string; // ISO 8601
}

function isConsultationDraft(value: unknown): value is ConsultationDraft {
  return (
    typeof value === "object" &&
    value !== null &&
    "fileId" in value &&
    "soapSections" in value &&
    "updatedAt" in value
  );
}

/** localStorage can be unavailable (private browsing, embedded webviews) — fail silently, never throw into UI code. */
export function loadConsultationDraft(): ConsultationDraft | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isConsultationDraft(parsed)) return null;
    // Older drafts (saved before Fase 6) won't have `segments` at all.
    const segments = (parsed as { segments?: unknown }).segments;
    return { ...parsed, segments: Array.isArray(segments) ? (segments as TranscriptSegment[]) : null };
  } catch {
    return null;
  }
}

export function saveConsultationDraft(draft: ConsultationDraft): void {
  try {
    let payload = JSON.stringify(draft);
    if (payload.length > MAX_DRAFT_CHARS && draft.segments && draft.segments.length > TRUNCATED_SEGMENT_COUNT) {
      payload = JSON.stringify({ ...draft, segments: draft.segments.slice(-TRUNCATED_SEGMENT_COUNT) });
    }
    if (payload.length > MAX_DRAFT_CHARS) {
      // Still too big (e.g. huge SOAP text) — drop segments and keep the
      // smaller, higher-value fields (fileId + SOAP) rather than saving nothing.
      payload = JSON.stringify({ ...draft, segments: null });
    }
    localStorage.setItem(STORAGE_KEY, payload);
  } catch {
    // localStorage unavailable or quota exceeded — the draft is a
    // convenience, not a requirement, so drop it silently.
  }
}

export function clearConsultationDraft(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // see saveConsultationDraft
  }
}
