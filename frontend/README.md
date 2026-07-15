# Phi Scribe — Frontend

React + TypeScript + Vite UI for Phi Scribe, styled with Bootstrap 5 / react-bootstrap.

## Setup

Requires Node.js 18+ (Vite 5 requirement).

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Opens at `http://localhost:5173`.

## Environment variables

- `VITE_API_BASE_URL` — base URL of the Flask API (`app/routes/audio.py`), default `http://localhost:5000/api/v1/audio`.
- `VITE_USE_MOCK` — when `true` (default in `.env.example`), the UI runs entirely off fixtures in `src/mocks/` with zero backend calls. Set to `false` once wired to a real backend (a later phase).
- `VITE_MAX_UPLOAD_BYTES` — client-side upload size limit checked before any network call, default `115343360` (110 MiB), mirroring `MAX_CONTENT_LENGTH` in `app/config.py`. Sized for a ~90 min consultation: measured `MediaRecorder` output (Chrome, `audio/webm;codecs=opus`, continuous audio) is ~125 kbps, budgeted at ~165 kbps for margin over Safari's `audio/mp4` (AAC) fallback. Keep the two in sync if the backend limit changes.

## Structure

- `src/api/` — type contract (`types.ts`) and HTTP client (`client.ts`, `audio.ts`) for the Flask endpoints. Components never call `fetch` directly.
- `src/mocks/` — mock session and sample upload/transcribe API responses, used when `VITE_USE_MOCK=true`.
- `src/hooks/` — `useConsultationSession` exposes the active consultation state.
- `src/components/`, `src/pages/` — UI (3-column consultation layout, mock-backed).

## API layer

