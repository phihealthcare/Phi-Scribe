from __future__ import annotations

from unittest.mock import MagicMock, patch

from app import create_app
from app.services.realtime_session import RealtimeConsultationSession


def _config(**overrides):
    app = create_app("default")
    app.config["DIARIZATION_ENABLED"] = False
    app.config.update(overrides)
    return app.config


def test_push_audio_chunk_translates_asr_segments_to_events():
    config = _config()
    with (
        patch("app.services.realtime_session.RealtimeTranscriptionSession") as MockAsr,
        patch("app.services.realtime_session.RealtimeDiarizationSession") as MockDiar,
    ):
        MockAsr.return_value.maybe_transcribe.return_value = [
            {"start_ms": 0, "end_ms": 1000, "text": "olá", "final": False},
            {"start_ms": 1000, "end_ms": 2000, "text": "doutor", "final": True},
        ]
        session = RealtimeConsultationSession(config=config, file_id="f1")
        events = session.push_audio_chunk(b"\x00\x00")

    MockDiar.assert_not_called()  # DIARIZATION_ENABLED is False
    assert events == [
        {"type": "partial", "start_ms": 0, "end_ms": 1000, "text": "olá", "speaker_label": None},
        {"type": "final", "start_ms": 1000, "end_ms": 2000, "text": "doutor", "speaker_label": None},
    ]


def test_push_audio_chunk_includes_speaker_update_events_when_diarization_enabled():
    config = _config(DIARIZATION_ENABLED=True)
    with (
        patch("app.services.realtime_session.RealtimeTranscriptionSession") as MockAsr,
        patch("app.services.realtime_session.RealtimeDiarizationSession") as MockDiar,
    ):
        MockAsr.return_value.maybe_transcribe.return_value = None
        MockDiar.return_value.maybe_diarize.return_value = [
            {"speaker": "speaker_G0", "start_ms": 0, "end_ms": 2000},
        ]
        session = RealtimeConsultationSession(config=config, file_id="f1")
        events = session.push_audio_chunk(b"\x00\x00")

    assert events == [{"type": "speaker_update", "start_ms": 0, "end_ms": 2000, "speaker": "speaker_G0"}]
    MockDiar.return_value.push_audio.assert_called_once_with(b"\x00\x00")


def test_push_audio_chunk_raises_after_stop():
    config = _config()
    with patch("app.services.realtime_session.RealtimeTranscriptionSession"):
        session = RealtimeConsultationSession(config=config, file_id="f1")
        session._stopped = True
        try:
            session.push_audio_chunk(b"\x00\x00")
        except RuntimeError as exc:
            assert "already stopped" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")


def test_stop_calls_postprocess_and_soap_exactly_once_without_diarization():
    config = _config()
    fake_postprocess = MagicMock(return_value=({"file_id": "f1"}, 200))
    with (
        patch("app.services.realtime_session.RealtimeTranscriptionSession") as MockAsr,
        patch("app.routes.audio._postprocess_and_soap", fake_postprocess),
    ):
        MockAsr.return_value.finalize.return_value = {
            "text": "texto final",
            "segments": [{"start_ms": 0, "end_ms": 1000, "text": "texto final", "final": True}],
            "duration_ms": 1000,
            "run": "faster-whisper-realtime",
        }
        session = RealtimeConsultationSession(config=config, file_id="f1")
        result = session.stop()

    assert fake_postprocess.call_count == 1
    call_kwargs = fake_postprocess.call_args.kwargs
    assert call_kwargs["file_id"] == "f1"
    assert call_kwargs["preprocessing"] == "realtime"
    assert call_kwargs["diarization_enabled"] is False
    transcription_arg = fake_postprocess.call_args.args[0]
    assert transcription_arg["text"] == "texto final"
    assert result == ({"file_id": "f1"}, 200)
    assert session.stopped is True


def test_stop_labels_segments_by_speaker_when_diarization_enabled():
    config = _config(DIARIZATION_ENABLED=True)
    fake_postprocess = MagicMock(return_value=({"file_id": "f1"}, 200))
    with (
        patch("app.services.realtime_session.RealtimeTranscriptionSession") as MockAsr,
        patch("app.services.realtime_session.RealtimeDiarizationSession") as MockDiar,
        patch("app.routes.audio._postprocess_and_soap", fake_postprocess),
    ):
        MockAsr.return_value.finalize.return_value = {
            "text": "unused pre-label text",
            "segments": [
                {"start_ms": 0, "end_ms": 1000, "text": "Olá doutor", "final": True},
                {"start_ms": 1000, "end_ms": 2000, "text": "Como posso ajudar", "final": True},
            ],
            "duration_ms": 2000,
            "run": "faster-whisper-realtime",
        }
        MockDiar.return_value.finalize.return_value = {
            "speakers": ["speaker_G0", "speaker_G1"],
            "turns": [
                {"speaker": "speaker_G0", "start_ms": 0, "end_ms": 1000},
                {"speaker": "speaker_G1", "start_ms": 1000, "end_ms": 2000},
            ],
        }
        session = RealtimeConsultationSession(config=config, file_id="f1")
        session.stop()

    transcription_arg = fake_postprocess.call_args.args[0]
    labeled = transcription_arg["segments"]
    assert labeled[0]["speaker"] == "speaker_G0"
    assert labeled[1]["speaker"] == "speaker_G1"
    assert labeled[0]["speaker_label"] != labeled[1]["speaker_label"]
    assert "Olá doutor" in transcription_arg["text"]


def test_stop_raises_if_called_twice():
    config = _config()
    with (
        patch("app.services.realtime_session.RealtimeTranscriptionSession") as MockAsr,
        patch("app.routes.audio._postprocess_and_soap", return_value=({}, 200)),
    ):
        MockAsr.return_value.finalize.return_value = {"text": "", "segments": [], "duration_ms": 0, "run": ""}
        session = RealtimeConsultationSession(config=config, file_id="f1")
        session.stop()
        try:
            session.stop()
        except RuntimeError as exc:
            assert "already stopped" in str(exc)
        else:
            raise AssertionError("expected RuntimeError on second stop()")
