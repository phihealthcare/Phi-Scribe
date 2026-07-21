"""Rolling-window Whisper transcription for a live audio stream.

Reuses transcribe._get_model() — the SAME cached singleton (and lock) the
batch path uses (app/services/transcribe.py) — so a live session doesn't
load a second Whisper model, and reuses app/services/vad.py's silero-vad
model to detect silence gaps that mark an utterance as likely complete.

Not a byte-for-byte port of transcribe.py's batch path: each tick only sees
a short rolling window, so condition_on_previous_text is forced False (there
is no meaningful prior-text continuity to condition on across independent
re-transcriptions of overlapping windows).
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import torch
from silero_vad import get_speech_timestamps

from app.services import transcribe, vad
from app.services.transcribe import DEFAULT_COMPRESSION_RATIO_THRESHOLD, DEFAULT_LOG_PROB_THRESHOLD

SAMPLE_RATE = 16_000
# Trailing silence, once VAD-detected speech ends, needed before we treat an
# utterance as "likely complete" and commit it as final.
SILENCE_COMMIT_THRESHOLD_S = 0.6


class RealtimeTranscriptionSession:
    def __init__(
        self,
        *,
        model_id: str,
        device: str,
        compute_type: str,
        language: str = "pt",
        window_s: float = 10.0,
        step_s: float = 2.0,
        vad_threshold: float = 0.35,
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._window_s = window_s
        self._step_s = step_s
        self._vad_threshold = vad_threshold

        self._buffer = np.zeros(0, dtype=np.float32)
        # Absolute ms (since session start) that self._buffer[0] corresponds to.
        self._buffer_start_ms = 0
        self._committed_segments: list[dict[str, Any]] = []
        self._last_transcribe_at = time.monotonic()
        self._total_pushed_ms = 0

    def push_audio(self, pcm16_bytes: bytes) -> None:
        """Append raw PCM16 mono 16kHz little-endian audio to the rolling buffer."""
        samples = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        self._buffer = np.concatenate([self._buffer, samples])
        self._total_pushed_ms += int(len(samples) / SAMPLE_RATE * 1000)

    def _buffer_duration_s(self) -> float:
        return len(self._buffer) / SAMPLE_RATE

    def _vad_speech_timestamps(self, audio: np.ndarray) -> list[dict[str, Any]]:
        if len(audio) == 0:
            return []
        model_obj = vad._get_model()
        audio_tensor = torch.from_numpy(audio)
        return get_speech_timestamps(
            audio_tensor,
            model_obj,
            threshold=self._vad_threshold,
            sampling_rate=SAMPLE_RATE,
        )

    def maybe_transcribe(self) -> list[dict[str, Any]] | None:
        """Re-transcribes the trailing window_s of buffered audio if a
        VAD-detected silence gap marks an utterance as complete, or step_s
        has elapsed since the last tick. Segments that fall before a detected
        commit boundary are appended to the committed transcript and trimmed
        out of the buffer (keeping each tick's Whisper call bounded to
        ~window_s regardless of session length); segments after the boundary
        (or the whole result, if no boundary was found) are returned as
        not-yet-final partials without being trimmed. Returns None if
        nothing new is available yet.

        Never calls Whisper when VAD finds no speech at all in the buffer —
        silence/near-silence input is a well-known Whisper hallucination
        trigger (it will confidently "transcribe" phrases like "Vamos lá" or
        "Obrigado por assistir" out of nothing); skipping the call entirely
        on pure silence is the real fix, not just a stricter threshold."""
        buffer_s = self._buffer_duration_s()
        if buffer_s == 0:
            return None

        speech_timestamps = self._vad_speech_timestamps(self._buffer)
        if not speech_timestamps:
            return None

        commit_boundary_sample = None
        last_speech_end = int(speech_timestamps[-1]["end"])
        trailing_silence_s = (len(self._buffer) - last_speech_end) / SAMPLE_RATE
        if trailing_silence_s >= SILENCE_COMMIT_THRESHOLD_S:
            commit_boundary_sample = last_speech_end

        now = time.monotonic()
        due_for_fallback_tick = (now - self._last_transcribe_at) >= self._step_s
        if commit_boundary_sample is None and not due_for_fallback_tick:
            return None

        window_start_sample = max(0, len(self._buffer) - int(self._window_s * SAMPLE_RATE))
        window_start_ms = self._buffer_start_ms + int(window_start_sample / SAMPLE_RATE * 1000)
        audio_window = self._buffer[window_start_sample:]

        model, _ = transcribe._get_model(self._model_id, self._device, self._compute_type)
        segments_iter, _info = model.transcribe(
            audio_window,
            language=self._language,
            condition_on_previous_text=False,
            vad_filter=True,
            compression_ratio_threshold=DEFAULT_COMPRESSION_RATIO_THRESHOLD,
            log_prob_threshold=DEFAULT_LOG_PROB_THRESHOLD,
        )
        segments = list(segments_iter)
        self._last_transcribe_at = now

        new_segments: list[dict[str, Any]] = []
        commit_boundary_s = (
            (commit_boundary_sample - window_start_sample) / SAMPLE_RATE
            if commit_boundary_sample is not None
            else None
        )
        trim_to_sample = None
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            is_final = commit_boundary_s is not None and segment.end <= commit_boundary_s
            entry = {
                "start_ms": window_start_ms + int(segment.start * 1000),
                "end_ms": window_start_ms + int(segment.end * 1000),
                "text": text,
                "final": is_final,
            }
            new_segments.append(entry)
            if is_final:
                self._committed_segments.append(entry)
                trim_to_sample = window_start_sample + int(segment.end * SAMPLE_RATE)

        if trim_to_sample:
            self._buffer = self._buffer[trim_to_sample:]
            self._buffer_start_ms += int(trim_to_sample / SAMPLE_RATE * 1000)

        return new_segments or None

    def finalize(self) -> dict[str, Any]:
        """Flushes any remaining buffered audio as final. Returns the full
        accumulated transcript in the same shape transcribe.transcribe_wav()
        returns, so it plugs into the existing SOAP/postprocess machinery
        (app/routes/audio.py) without translation."""
        if self._buffer_duration_s() > 0 and self._vad_speech_timestamps(self._buffer):
            model, _ = transcribe._get_model(self._model_id, self._device, self._compute_type)
            segments_iter, _info = model.transcribe(
                self._buffer,
                language=self._language,
                condition_on_previous_text=False,
                vad_filter=True,
                compression_ratio_threshold=DEFAULT_COMPRESSION_RATIO_THRESHOLD,
                log_prob_threshold=DEFAULT_LOG_PROB_THRESHOLD,
            )
            for segment in segments_iter:
                text = segment.text.strip()
                if not text:
                    continue
                self._committed_segments.append(
                    {
                        "start_ms": self._buffer_start_ms + int(segment.start * 1000),
                        "end_ms": self._buffer_start_ms + int(segment.end * 1000),
                        "text": text,
                        "final": True,
                    }
                )
        self._buffer = np.zeros(0, dtype=np.float32)

        full_text = " ".join(
            segment["text"] for segment in self._committed_segments if segment.get("text")
        )
        return {
            "text": full_text,
            "segments": [dict(segment) for segment in self._committed_segments],
            "duration_ms": self._total_pushed_ms,
            "run": "faster-whisper-realtime",
        }