Everything under `src/api/` targets the Flask backend in `app/routes/audio.py`. None of it is wired into the UI yet (that's a future integration phase) — it's built and tested standalone so the wiring step is just plumbing.

- **`types.ts`** — the response contract (`UploadResponse`, `TranscribeResponse`, `Transcription`, `TranscriptSegment`, `SoapDraft`, `SoapSectionResult`, ...), reviewed against `app/services/transcribe_diarized.py` and `app/services/soap_draft.py`.
- **`client.ts`** — `apiPost<T>(path, options)`, the shared fetch wrapper. Throws `ApiRequestError` (with `.status`, `0` for network/timeout failures) on non-2xx responses, on a JSON body with an `error` field (even if the HTTP status was 200), on unparseable (non-JSON) responses, and on network failure or timeout. Supports an optional `timeoutMs` for long-running calls.
- **`audio.ts`** — `uploadAudio(file)` / `transcribeFile(fileId)` (throwing) and `uploadAudioSafe(file)` / `transcribeFileSafe(fileId)` (return an `ApiResult` instead of throwing). `uploadAudio` runs `validateAudioFile` first; `transcribeFile` uses a 20-minute timeout since transcription + SOAP generation is synchronous on the backend.
- **`result.ts`** — `ApiResult<T>` union (`{ ok: true, data } | { ok: false, error, status? }`) and `toApiResult()` to convert a throwing call into one.
- **`parse.ts`** — pure, dependency-free functions: `parseUploadResponse`/`parseTranscribeResponse` (shape validation, throw `ParseError`), `extractSoapSections` (prefers `soap_draft.document.soap`, falls back to assembling text from `soap_draft.sections[*].partial`, else `null`), `extractSegments`.

### Tests

```bash
npm test        # run once
npm run test:watch
```

Vitest, no backend required — `src/api/parse.test.ts` and `src/api/client.test.ts` run against the fixtures in `src/mocks/` and a mocked `fetch`.

## Error handling and local persistence

- **`src/api/validateAudioFile.ts`** — client-side checks (empty file, extension, size vs. `VITE_MAX_UPLOAD_BYTES`) that run *before* any network call, so an invalid file never puts the UI into an "uploading" state. Throws `ValidationError` with a ready-to-display pt-BR message.
- **`src/api/errorMessages.ts`** — `toUserMessage(err)` maps any error from the API layer (`ValidationError`, `ApiRequestError` by status, network/timeout failures, or a plain `Error`) to a short pt-BR message. Falls back to the backend's own `error` text when no specific mapping applies.
- **`src/hooks/useConsultationSession.ts`** — tracks `errorPhase: "validation" | "upload" | "transcribe" | null` alongside `status`/`error`, and `lastFileId` (the most recent successful upload). `retryTranscribe()` re-runs only `/{file_id}/transcribe` with the stored id — no re-upload — which is what the "Tentar novamente" button in `StatusBanner` calls when `errorPhase === "transcribe"`.
- **`src/lib/consultationDraft.ts`** — mirrors `{ fileId, soapSections, updatedAt }` to `localStorage` (debounced ~500ms) on every `lastFileId`/`soapSections` change, so an edited SOAP draft and the in-flight file id survive a reload (and, unlike `sessionStorage`, closing the tab). Fails silently if `localStorage` is unavailable (private browsing).
  - **Restore choice on mount**: a draft with saved `soapSections` restores straight to `status: "done"`. A draft with only a `fileId` (upload succeeded but transcribe never finished — e.g. the tab was closed or reloaded mid-transcription) restores into `status: "error"` / `errorPhase: "transcribe"`, so "Tentar novamente" is immediately available without re-uploading. Transcript segments are **not** persisted — they come back via the retry.

### Manual test recipes

- **RE-05**: pick a `.pdf`/`.exe` or a file over 110 MiB — an alert appears immediately, no spinner, no network request.
- **RE-04**: upload a valid file, stop the Flask backend before `/transcribe` responds (or let it time out) → error banner with "Tentar novamente" → start the backend again → click retry → transcript and SOAP fill in without re-uploading.
- **RNF-07 (partial)**: edit a SOAP section, wait ~1s, reload the page → the edited text is still there. If you reload while `status: "transcribing"` (or right after an upload that never got transcribed), the page reopens with the retry banner instead of losing the file id.

## Live microphone recording (Fase 5)

- **`src/lib/audioRecorder.ts`** — pure/testable pieces only: `MicError`/`mapMicError` (maps `getUserMedia`/`MediaRecorder` `DOMException`s to a typed pt-BR error), `pickSupportedMimeType`, `extensionForMimeType`, `blobToUploadFile` (wraps a recorded `Blob` into a `File` the existing `uploadAudio` already knows how to send), `computeInputLevel` (VU meter math), `formatElapsed`, and `requestMicrophone` (thin `getUserMedia` wrapper, only ever called from a user click — never on page load).
- **`src/hooks/useAudioRecorder.ts`** — owns the actual `MediaRecorder`/`MediaStream`/`AudioContext`/`AnalyserNode` instances (integration glue, not unit-tested — see manual recipe below). State machine: `idle → requesting → recording ⇄ paused → idle`, or `→ error` on a `getUserMedia` failure. Exposes `devices`/`selectedDeviceId` (RF-05; device switching is only allowed while `idle` to avoid orphaning a live stream), `inputLevel` (0-1, driven by a `requestAnimationFrame` loop reading `AnalyserNode.getByteFrequencyData`), and `elapsedSeconds`.
- **Recorded format**: `MediaRecorder` is asked for `audio/webm;codecs=opus` first (Chrome/Firefox/Edge), then plain `audio/webm`, then `audio/mp4` (Safari) — whichever `MediaRecorder.isTypeSupported` accepts first. **`webm` was added to the backend's `ALLOWED_EXTENSIONS`** (`app/routes/audio.py`, mirrored in `validateAudioFile.ts`) since that's what most desktop browsers actually produce; the existing `/upload` pipeline decodes it fine because `normalize_audio` shells out to `ffmpeg -i <input>`, which auto-detects the container regardless of extension — no other backend change was needed.
- **Uploaded file formats**: the backend's `ALLOWED_EXTENSIONS` (`app/routes/audio.py`) is `mp3, wav, mp4, webm, m4a, ogg`. `m4a`/`ogg` were added alongside `webm` for the same reason — `ffmpeg` decodes any container it's given regardless of extension, so accepting them needed no pipeline change, only the allowlist entry. Note: as of this update, `validateAudioFile.ts`'s `ALLOWED_EXTENSIONS` and the file `<input accept>` in `AudioCapturePanel.tsx` still only list `mp3, wav, mp4, webm` — until those are updated to match, an `.m4a`/`.ogg` file picked in the UI is rejected client-side before it ever reaches the (now permissive) backend.
- **`MicPermissionModal.tsx`** — shown whenever `useAudioRecorder`'s `micError` is set (denied/not-found/busy/unsupported), each with a plain-language pt-BR explanation. Uploading a file is never blocked by this modal.
- **`SessionHeader.tsx`** — red pulsing "● Gravando MM:SS" / "⏸ Pausado MM:SS" badge replaces "Sessão carregada" whenever `recorderStatus` is `recording`/`paused` (RNF-05).
- **`ConsultationPage.tsx`** — registers a `beforeunload` handler only while recording/paused (RF-07); on stop, converts the recorded blob via `blobToUploadFile` and hands it straight to the existing `uploadAndTranscribe` — recording doesn't duplicate any upload/transcribe logic.

### Known limitations

- Safari's actual supported `MediaRecorder` mime type wasn't verified against a real Safari install in this environment — `audio/mp4` is the documented fallback, but if Safari produces something else, `blobToUploadFile` will surface a clear "unsupported format" toast rather than silently failing.
- No maximum recording duration or periodic auto-save; a very long recording is held entirely in memory as `Blob[]` until stopped (RNF-06's "buffer/retomada" for long recordings/connection loss is explicitly future work, per the brief).
- Switching microphones mid-recording isn't supported (device `<select>` is disabled while `recorderStatus !== "idle"`) — stop, switch, and start a new recording instead.

### Manual test recipe (requires `localhost` or HTTPS — `getUserMedia` needs a secure context)

- Click "● Gravar" → the browser's permission prompt appears (not before) → grant it → VU meter reacts to actual sound, header shows "● Gravando 00:0X" counting up.
- "❚❚ Pausar" → timer freezes, badge switches to "⏸ Pausado" → "▶ Retomar" → timer continues from where it stopped.
- "■ Parar" → recording hands off to the existing upload → transcribe flow (spinner banner, then segments/SOAP fill in) exactly as a file upload would.
- Deny the permission prompt → `MicPermissionModal` explains why and how to fix it; "Enviar arquivo de áudio" in the left panel still works with the modal open.
- Start a recording, then try to close/reload the tab → the browser's native "leave site?" prompt appears; it doesn't while idle.

## Clinical polish and resilience (Fase 6)

- **RF-10 (speaker rename)** — click a segment's speaker label (`TranscriptSegment.tsx`) to open `SpeakerLabelEditor.tsx`: free-text label, two quick buttons for MÉDICO/PACIENTE, and a checkbox to apply the change to every segment currently sharing the original label. `useConsultationSession.updateSegmentSpeaker(startMs, label, scope)` matches segments by `start_ms` (not array index), so renames are correct even while a search filter is narrowing what's visible. Local-only — there's no backend rename endpoint.
- **"✦ Atualizar resumo"** now calls `retryTranscribe()` for real instead of a toast. If the SOAP was hand-edited since the last transcribe (`soapEdited`, set by `updateSoapSections`), a confirm step (`ConfirmModal.tsx`) warns that reprocessing will overwrite those edits. Disabled until there's a `lastFileId` to reprocess.
- **RE-03 (low audio warning)** — `src/lib/audioLevels.ts` (`isLevelLow`, `shouldWarnLowLevel`) is pure threshold math; `useAudioRecorder`'s VU-meter `requestAnimationFrame` loop reads time-domain RMS (`computeInputLevelFromTimeDomain`), smooths it with an EMA, and tracks how long the signal has stayed below `LOW_INPUT_LEVEL_THRESHOLD` (0.08) before flipping `lowAudioWarning` after `LOW_INPUT_LEVEL_WARNING_SECONDS` (5s) of near-silence. Shown as a small warning `Alert` under the VU meter in `AudioCapturePanel.tsx` — recording is never blocked by it.
- **RNF-07 (segments persisted too)** — `ConsultationDraft` now includes `segments` (including any RF-10 renames). `saveConsultationDraft` caps the serialized draft at ~4MB, dropping to the most recent 200 segments (then to no segments at all) rather than silently failing to save on a very long consultation — see the comment in `consultationDraft.ts`.
- **RNF-02 (long consultations)** — `TranscriptPanel.tsx` paginates at 50 segments ("Carregar mais") instead of rendering everything at once. **Chose pagination over a virtualization library** (e.g. `react-window`): segment cards have variable height (search-highlighted, being edited, different text lengths), which doesn't fit a fixed-size virtualizer without reworking the segment component in ways I couldn't visually verify in this environment. Pagination is zero-dependency and needed no new package. Search still filters the *full* segment list upstream (`useConsultationSession.filteredSegments`) before pagination ever sees it.
- **RNF-06 (partial — crash recovery for an unsent recording)** — `src/lib/recordingBackup.ts` mirrors each `MediaRecorder` chunk to IndexedDB (`phi-scribe-recording` DB, single fixed key since only one recording is ever active) as it's captured, tagged with `startedAt`/`mimeType`/`deviceId`. On mount, `useAudioRecorder` checks for a leftover backup and exposes it as `recoverableBackup`; `ConsultationPage` shows a confirm modal ("Recuperar" reassembles the blob and hands it to `uploadAndTranscribe`, "Descartar" clears it). The backup is cleared automatically on a clean stop. This is local-only crash protection, not a resumable upload — see "Known limitations".
- **Entities** — `extractEntities` (`src/api/parse.ts`) is an MVP heuristic over the SOAP text: dosage mentions (`Losartana 50 mg`) and bare uppercase acronyms (`HAS`, `ECG`), deduped, capped at 8. There's no `entities` field in the real backend response to prefer instead (confirmed against a live `/transcribe` call in Fase 3).
- **RF-13 ("Finalizar consulta")** — a new button in `SoapSummaryPanel.tsx` (confirm modal first) copies the current SOAP via `formatSoapPlainText` (`src/lib/soapText.ts`, mirrors the backend's `format_soap_plain_text`) to the clipboard, then calls `resetSession()` (clears all state + the localStorage draft) and discards any recording backup. No PDF/file export yet.
- **`VITE_USE_MOCK=false`** — already did the right thing since Fase 3 (empty/idle start, no fake data); this phase just documents it properly in `.env.example`. Header metadata (patient/professional) still comes from the mock either way — there's no session/patient API yet.

### Known limitations

- `appendRecordingBackupChunk` does a read-modify-write of the *entire* chunk array on every ~1s chunk — fine for a short recording, but grows roughly quadratically for very long ones. Full RNF-06 (a properly chunked/streamed backup, plus resuming an interrupted *upload*, not just recovering a pre-upload blob) is still future work.
- Speaker rename is local-only; there's no backend endpoint to persist it beyond this browser (draft/localStorage aside).
- `extractEntities` is a regex heuristic, not clinical NER — expect both false positives (stray acronyms) and misses.
- Pagination, not virtualization — see the RNF-02 note above for why.

## Current scope

Fases 0-6 done: project foundation, mock-backed UI matching `public/ui-template.jpeg`, a hardened/tested API layer, real upload→transcribe wiring, error/retry handling with a partial localStorage draft, live microphone recording, and this phase's clinical polish (speaker rename, resumo refresh, low-audio warning, long-consultation pagination, partial crash recovery, entities, finalize/copy). Still out of scope: real-time/WebSocket transcription (RE-02), full RNF-06 (see above), EHR/auth integration, and PDF export.
