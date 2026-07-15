import { apiPost } from "./client";
import { toApiResult, type ApiResult } from "./result";
import type { TranscribeResponse, UploadResponse } from "./types";
import { validateAudioFile } from "./validateAudioFile";

/**
 * Typed wrappers over the existing Flask endpoints (app/routes/audio.py).
 */

// Transcription is synchronous on the backend and can take minutes on real
// audio (ASR + postprocess + SOAP draft generation). See client.ts.
const TRANSCRIBE_TIMEOUT_MS = 20 * 60 * 1000;

function assertValidFileId(fileId: string): void {
  if (!fileId || !fileId.trim()) {
    throw new Error("fileId is required");
  }
}

export function uploadAudio(file: File): Promise<UploadResponse> {
  validateAudioFile(file);
  const formData = new FormData();
  formData.append("file", file);
  return apiPost<UploadResponse>("/upload", { body: formData });
}

/**
 * Uploads one or more recording segments as a single logical recording — more
 * than one only happens after continueRecording() (RE-02/RNF-06: recording
 * interrupted by a tab close/crash, then resumed). The backend concatenates
 * segments server-side in order before running the normal pipeline.
 */
export function uploadAudioSegments(files: File[]): Promise<UploadResponse> {
  if (files.length === 1) return uploadAudio(files[0]);
  files.forEach((file) => validateAudioFile(file));
  const formData = new FormData();
  files.forEach((file) => formData.append("segments", file));
  return apiPost<UploadResponse>("/upload", { body: formData });
}

export function transcribeFile(fileId: string): Promise<TranscribeResponse> {
  assertValidFileId(fileId);
  return apiPost<TranscribeResponse>(`/${fileId}/transcribe`, { timeoutMs: TRANSCRIBE_TIMEOUT_MS });
}

export function uploadAudioSafe(file: File): Promise<ApiResult<UploadResponse>> {
  return toApiResult(uploadAudio(file));
}

export function transcribeFileSafe(fileId: string): Promise<ApiResult<TranscribeResponse>> {
  return toApiResult(transcribeFile(fileId));
}
