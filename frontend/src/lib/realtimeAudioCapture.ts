/**
 * Pure helpers for the live-transcription audio pipeline: PCM16 encoding and
 * resampling to the 16kHz mono the backend's rolling Whisper/Sortformer
 * sessions expect (app/services/transcribe_realtime.py,
 * app/services/diarization_realtime.py). Kept separate from
 * useRealtimeTranscription.ts (the integration glue — AudioWorkletNode,
 * getUserMedia, WebSocket) the same way audioRecorder.ts is split from
 * useAudioRecorder.ts, so this half is testable without a browser.
 */

export const REALTIME_SAMPLE_RATE = 16_000;

/** Converts Float32 samples in [-1, 1] to little-endian PCM16 bytes. */
export function float32ToPCM16(input: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < input.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return buffer;
}

/**
 * Simple linear-interpolation resampler. Browsers don't reliably honor a
 * requested AudioContext sampleRate (Safari in particular), so capture runs
 * at whatever native rate the browser gives us (typically 44100/48000) and
 * this converts to REALTIME_SAMPLE_RATE before sending. Not broadcast-grade
 * (no anti-aliasing filter), but sufficient for ASR/diarization input.
 */
export function resampleLinear(input: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate || input.length === 0) return input;
  const ratio = inputRate / outputRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i += 1) {
    const sourceIndex = i * ratio;
    const indexFloor = Math.floor(sourceIndex);
    const indexCeil = Math.min(indexFloor + 1, input.length - 1);
    const fraction = sourceIndex - indexFloor;
    output[i] = input[indexFloor] * (1 - fraction) + input[indexCeil] * fraction;
  }
  return output;
}

/** Concatenates buffered Float32 frames (each the Web Audio spec's 128-sample
 * render quantum) into one Float32Array — used to batch several
 * AudioWorkletNode callbacks into one WebSocket send instead of one message
 * per 128 samples (~2.9ms at 44.1kHz), which would be both wasteful and
 * would resample each tiny chunk's boundary in isolation. */
export function concatFloat32(chunks: Float32Array[]): Float32Array {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const result = new Float32Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }
  return result;
}

// Registered under this name by the inline AudioWorklet module below —
// referenced by both createCaptureWorkletModuleUrl() (registerProcessor)
// and useRealtimeTranscription.ts (`new AudioWorkletNode(ctx, NAME)`).
export const CAPTURE_WORKLET_NAME = "phi-scribe-realtime-capture";

const WORKLET_SOURCE = `
class RealtimeCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length > 0) {
      this.port.postMessage(channel.slice());
    }
    return true;
  }
}
registerProcessor("${CAPTURE_WORKLET_NAME}", RealtimeCaptureProcessor);
`;

/** Builds a Blob URL for the capture worklet module, so it can be loaded via
 * `audioContext.audioWorklet.addModule(...)` without needing a separate
 * static file served by Vite. Caller is responsible for revoking it once
 * the module has been loaded (see useRealtimeTranscription.ts). */
export function createCaptureWorkletModuleUrl(): string {
  const blob = new Blob([WORKLET_SOURCE], { type: "application/javascript" });
  return URL.createObjectURL(blob);
}
