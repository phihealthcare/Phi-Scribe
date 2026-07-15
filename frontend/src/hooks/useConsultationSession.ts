import { useEffect, useMemo, useRef, useState } from "react";
import { transcribeFile, uploadAudioSegments } from "../api/audio";
import { toUserMessage } from "../api/errorMessages";
import { extractEntities, extractSegments, extractSoapSections } from "../api/parse";
import type {
  ConsultationErrorPhase,
  ConsultationSession,
  ConsultationStatus,
  SoapSections,
  TranscriptSegment,
} from "../api/types";
import { validateAudioFile } from "../api/validateAudioFile";
import { clearConsultationDraft, loadConsultationDraft, saveConsultationDraft } from "../lib/consultationDraft";
import { clearRecordingBackup } from "../lib/recordingBackup";
import { mockSession } from "../mocks/session";

const useMock = import.meta.env.VITE_USE_MOCK === "true";
const DRAFT_SAVE_DEBOUNCE_MS = 500;

const PENDING_TRANSCRIBE_MESSAGE =
  'Sessão anterior não foi concluída. Clique em "Tentar novamente" para retomar a transcrição.';

/**
 * Session header metadata (patient/professional/etc.) has no backing API in
 * this phase, so it always comes from the mock. Only the transcript/SOAP
 * state below is real: when VITE_USE_MOCK=true it starts pre-filled with
 * mock data (Fase 1 demo), but calling `uploadAndTranscribe` always hits the
 * real `/upload` + `/{file_id}/transcribe` endpoints and overwrites it with
 * the actual response.
 *
 * Fase 4 (RNF-07, partial): the last uploaded `file_id` and any locally
 * edited SOAP text are mirrored to localStorage. On mount, if a draft is
 * found: a draft with saved `soapSections` restores straight to "done"; a
 * draft with only a `fileId` (upload succeeded but transcribe never did)
 * restores into the same "error" + retry state a failed transcribe would
 * leave behind, so the "Tentar novamente" button works after a reload too.
 *
 * Fase 6: transcript segments (incl. RF-10 speaker renames) are persisted
 * too, `retryTranscribe` doubles as "Atualizar resumo" (with a confirm step
 * if the SOAP was hand-edited since the last transcribe), entities are
 * derived from the SOAP text, and `resetSession` backs "Finalizar consulta".
 */
