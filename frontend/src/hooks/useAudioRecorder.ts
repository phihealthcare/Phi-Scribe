import { useEffect, useRef, useState } from "react";
import {
  INPUT_LEVEL_SMOOTHING_ALPHA,
  LOW_INPUT_LEVEL_THRESHOLD,
  LOW_INPUT_LEVEL_WARNING_SECONDS,
  isLevelLow,
  shouldWarnLowLevel,
  smoothInputLevel,
} from "../lib/audioLevels";
import { audioDebugLog, audioDebugLogOnce } from "../lib/audioDebug";
import {
  MicError,
  blobToUploadFile,
  computeInputLevelFromTimeDomain,
  mapMicError,
  pickSupportedMimeType,
  requestMicrophone,
  type RecorderStatus,
} from "../lib/audioRecorder";
import {
  appendRecordingBackupChunk,
  assembleAllSegments,
  clearRecordingBackup,
  loadRecordingBackup,
  startRecordingBackup,
  type RecordingBackupRecord,
} from "../lib/recordingBackup";

/**
 * Owns the actual MediaRecorder/getUserMedia/AudioContext instances and
 * their React-visible state. Pure mapping/formatting logic lives in
 * `src/lib/audioRecorder.ts` (testable without a browser); this hook is
 * integration glue and is exercised manually (see frontend/README.md).
 *
 * Never requests microphone access on mount — only `startRecording()` does,
 * and only in response to a user click (RF-06 / RE-01).
 */
