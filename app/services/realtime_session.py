"""Glues RealtimeTranscriptionSession + RealtimeDiarizationSession together
for one live consultation, and runs the existing batch postprocess/SOAP
machinery (app/routes/audio.py's _postprocess_and_soap) exactly once, when
the session stops — SOAP itself is never made incremental; it just receives
the live-accumulated transcript instead of a post-hoc batch one.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from app.services.diarization_realtime import RealtimeDiarizationSession
from app.services.transcribe import transcribe_options_from_mapping
from app.services.transcribe_diarized import (
    diarization_options_from_mapping,
    format_speaker_transcript,
    speaker_for_ms,
    speaker_label_map,
)
from app.services.transcribe_realtime import RealtimeTranscriptionSession

if TYPE_CHECKING:
    from app.services.pipeline_tracker import PipelineTracker


class RealtimeConsultationSession:
    def __init__(
        self,
        *,
        config: Any,
        file_id: str | None = None,
        tracker: "PipelineTracker | None" = None,
    ) -> None:
        self.file_id = file_id or str(uuid.uuid4())
        self._config = config
        self._tracker = tracker
        self._stopped = False

        transcribe_kwargs = transcribe_options_from_mapping(config)
        self._asr = RealtimeTranscriptionSession(
            model_id=transcribe_kwargs["model_id"],
            device=transcribe_kwargs["device"],
            compute_type=transcribe_kwargs["compute_type"],
            language=transcribe_kwargs.get("language", "pt"),
            window_s=float(config.get("REALTIME_WINDOW_S", 10)),
            step_s=float(config.get("REALTIME_STEP_S", 2)),
        )

        diar_opts = diarization_options_from_mapping(config)
        self._diarization_enabled = bool(diar_opts.get("enabled"))
        self._diar: RealtimeDiarizationSession | None = None
        if self._diarization_enabled:
            self._diar = RealtimeDiarizationSession(
                model_id=diar_opts.get("sortformer_model_id", "nvidia/diar_sortformer_4spk-v1"),
                device=diar_opts.get("sortformer_device", "cuda"),
                max_duration_s=float(diar_opts.get("sortformer_max_duration_s", 300.0)),
                min_turn_ms=int(diar_opts.get("min_turn_ms", 400)),
                window_s=float(config.get("REALTIME_DIARIZATION_WINDOW_S", 30)),
                overlap_s=float(config.get("REALTIME_DIARIZATION_OVERLAP_S", 10)),
                venv_python=diar_opts.get("sortformer_venv_python"),
                use_daemon=bool(diar_opts.get("sortformer_use_daemon", True)),
            )

    @property
    def stopped(self) -> bool:
        return self._stopped

    def push_audio_chunk(self, pcm16_bytes: bytes) -> list[dict[str, Any]]:
        """Feeds both sub-sessions and returns newly available events to emit
        over the WebSocket immediately (partial/final transcript segments,
        and speaker_update events once diarization catches up — diarization
        runs on a slower cadence than ASR partials, so a segment may render
        without a speaker label at first and get corrected in place)."""
        if self._stopped:
            raise RuntimeError("session already stopped")

        events: list[dict[str, Any]] = []

        self._asr.push_audio(pcm16_bytes)
        asr_segments = self._asr.maybe_transcribe()
        if asr_segments:
            for segment in asr_segments:
                events.append(
                    {
                        "type": "final" if segment["final"] else "partial",
                        "start_ms": segment["start_ms"],
                        "end_ms": segment["end_ms"],
                        "text": segment["text"],
                        "speaker_label": None,
                    }
                )

        if self._diar is not None:
            self._diar.push_audio(pcm16_bytes)
            new_turns = self._diar.maybe_diarize()
            if new_turns:
                for turn in new_turns:
                    events.append(
                        {
                            "type": "speaker_update",
                            "start_ms": turn["start_ms"],
                            "end_ms": turn["end_ms"],
                            "speaker": turn["speaker"],
                        }
                    )

        return events

    def stop(self) -> tuple[dict, int]:
        """Finalizes both sub-sessions and runs postprocess/SOAP exactly
        once on the full accumulated transcript. Safe to call only once —
        raises if called again."""
        if self._stopped:
            raise RuntimeError("session already stopped")
        self._stopped = True

        # Imported here (not at module load) to avoid a circular import:
        # app.routes.audio imports app.services.realtime_session (Stage 7's
        # WS route lives in a sibling module that also needs this session).
        from app.routes.audio import _postprocess_and_soap

        transcription = self._asr.finalize()

        if self._diar is not None:
            diar_result = self._diar.finalize()
            turns = diar_result.get("turns") or []
            label_mapping = speaker_label_map(diar_result.get("speakers", []))
            segments = transcription.get("segments") or []
            labeled_segments = []
            for segment in segments:
                midpoint_ms = (segment["start_ms"] + segment["end_ms"]) // 2
                speaker = speaker_for_ms(turns, midpoint_ms) if turns else "SPEAKER_00"
                labeled_segments.append(
                    {
                        **segment,
                        "speaker": speaker,
                        "speaker_label": label_mapping.get(speaker, speaker),
                    }
                )
            transcription["segments"] = labeled_segments
            transcription["text"] = format_speaker_transcript(labeled_segments)

        return _postprocess_and_soap(
            transcription,
            config=self._config,
            tracker=self._tracker,
            file_id=self.file_id,
            preprocessing="realtime",
            audio_path=f"realtime://{self.file_id}",
            diarization_enabled=self._diarization_enabled,
        )
