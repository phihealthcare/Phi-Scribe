from __future__ import annotations

from unittest.mock import patch

import numpy as np

from app.services.transcribe_realtime import SAMPLE_RATE, RealtimeTranscriptionSession


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _FakeModel:
    pass


def _silence_pcm16(seconds: float) -> bytes:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16).tobytes()


def _speech_timestamps(end_s: float, *, start_s: float = 0.0) -> list[dict]:
    return [{"start": int(start_s * SAMPLE_RATE), "end": int(end_s * SAMPLE_RATE)}]


def _session(**overrides) -> RealtimeTranscriptionSession:
    kwargs = dict(
        model_id="small",
        device="cpu",
        compute_type="int8",
        window_s=10.0,
        step_s=2.0,
    )
    kwargs.update(overrides)
    return RealtimeTranscriptionSession(**kwargs)


def test_push_audio_accumulates_buffer_duration() -> None:
    session = _session()
    session.push_audio(_silence_pcm16(1.0))
    session.push_audio(_silence_pcm16(0.5))
    assert session._buffer_duration_s() == 1.5
    assert session._total_pushed_ms == 1500


def test_maybe_transcribe_never_calls_whisper_on_pure_silence() -> None:
    """Regression test for the reported bug: staying silent was producing
    hallucinated text ("Vamos lá"). VAD finding zero speech in the buffer
    must skip the Whisper call entirely, not just wait for a stricter
    threshold — even when the step_s fallback cadence is already due."""
    session = _session(step_s=0.0)  # always "due" for a fallback tick
    session.push_audio(_silence_pcm16(3.0))

    with (
        patch.object(RealtimeTranscriptionSession, "_vad_speech_timestamps", return_value=[]),
        patch("app.services.transcribe_realtime.transcribe._get_model") as mock_get_model,
    ):
        result = session.maybe_transcribe()

    assert result is None
    mock_get_model.assert_not_called()
    assert session._committed_segments == []


def test_maybe_transcribe_returns_none_before_step_s_with_speech_but_no_trailing_silence() -> None:
    session = _session(step_s=5.0)
    session.push_audio(_silence_pcm16(1.0))
    # Speech runs right up to the end of the buffer — no trailing silence yet,
    # so no commit boundary; step_s (5s) hasn't elapsed either.
    with patch.object(
        RealtimeTranscriptionSession, "_vad_speech_timestamps", return_value=_speech_timestamps(1.0)
    ):
        assert session.maybe_transcribe() is None


def test_maybe_transcribe_commits_final_segment_before_silence_boundary_and_trims_buffer() -> None:
    session = _session()
    session.push_audio(_silence_pcm16(3.0))

    fake_model = _FakeModel()

    def fake_transcribe(audio, **kwargs):
        assert kwargs["condition_on_previous_text"] is False
        assert kwargs["vad_filter"] is True
        return iter([_FakeSegment(0.0, 2.0, "Olá doutor")]), object()

    # Speech ends at 2.0s, buffer is 3.0s long -> 1.0s trailing silence, over
    # SILENCE_COMMIT_THRESHOLD_S (0.6s) -> commit boundary at 2.0s.
    with (
        patch.object(
            RealtimeTranscriptionSession, "_vad_speech_timestamps", return_value=_speech_timestamps(2.0)
        ),
        patch("app.services.transcribe_realtime.transcribe._get_model", return_value=(fake_model, "int8")),
        patch.object(fake_model, "transcribe", side_effect=fake_transcribe, create=True),
    ):
        result = session.maybe_transcribe()

    assert result == [{"start_ms": 0, "end_ms": 2000, "text": "Olá doutor", "final": True}]
    assert session._committed_segments == result
    # Buffer trimmed up to the committed segment's end (2s) — 1s of trailing audio remains.
    assert round(session._buffer_duration_s(), 2) == 1.0
    assert session._buffer_start_ms == 2000


def test_maybe_transcribe_keeps_uncommitted_partial_without_trimming() -> None:
    session = _session(step_s=0.0)  # always due for a fallback tick

    session.push_audio(_silence_pcm16(3.0))

    fake_model = _FakeModel()

    def fake_transcribe(audio, **kwargs):
        return iter([_FakeSegment(0.0, 3.0, "texto parcial")]), object()

    # Speech runs to the very end of the buffer -> no trailing silence -> no
    # commit boundary, but step_s=0 means the fallback tick fires anyway.
    with (
        patch.object(
            RealtimeTranscriptionSession, "_vad_speech_timestamps", return_value=_speech_timestamps(3.0)
        ),
        patch("app.services.transcribe_realtime.transcribe._get_model", return_value=(fake_model, "int8")),
        patch.object(fake_model, "transcribe", side_effect=fake_transcribe, create=True),
    ):
        result = session.maybe_transcribe()

    assert result == [{"start_ms": 0, "end_ms": 3000, "text": "texto parcial", "final": False}]
    assert session._committed_segments == []
    # Nothing committed, so nothing trimmed — buffer still holds all 3s.
    assert round(session._buffer_duration_s(), 2) == 3.0


def test_finalize_flushes_remaining_buffer_and_returns_transcribe_wav_shape() -> None:
    session = _session()
    session.push_audio(_silence_pcm16(1.5))

    fake_model = _FakeModel()

    def fake_transcribe(audio, **kwargs):
        assert kwargs["vad_filter"] is True
        return iter([_FakeSegment(0.0, 1.5, "fim da consulta")]), object()

    with (
        patch.object(
            RealtimeTranscriptionSession, "_vad_speech_timestamps", return_value=_speech_timestamps(1.5)
        ),
        patch("app.services.transcribe_realtime.transcribe._get_model", return_value=(fake_model, "int8")),
        patch.object(fake_model, "transcribe", side_effect=fake_transcribe, create=True),
    ):
        result = session.finalize()

    assert result["text"] == "fim da consulta"
    assert result["segments"] == [{"start_ms": 0, "end_ms": 1500, "text": "fim da consulta", "final": True}]
    assert result["duration_ms"] == 1500
    assert result["run"] == "faster-whisper-realtime"
    assert session._buffer_duration_s() == 0.0


def test_finalize_skips_whisper_when_remaining_buffer_is_pure_silence() -> None:
    """Same hallucination guard as maybe_transcribe(): if the user stops
    recording right after a silence gap, finalize() must not transcribe it."""
    session = _session()
    session.push_audio(_silence_pcm16(2.0))

    with (
        patch.object(RealtimeTranscriptionSession, "_vad_speech_timestamps", return_value=[]),
        patch("app.services.transcribe_realtime.transcribe._get_model") as mock_get_model,
    ):
        result = session.finalize()

    mock_get_model.assert_not_called()
    assert result == {"text": "", "segments": [], "duration_ms": 2000, "run": "faster-whisper-realtime"}
    assert session._buffer_duration_s() == 0.0


def test_finalize_with_no_pending_audio_returns_prior_committed_segments() -> None:
    session = _session()
    result = session.finalize()
    assert result == {"text": "", "segments": [], "duration_ms": 0, "run": "faster-whisper-realtime"}