export function useAudioRecorder() {
  const [recorderStatus, setRecorderStatus] = useState<RecorderStatus>("idle");
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceIdState] = useState<string | null>(null);
  const [inputLevel, setInputLevel] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [micError, setMicError] = useState<MicError | null>(null);
  // Persists across dismissMicError (unlike micError itself): the browser
  // blocks getUserMedia at the origin level, not per-device, so once denied,
  // re-enabling the device select would falsely suggest picking a different
  // mic could help — only a real permission grant should re-enable it.
  const [micBlocked, setMicBlocked] = useState(false);
  const [lowAudioWarning, setLowAudioWarning] = useState(false);
  const [recoverableBackup, setRecoverableBackup] = useState<RecordingBackupRecord | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeTypeRef = useRef<string>("");
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const timerIdRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopResolveRef = useRef<((blob: Blob | null) => void) | null>(null);
  // Segments carried forward from an earlier interrupted take (continueRecording).
  // Combined with the current segment's blob when stopRecording() resolves.
  const previousSegmentsRef = useRef<Blob[]>([]);
  const lowLevelSinceRef = useRef<number | null>(null);
  const recorderStatusRef = useRef<RecorderStatus>("idle");
  const lowAudioWarningRef = useRef(false);
  const lastLevelLogAtRef = useRef(0);
  const smoothedLevelRef = useRef(0);

  function describeStreamTracks(stream: MediaStream): Record<string, unknown>[] {
    return stream.getAudioTracks().map((track) => ({
      id: track.id,
      label: track.label,
      enabled: track.enabled,
      muted: track.muted,
      readyState: track.readyState,
    }));
  }

  function stopTimer() {
    if (timerIdRef.current !== null) {
      clearInterval(timerIdRef.current);
      timerIdRef.current = null;
    }
  }

  function startTimer() {
    stopTimer();
    timerIdRef.current = setInterval(() => {
      setElapsedSeconds((seconds) => seconds + 1);
    }, 1000);
  }

  function stopVuMeter() {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    analyserRef.current = null;
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    lowLevelSinceRef.current = null;
    smoothedLevelRef.current = 0;
    setInputLevel(0);
    if (lowAudioWarningRef.current) {
      lowAudioWarningRef.current = false;
      audioDebugLog("RE-03 warning cleared (VU meter stopped)");
    }
    setLowAudioWarning(false);
  }

  function setLowAudioWarningState(next: boolean, reason: string): void {
    if (lowAudioWarningRef.current === next) return;
    lowAudioWarningRef.current = next;
    setLowAudioWarning(next);
    audioDebugLog(next ? "RE-03 warning ON" : "RE-03 warning OFF", { reason });
  }

  function startVuMeter(stream: MediaStream) {
    const AudioContextCtor =
      window.AudioContext ?? (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) {
      audioDebugLogOnce("no-audio-context", "AudioContext unavailable — VU meter and RE-03 disabled");
      return;
    }

    audioDebugLog("Starting VU meter", {
      tracks: describeStreamTracks(stream),
      threshold: LOW_INPUT_LEVEL_THRESHOLD,
      warningAfterSeconds: LOW_INPUT_LEVEL_WARNING_SECONDS,
    });

    const audioContext = new AudioContextCtor();
    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);

    audioContextRef.current = audioContext;
    analyserRef.current = analyser;

    void audioContext.resume().then(() => {
      audioDebugLog("AudioContext resumed", { state: audioContext.state });
    }).catch((err) => {
      audioDebugLog("AudioContext resume failed — levels may stay at zero", {
        state: audioContext.state,
        error: err instanceof Error ? err.message : String(err),
      });
    });

    const data = new Uint8Array(analyser.fftSize);
    const tick = () => {
      if (!analyserRef.current) return;
      analyserRef.current.getByteTimeDomainData(data);
      const rawLevel = computeInputLevelFromTimeDomain(data);
      const level = smoothInputLevel(smoothedLevelRef.current, rawLevel);
      smoothedLevelRef.current = level;

      let peakDeviation = 0;
      for (let i = 0; i < data.length; i += 1) {
        const deviation = Math.abs(data[i] - 128);
        if (deviation > peakDeviation) peakDeviation = deviation;
      }

      setInputLevel(level);

      const levelIsLow = isLevelLow(level);
      let consecutiveSeconds = 0;
      let shouldWarn = false;

      // RE-03: warn if the signal has been (near-)silent for a while —
      // likely muted/unplugged mic or the speaker has stepped away.
      if (levelIsLow) {
        if (lowLevelSinceRef.current === null) {
          lowLevelSinceRef.current = performance.now();
          audioDebugLog("Input below threshold — timer started", {
            level: level.toFixed(4),
            rawLevel: rawLevel.toFixed(4),
            threshold: LOW_INPUT_LEVEL_THRESHOLD,
          });
        }
        consecutiveSeconds = (performance.now() - lowLevelSinceRef.current) / 1000;
        shouldWarn = shouldWarnLowLevel(consecutiveSeconds);
        setLowAudioWarningState(shouldWarn, `low for ${consecutiveSeconds.toFixed(1)}s`);
      } else {
        if (lowLevelSinceRef.current !== null) {
          audioDebugLog("Input above threshold — timer reset", {
            level: level.toFixed(4),
            rawLevel: rawLevel.toFixed(4),
            threshold: LOW_INPUT_LEVEL_THRESHOLD,
          });
        }
        lowLevelSinceRef.current = null;
        setLowAudioWarningState(false, "level recovered");
      }

      const now = performance.now();
      if (now - lastLevelLogAtRef.current >= 1000) {
        lastLevelLogAtRef.current = now;
        audioDebugLog("Level tick (1/s)", {
          recorderStatus: recorderStatusRef.current,
          level: Number(level.toFixed(4)),
          rawLevel: Number(rawLevel.toFixed(4)),
          peakDeviation,
          smoothingAlpha: INPUT_LEVEL_SMOOTHING_ALPHA,
          levelIsLow,
          consecutiveLowSeconds: levelIsLow ? Number(consecutiveSeconds.toFixed(1)) : 0,
          shouldWarn,
          lowAudioWarning: lowAudioWarningRef.current,
          audioContextState: audioContextRef.current?.state ?? "none",
          uiWouldShowAlert:
            recorderStatusRef.current === "recording" && lowAudioWarningRef.current,
        });
      }

      rafIdRef.current = requestAnimationFrame(tick);
    };
    tick();
  }

  function releaseStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function refreshDevices(): Promise<void> {
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) return;
    try {
      const allDevices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = allDevices.filter((device) => device.kind === "audioinput");
      setDevices(audioInputs);
      setSelectedDeviceIdState((prev) => prev ?? audioInputs[0]?.deviceId ?? null);
    } catch {
      // enumerateDevices without permission can fail silently in some
      // browsers — the device select just stays empty until a recording
      // succeeds once and refreshDevices() is called again.
    }
  }

  // enumerateDevices() (unlike getUserMedia) doesn't prompt for permission,
  // so calling it on mount is safe and lets the select populate early
  // (labels arrive later, once a recording has actually granted access).
  useEffect(() => {
    void refreshDevices();
  }, []);

  // RNF-06 (partial): surface any backup left behind by a crash/reload
  // during a previous recording, without auto-discarding it.
  useEffect(() => {
    void loadRecordingBackup().then((backup) => {
      if (backup && backup.chunks.length > 0) {
        setRecoverableBackup(backup);
      }
    });
  }, []);

  useEffect(() => {
    return () => {
      stopTimer();
      stopVuMeter();
      releaseStream();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
    };
  }, []);

  async function startRecording(previousSegments: Blob[] = []): Promise<void> {
    setMicError(null);
    setMicBlocked(false);
    setRecoverableBackup(null);
    previousSegmentsRef.current = previousSegments;
    setRecorderStatus("requesting");
    recorderStatusRef.current = "requesting";
    audioDebugLog("startRecording() — requesting microphone", {
      selectedDeviceId,
      continuationSegments: previousSegments.length,
    });
    try {
      const stream = await requestMicrophone(selectedDeviceId ?? undefined);
      streamRef.current = stream;

      audioDebugLog("Microphone granted", { tracks: describeStreamTracks(stream) });

      await refreshDevices();

      const mimeType = pickSupportedMimeType();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      mimeTypeRef.current = recorder.mimeType || mimeType || "";
      chunksRef.current = [];

      void startRecordingBackup(
        {
          startedAt: new Date().toISOString(),
          mimeType: mimeTypeRef.current,
          deviceId: selectedDeviceId,
        },
        previousSegments,
      );

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
          void appendRecordingBackupChunk(event.data);
        }
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeTypeRef.current || recorder.mimeType });
        chunksRef.current = [];
        stopResolveRef.current?.(blob);
        stopResolveRef.current = null;
      };

      mediaRecorderRef.current = recorder;
      recorder.start(1000);
      startVuMeter(stream);
      setElapsedSeconds(0);
      startTimer();
      setRecorderStatus("recording");
      recorderStatusRef.current = "recording";
      audioDebugLog("Recording started", { mimeType: mimeTypeRef.current });
    } catch (err) {
      releaseStream();
      const mapped = mapMicError(err);
      setMicError(mapped);
      setMicBlocked(mapped.code === "denied");
      setRecorderStatus("error");
      recorderStatusRef.current = "error";
      audioDebugLog("startRecording() failed", {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  function pauseRecording(): void {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state !== "recording") return;
    recorder.pause();
    stopTimer();
    setRecorderStatus("paused");
    recorderStatusRef.current = "paused";
    audioDebugLog("Recording paused — RE-03 alert hidden while paused (VU meter still runs)");
  }

  function resumeRecording(): void {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state !== "paused") return;
    recorder.resume();
    startTimer();
    setRecorderStatus("recording");
    recorderStatusRef.current = "recording";
    audioDebugLog("Recording resumed");
  }

  /**
   * Resolves to the ordered list of segments to upload: any earlier
   * interrupted takes carried forward by continueRecording(), followed by
   * this session's blob. Almost always a single-element array — only has
   * more than one after a continuation.
   */
  function stopRecording(): Promise<Blob[] | null> {
    const recorder = mediaRecorderRef.current;
    stopTimer();
    stopVuMeter();
    audioDebugLog("stopRecording()");

    if (!recorder || recorder.state === "inactive") {
      releaseStream();
      mediaRecorderRef.current = null;
      setRecorderStatus("idle");
      recorderStatusRef.current = "idle";
      const carried = previousSegmentsRef.current;
      previousSegmentsRef.current = [];
      return Promise.resolve(carried.length > 0 ? carried : null);
    }

    return new Promise<Blob | null>((resolve) => {
      stopResolveRef.current = resolve;
      recorder.stop();
    }).then((blob) => {
      releaseStream();
      mediaRecorderRef.current = null;
      setRecorderStatus("idle");
      recorderStatusRef.current = "idle";
      audioDebugLog("Recording stopped", { blobSize: blob?.size ?? 0 });
      // Don't clear the backup here — the caller still has to upload this
      // blob, and that can fail or the tab can close mid-upload. The backup
      // is only cleared once uploadAndTranscribe's upload actually succeeds
      // (useConsultationSession.ts), so a crash/close during upload can still
      // recover from IndexedDB on reload.
      const carried = previousSegmentsRef.current;
      previousSegmentsRef.current = [];
      const segments = [...carried, ...(blob && blob.size > 0 ? [blob] : [])];
      return segments.length > 0 ? segments : null;
    });
  }

  function setSelectedDeviceId(deviceId: string): void {
    // Switching input mid-recording would orphan the live MediaStream; keep
    // it simple and only allow it while idle (documented trade-off).
    if (recorderStatus !== "idle") return;
    setSelectedDeviceIdState(deviceId);
  }

  function dismissMicError(): void {
    setMicError(null);
    setRecorderStatus("idle");
  }

  /** Assembles the recovered backup (all its segments) into Files ready for uploadAndTranscribe, and clears the backup. */
  async function recoverBackup(): Promise<File[] | null> {
    if (!recoverableBackup) return null;
    const blobs = assembleAllSegments(recoverableBackup);
    await clearRecordingBackup();
    setRecoverableBackup(null);
    if (blobs.length === 0) return null;
    try {
      return blobs.map((blob) => blobToUploadFile(blob, recoverableBackup.mimeType));
    } catch {
      return null;
    }
  }

  async function discardBackup(): Promise<void> {
    await clearRecordingBackup();
    setRecoverableBackup(null);
  }

  /**
   * "Continuar gravando": carries the recovered backup's segments forward
   * instead of uploading them, and starts a fresh MediaRecorder session for
   * the rest of the take. The old MediaRecorder/MediaStream are gone (the
   * tab closed or crashed), so this can't literally resume — it starts a new
   * recording and the two segments get concatenated server-side on upload.
   */
  async function continueRecording(): Promise<void> {
    if (!recoverableBackup) return;
    const carried = assembleAllSegments(recoverableBackup);
    await startRecording(carried);
  }

  return {
    recorderStatus,
    devices,
    selectedDeviceId,
    inputLevel,
    elapsedSeconds,
    micError,
    micBlocked,
    lowAudioWarning,
    recoverableBackup,
    startRecording,
    pauseRecording,
    resumeRecording,
    stopRecording,
    refreshDevices,
    setSelectedDeviceId,
    dismissMicError,
    recoverBackup,
    discardBackup,
    continueRecording,
  };
}
