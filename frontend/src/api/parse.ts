import type { SoapSections, TranscribeResponse, TranscriptSegment, UploadResponse } from "./types";

export class ParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ParseError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Validates the minimal shape needed to trust an `/upload` response. */
export function parseUploadResponse(data: unknown): UploadResponse {
  if (!isRecord(data)) {
    throw new ParseError("Upload response is not an object");
  }
  if (typeof data.file_id !== "string" || !data.file_id) {
    throw new ParseError("Upload response is missing file_id");
  }
  if (typeof data.message !== "string") {
    throw new ParseError("Upload response is missing message");
  }
  if (!isRecord(data.processed)) {
    throw new ParseError("Upload response is missing processed");
  }
  return data as unknown as UploadResponse;
}

/** Validates the minimal shape needed to trust a `/transcribe` response. */
export function parseTranscribeResponse(data: unknown): TranscribeResponse {
  if (!isRecord(data)) {
    throw new ParseError("Transcribe response is not an object");
  }
  if (typeof data.file_id !== "string" || !data.file_id) {
    throw new ParseError("Transcribe response is missing file_id");
  }
  const transcription = data.transcription;
  if (!isRecord(transcription) || typeof transcription.text !== "string") {
    throw new ParseError("Transcribe response is missing transcription.text");
  }
  return data as unknown as TranscribeResponse;
}

/**
 * `plano`'s partial is keyed as `plano_conduta`, not `plano` — see
 * `PLANO_RESPONSE_KEY` in app/services/soap_validation.py.
 */
const SECTION_PARTIAL_KEY: Record<keyof SoapSections, string> = {
  subjetivo: "subjetivo",
  objetivo: "objetivo",
  avaliacao: "avaliacao",
  plano: "plano_conduta",
};

/**
 * Prefers the merged `soap_draft.document.soap` (present when split-mode
 * generation succeeded, or when running in monolithic mode). Falls back to
 * assembling text out of `soap_draft.sections[*].partial` — the raw
 * per-section results kept even when the merge/validation step failed — so
 * a partially-successful draft can still show something. Returns null only
 * when neither is usable.
 */
export function extractSoapSections(response: TranscribeResponse): SoapSections | null {
  const document = response.soap_draft?.document;
  if (document?.soap) {
    return document.soap;
  }

  const sections = response.soap_draft?.sections;
  if (!sections) {
    return null;
  }

  const result = {} as SoapSections;
  for (const key of Object.keys(SECTION_PARTIAL_KEY) as Array<keyof SoapSections>) {
    const partial = sections[key]?.partial;
    const text = partial?.[SECTION_PARTIAL_KEY[key]];
    if (typeof text !== "string" || !text.trim()) {
      return null;
    }
    result[key] = text;
  }
  return result;
}

export function extractSegments(response: TranscribeResponse): TranscriptSegment[] {
  return response.transcription.segments ?? [];
}

// "word(s) + dosage" (e.g. "Losartana 50 mg") and bare 2-6 letter uppercase
// acronyms (e.g. "HAS", "ECG"). MVP heuristic — there's no entity-extraction
// field in the backend response to prefer instead (confirmed against a live
// /transcribe call in Fase 3: no `entities` key exists there).
// Requires the word right before the dosage to look like a proper noun
// (capitalized) — e.g. "Losartana 50 mg" — so lowercase connectors like
// "à"/"de" in "adesão à Losartana 50 mg" aren't swept into the match.
const DOSAGE_ENTITY_RE = /([A-ZÀ-Ý][a-zà-ÿ]+)\s+(\d+(?:[.,]\d+)?\s?(?:mg|mcg|g|ml|UI))\b/g;
const ACRONYM_RE = /\b[A-ZÀ-Ý]{2,6}\b/g;
const MAX_ENTITIES = 8;

/** Best-effort medication/acronym chips pulled from the SOAP text — see EntityChips.tsx. */
export function extractEntities(sections: SoapSections | null): string[] {
  if (!sections) return [];

  const text = [sections.subjetivo, sections.objetivo, sections.avaliacao, sections.plano].join(" ");
  const seen = new Set<string>();
  const found: string[] = [];

  function add(value: string) {
    const normalized = value.replace(/\s+/g, " ").trim();
    const key = normalized.toLowerCase();
    if (!normalized || seen.has(key)) return;
    seen.add(key);
    found.push(normalized);
  }

  for (const match of text.matchAll(DOSAGE_ENTITY_RE)) {
    add(`${match[1]} ${match[2]}`);
  }
  for (const match of text.matchAll(ACRONYM_RE)) {
    add(match[0]);
  }

  return found.slice(0, MAX_ENTITIES);
}