export function useConsultationSession() {
  const session: ConsultationSession = mockSession;

  const [status, setStatus] = useState<ConsultationStatus>(useMock ? "done" : "idle");
  const [segments, setSegments] = useState<TranscriptSegment[]>(useMock ? mockSession.transcript : []);
  const [soapSections, setSoapSections] = useState<SoapSections | null>(useMock ? mockSession.soap : null);
  const [soapRevision, setSoapRevision] = useState(0);
  const [entities, setEntities] = useState<string[]>(useMock ? mockSession.entities : []);
  const [soapEdited, setSoapEdited] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorPhase, setErrorPhase] = useState<ConsultationErrorPhase>(null);
  const [lastFileId, setLastFileId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const restoredRef = useRef(false);

  // Restore from localStorage once, before the debounced-save effect below
  // can persist the initial (possibly mock) state over a real draft.
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;

    const draft = loadConsultationDraft();
    if (!draft?.fileId) return;

    setLastFileId(draft.fileId);
    if (draft.segments) setSegments(draft.segments);
    if (draft.soapSections) {
      setSoapSections(draft.soapSections);
      setSoapRevision((r) => r + 1);
      setStatus("done");
    } else {
      setError(PENDING_TRANSCRIBE_MESSAGE);
      setErrorPhase("transcribe");
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      saveConsultationDraft({
        fileId: lastFileId,
        soapSections,
        segments: segments.length > 0 ? segments : null,
        updatedAt: new Date().toISOString(),
      });
    }, DRAFT_SAVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [lastFileId, soapSections, segments]);

  const filteredSegments = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return segments;
    return segments.filter((segment) => segment.text.toLowerCase().includes(query));
  }, [segments, searchQuery]);

  function updateSoapSections(sections: SoapSections) {
    setSoapSections(sections);
    setSoapEdited(true);
  }

  /** RF-10: rename a speaker on one segment, or every segment that currently shares its label. */
  function updateSegmentSpeaker(startMs: number, label: string, scope: "single" | "all") {
    setSegments((prev) => {
      const target = prev.find((segment) => segment.start_ms === startMs);
      if (!target) return prev;
      if (scope === "single") {
        return prev.map((segment) => (segment.start_ms === startMs ? { ...segment, speaker_label: label } : segment));
      }
      const originalLabel = target.speaker_label;
      return prev.map((segment) =>
        segment.speaker_label === originalLabel ? { ...segment, speaker_label: label } : segment,
      );
    });
  }

  async function runTranscribe(fileId: string): Promise<void> {
    setStatus("transcribing");
    setError(null);
    setErrorPhase(null);
    try {
      const transcribed = await transcribeFile(fileId);
      const newSoap = extractSoapSections(transcribed);
      setSegments(extractSegments(transcribed));
      setSoapSections(newSoap);
      setSoapRevision((r) => r + 1);
      setEntities(extractEntities(newSoap));
      setSoapEdited(false);
      setStatus("done");
    } catch (err) {
      setError(toUserMessage(err));
      setErrorPhase("transcribe");
      setStatus("error");
    }
  }

  async function uploadAndTranscribe(fileOrSegments: File | File[]): Promise<void> {
    setError(null);
    setErrorPhase(null);

    // More than one file only happens after continueRecording() (RE-02):
    // an interrupted-then-resumed recording, uploaded as ordered segments
    // for the backend to concatenate.
    const files = Array.isArray(fileOrSegments) ? fileOrSegments : [fileOrSegments];

    // RE-05: validate before touching the network at all, so an invalid
    // file never puts the UI into an "uploading" state.
    try {
      files.forEach((file) => validateAudioFile(file));
    } catch (err) {
      setError(toUserMessage(err));
      setErrorPhase("validation");
      setStatus("error");
      return;
    }

    // A new file means any previous transcript/SOAP no longer applies —
    // clear them so the UI doesn't show stale data from a different upload
    // while the new one is in flight, and so the draft doesn't conflate them.
    setSegments([]);
    setSoapSections(null);
    setEntities([]);
    setSoapEdited(false);
    setLastFileId(null);

    let uploaded;
    try {
      setStatus("uploading");
      uploaded = await uploadAudioSegments(files);
    } catch (err) {
      setError(toUserMessage(err));
      setErrorPhase("upload");
      setStatus("error");
      return;
    }

    // The audio is now safely stored server-side (by file_id) — the local
    // IndexedDB recording backup (if any) is no longer needed. If upload had
    // failed above, the backup is deliberately left in place so a crash/tab
    // close mid-upload can still recover the recording on reload.
    void clearRecordingBackup();

    setLastFileId(uploaded.file_id);
    await runTranscribe(uploaded.file_id);
  }

  /** Also backs the "Atualizar resumo" button (Fase 6) — same call, re-runs only /transcribe. */
  async function retryTranscribe(): Promise<void> {
    if (!lastFileId) return;
    await runTranscribe(lastFileId);
  }

  function dismissError() {
    setError(null);
    setErrorPhase(null);
    setStatus(soapSections || segments.length > 0 ? "done" : "idle");
  }

  /** RF-13: "Finalizar consulta" — wipe all session state and its persisted draft. */
  function resetSession() {
    setStatus("idle");
    setSegments([]);
    setSoapSections(null);
    setEntities([]);
    setSoapEdited(false);
    setError(null);
    setErrorPhase(null);
    setLastFileId(null);
    setSearchQuery("");
    clearConsultationDraft();
  }

  return {
    session,
    segments,
    soapSections,
    soapRevision,
    entities,
    soapEdited,
    status,
    error,
    errorPhase,
    lastFileId,
    updateSoapSections,
    updateSegmentSpeaker,
    searchQuery,
    setSearchQuery,
    filteredSegments,
    uploadAndTranscribe,
    retryTranscribe,
    dismissError,
    resetSession,
  };
}
