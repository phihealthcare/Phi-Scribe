import { useCallback, useRef, useState } from "react";
import type { TranscriptSegment, TranscribeResponse } from "../api/types";
import {
  CAPTURE_WORKLET_NAME,
  REALTIME_SAMPLE_RATE,
  concatFloat32,
  createCaptureWorkletModuleUrl,
  float32ToPCM16,
  resampleLinear,
} from "../lib/realtimeAudioCapture";

// Batches this many native-rate samples per worklet callback (128 samples
// each, ~2.9ms at 44.1kHz) before resampling+sending one WebSocket frame —
// avoids one send per 128 samples (too many tiny messages) and avoids
// resampling each tiny chunk's boundary in isolation.
const FLUSH_THRESHOLD_SAMPLES = 4096;

type ReadyEvent = { type: "ready"; file_id: string };
type SegmentEvent = {
  type: "partial" | "final";
  start_ms: number;
  end_ms: number;
  text: string;
  speaker_label: string | null;
};
type SpeakerUpdateEvent = { type: "speaker_update"; start_ms: number; end_ms: number; speaker: string };
type SoapReadyEvent = { type: "soap_ready"; status: number; response: TranscribeResponse };
type ErrorEvent = { type: "error"; message: string };
type RealtimeEvent = ReadyEvent | SegmentEvent | SpeakerUpdateEvent | SoapReadyEvent | ErrorEvent;

function wsUrl(): string {
  return import.meta.env.VITE_REALTIME_WS_URL ?? "ws://localhost:5000/api/v1/realtime/transcribe";
}

/**
 * Applies one server event to the current segment list — pure and
 * independently testable from the WebSocket/AudioWorklet plumbing below.
 * Segments are keyed by start_ms: a "partial" followed later by a "final"
 * for the same start_ms replaces it in place (not appended again), and a
 * "speaker_update" patches speaker/speaker_label onto every already-received
 * segment whose start_ms falls inside its [start_ms, end_ms) span — this is
 * what lets a segment render unlabeled and get corrected once diarization
 * (which runs on a slower cadence than ASR partials) catches up.
 */
export function applySegmentEvent(
  segments: TranscriptSegment[],
  event: SegmentEvent | SpeakerUpdateEvent,
): TranscriptSegment[] {
  if (event.type === "speaker_update") {
    return segments.map((segment) =>
      segment.start_ms >= event.start_ms && segment.start_ms < event.end_ms
        ? { ...segment, speaker: event.speaker, speaker_label: event.speaker }
        : segment,
    );
  }

  const next: TranscriptSegment = {
    start_ms: event.start_ms,
    end_ms: event.end_ms,
    text: event.text,
    ...(event.speaker_label ? { speaker_label: event.speaker_label } : {}),
  };
  const existingIndex = segments.findIndex((segment) => segment.start_ms === event.start_ms);
  if (existingIndex === -1) {
    return [...segments, next];
  }
  const copy = [...segments];
  copy[existingIndex] = { ...copy[existingIndex], ...next };
  return copy;
}

export function useRealtimeTranscription() {
  const [isActive, setIsActive] = useState(false);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [soapResponse, setSoapResponse] = useState<TranscribeResponse | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const pendingChunksRef = useRef<Float32Array[]>([]);
  const pendingSamplesRef = useRef(0);
  const workletModuleUrlRef = useRef<string | null>(null);

  function teardown() {
    workletNodeRef.current?.port.close();
    workletNodeRef.current?.disconnect();
    sourceNodeRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    void audioContextRef.current?.close();
    if (workletModuleUrlRef.current) {
      URL.revokeObjectURL(workletModuleUrlRef.current);
      workletModuleUrlRef.current = null;
    }
    audioContextRef.current = null;
    workletNodeRef.current = null;
    sourceNodeRef.current = null;
    streamRef.current = null;
    wsRef.current = null;
    pendingChunksRef.current = [];
    pendingSamplesRef.current = 0;
    setIsActive(false);
  }

  function flushPendingAudio() {
    const ws = wsRef.current;
    const audioContext = audioContextRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !audioContext || pendingChunksRef.current.length === 0) {
      return;
    }
    const combined = concatFloat32(pendingChunksRef.current);
    pendingChunksRef.current = [];
    pendingSamplesRef.current = 0;
    const resampled = resampleLinear(combined, audioContext.sampleRate, REALTIME_SAMPLE_RATE);
    ws.send(float32ToPCM16(resampled));
  }

  function handleServerEvent(raw: string) {
    let event: RealtimeEvent;
    try {
      event = JSON.parse(raw) as RealtimeEvent;
    } catch {
      return;
    }
    if (event.type === "partial" || event.type === "final" || event.type === "speaker_update") {
      setSegments((prev) => applySegmentEvent(prev, event));
    } else if (event.type === "soap_ready") {
      setSoapResponse(event.response);
    } else if (event.type === "error") {
      setConnectionError(event.message);
    }
    // "ready" carries only file_id today — nothing to apply yet.
  }

  const start = useCallback(async () => {
    setSegments([]);
    setSoapResponse(null);
    setConnectionError(null);
    pendingChunksRef.current = [];
    pendingSamplesRef.current = 0;

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;

    const AudioContextCtor =
      window.AudioContext ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    const audioContext = new AudioContextCtor();
    audioContextRef.current = audioContext;

    const moduleUrl = createCaptureWorkletModuleUrl();
    workletModuleUrlRef.current = moduleUrl;
    await audioContext.audioWorklet.addModule(moduleUrl);

    const ws = new WebSocket(wsUrl());
    wsRef.current = ws;
    ws.onmessage = (message) => handleServerEvent(message.data as string);
    ws.onerror = () => setConnectionError("Falha na conexão de transcrição em tempo real.");
    ws.onclose = () => setIsActive(false);

    await new Promise<void>((resolve, reject) => {
      ws.addEventListener("open", () => resolve(), { once: true });
      ws.addEventListener(
        "error",
        () => reject(new Error("Não foi possível conectar ao serviço de transcrição em tempo real.")),
        { once: true },
      );
    });

    const source = audioContext.createMediaStreamSource(stream);
    sourceNodeRef.current = source;
    const workletNode = new AudioWorkletNode(audioContext, CAPTURE_WORKLET_NAME);
    workletNodeRef.current = workletNode;
    workletNode.port.onmessage = (event: MessageEvent<Float32Array>) => {
      pendingChunksRef.current.push(event.data);
      pendingSamplesRef.current += event.data.length;
      if (pendingSamplesRef.current >= FLUSH_THRESHOLD_SAMPLES) {
        flushPendingAudio();
      }
    };
    source.connect(workletNode);

    setIsActive(true);
  }, []);

  const stop = useCallback(() => {
    flushPendingAudio();
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
    }
    teardown();
  }, []);

  return { isActive, segments, soapResponse, connectionError, start, stop };
}
