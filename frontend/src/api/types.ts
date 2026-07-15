/**
 * Type contract for the Flask backend (`/api/v1/audio`), based on
 * `app/routes/audio.py`. Frozen after Fase 0 — do not change without
 * explicit approval (see `.cursor/rules/scribe-frontend.mdc`).
 *
 * Revised in Fase 2 against `app/services/transcribe_diarized.py` and
 * `app/services/soap_draft.py` to align segment timestamp fields and the
 * shape of `soap_draft.sections` (per-section split-mode results, keyed by
 * section id) with what the backend actually returns.
 */

// ---- Upload -----------------------------------------------------------

export interface UploadResponse {
  message: string;
  file_id: string;
  filename: string;
  stored_as: string;
  size_bytes: number;
  content_type: string | null;
  stages: string[];
  processed: {
    wav: ProcessedAudioInfo;
    pcm: ProcessedAudioInfo;
  };
  vad?: Record<string, unknown>;
  loudness?: Record<string, unknown>;
  enhance_voice?: Record<string, unknown>;
  enhance_deep?: Record<string, unknown>;
  pipeline_log?: PipelineLog;
}

export interface ProcessedAudioInfo {
  stored_as: string;
  format: string;
  sample_rate: number;
  channels: number;
  sample_width_bits: number;
  duration_ms: number;
  size_bytes: number;
}

export interface PipelineLog {
  enabled: boolean;
  run_id: string;
  log_dir: string;
  manifest: string;
  llm_requests: string;
}

// ---- Transcribe ---------------------------------------------------------

export interface TranscriptSegment {
  /**
   * Confirmed against a live `/transcribe` call (Fase 3): both the plain
   * (`transcribe_wav`) and diarized (`transcribe_wav_diarized`) paths emit
   * `start_ms`/`end_ms` exclusively — never `start`/`end` in seconds, despite
   * earlier fixtures in this repo assuming otherwise. See
   * `app/services/transcribe.py:301-302` and `transcribe_diarized.py`.
   */
  start_ms: number;
  end_ms: number;
  text: string;
  speaker?: string;
  speaker_label?: string;
}

export interface Transcription {
  text: string;
  raw_text?: string;
  segments?: TranscriptSegment[];
  duration_ms?: number;
  run?: Record<string, unknown>;
}

export interface SoapSections {
  subjetivo: string;
  objetivo: string;
  avaliacao: string;
  plano: string;
}

/**
 * Raw per-section LLM result from split-mode SOAP generation
 * (`_generate_soap_section` in `app/services/soap_draft.py`), keyed by
 * section id (`subjetivo` | `objetivo` | `avaliacao` | `plano`) in
 * `SoapDraft.sections`. Note `partial` uses `plano_conduta` as the text key
 * for the `plano` section, not `plano` — see `PLANO_RESPONSE_KEY` in
 * `app/services/soap_validation.py`.
 */
export interface SoapSectionResult {
  section_id: string;
  prompt_path: string;
  raw: string | null;
  partial: Record<string, unknown> | null;
  schema_coerced?: boolean;
  validation_errors?: string[] | null;
}

export interface SoapDraft {
  enabled: boolean;
  provider: string | null;
  model: string | null;
  prompt_path: string | null;
  skipped: boolean;
  error: string | null;
  diarization_enabled: boolean;
  postprocess_applied: boolean;
  validation_errors?: string[];
  raw?: string | null;
  document?: { soap: SoapSections } | null;
  plain_text?: string | null;
  sections?: Record<string, SoapSectionResult>;
  prompt_paths?: string[];
}

export interface PostprocessResult {
  enabled: boolean;
  provider: string | null;
  model: string | null;
  skipped: boolean;
  error: string | null;
  asr_fix?: { skipped: boolean; error: string | null; diff?: string };
  diarization_labels?: { skipped: boolean; error: string | null; diff?: string };
  diff?: string;
}

export interface TranscribeResponse {
  file_id: string;
  source_audio: string;
  preprocessing: string;
  transcription: Transcription;
  source: string;
  experimental: boolean;
  diarization_enabled: boolean;
  pipeline_log?: PipelineLog;
  postprocess?: PostprocessResult;
  soap_draft?: SoapDraft;
  whisper?: Record<string, unknown>;
}

// ---- Errors -------------------------------------------------------------

export interface ApiError {
  error: string;
}

// ---- UI / session state (not part of the backend contract) --------------

export type ConsultationStatus =
  | "idle"
  | "uploading"
  | "transcribing"
  | "done"
  | "error";

/**
 * Which step failed when `status === "error"` — drives what the error
 * banner offers: "transcribe" gets a retry (reuses the stored file id, no
 * re-upload); "upload" and "validation" just let the user pick a file again.
 */
export type ConsultationErrorPhase = "validation" | "upload" | "transcribe" | null;

export interface ConsultationSession {
  consultationId: string;
  patientName: string;
  patientAge: number;
  professionalName: string;
  startedAt: string; // ISO 8601
  status: ConsultationStatus;
  transcript: TranscriptSegment[];
  soap: SoapSections | null;
  entities: string[];
  error?: string;
}
