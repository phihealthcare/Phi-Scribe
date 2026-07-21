from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from app.services import transcribe, wav_utils
from app.services.pipeline_steps import (
    TRANSCRIBE_01_DIARIZATION,
    TRANSCRIBE_02_WHISPER,
    TRANSCRIBE_03_FORMAT_SPEAKERS,
)

if TYPE_CHECKING:
    from app.services.pipeline_tracker import PipelineTracker

def speaker_label_map(speakers: list[str]) -> dict[str, str]:
    ordered = sorted(speakers)
    return {speaker_id: f"Falante {index + 1}" for index, speaker_id in enumerate(ordered)}


def format_speaker_transcript(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for segment in segments:
        label = str(segment.get("speaker_label", "Falante"))
        text = str(segment.get("text", "")).strip()
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def speaker_for_ms(turns: list[dict[str, Any]], ms: int) -> str:
    for turn in turns:
        start_ms = int(turn["start_ms"])
        end_ms = int(turn["end_ms"])
        if start_ms <= ms < end_ms:
            return str(turn["speaker"])

    best_speaker: str | None = None
    best_overlap = 0
    for turn in turns:
        start_ms = int(turn["start_ms"])
        end_ms = int(turn["end_ms"])
        overlap = max(0, min(end_ms, ms + 1) - max(start_ms, ms))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = str(turn["speaker"])

    if best_speaker:
        return best_speaker
    if turns:
        return str(turns[0]["speaker"])
    return "SPEAKER_00"


def _collect_words(transcription: dict[str, Any]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for segment in transcription.get("segments", []):
        for word in segment.get("words") or []:
            text = str(word.get("word", "")).strip()
            if not text:
                continue
            words.append(
                {
                    "word": text,
                    "start_ms": int(word["start_ms"]),
                    "end_ms": int(word["end_ms"]),
                }
            )
    return words


def _segments_from_aligned_words(
    words: list[dict[str, Any]],
    *,
    alignment_turns: list[dict[str, Any]],
    speaker_label_mapping: dict[str, str],
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for word in words:
        midpoint_ms = (word["start_ms"] + word["end_ms"]) // 2
        speaker_id = speaker_for_ms(alignment_turns, midpoint_ms)
        speaker_label = speaker_label_mapping.get(speaker_id, speaker_id)

        if segments and segments[-1]["speaker_id"] == speaker_id:
            segments[-1]["text"] = f"{segments[-1]['text']} {word['word']}".strip()
            segments[-1]["end_ms"] = word["end_ms"]
        else:
            segments.append(
                {
                    "speaker_id": speaker_id,
                    "speaker_label": speaker_label,
                    "start_ms": word["start_ms"],
                    "end_ms": word["end_ms"],
                    "text": word["word"],
                }
            )
    return segments


def _sequential_transcribe_options(options: dict[str, Any]) -> dict[str, Any]:
    sequential_options = dict(options)
    sequential_options["force_sequential"] = True
    return sequential_options


def _transcribe_turns(
    wav_path: Path,
    turns: list[dict[str, Any]],
    *,
    transcribe_options: dict[str, Any],
    speaker_label_mapping: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int]:
    segments: list[dict[str, Any]] = []
    last_run: dict[str, Any] | None = None
    total_duration_ms = 0

    with tempfile.TemporaryDirectory(prefix="phi-scribe-diarize-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        for index, turn in enumerate(turns):
            turn_wav = tmp_path / f"turn_{index:04d}.wav"
            wav_utils.extract_turn_wav(
                wav_path,
                turn_wav,
                start_ms=int(turn["start_ms"]),
                end_ms=int(turn["end_ms"]),
            )
            turn_result = transcribe.transcribe_wav(
                turn_wav,
                **_sequential_transcribe_options(transcribe_options),
            )
            turn_text = str(turn_result.get("text", "")).strip()
            last_run = turn_result.get("run")
            total_duration_ms = max(total_duration_ms, int(turn_result.get("duration_ms", 0)))

            speaker_id = str(turn["speaker"])
            segments.append(
                {
                    "speaker_id": speaker_id,
                    "speaker_label": speaker_label_mapping.get(speaker_id, speaker_id),
                    "start_ms": turn["start_ms"],
                    "end_ms": turn["end_ms"],
                    "text": turn_text,
                }
            )

    return segments, last_run, total_duration_ms


def diarization_options_from_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    def _get(name: str, default: Any = None) -> Any:
        env_name = f"DIARIZATION_{name}"
        if name in mapping:
            return mapping[name]
        if env_name in mapping:
            return mapping[env_name]
        return default

    def _bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"true", "1", "yes"}

    return {
        "enabled": _bool(_get("ENABLED", _get("enabled")), False),
        "min_turn_ms": int(_get("MIN_TURN_MS", _get("min_turn_ms", 400))),
        "sortformer_model_id": mapping.get("SORTFORMER_MODEL_ID", "nvidia/diar_sortformer_4spk-v1"),
        "sortformer_device": mapping.get("SORTFORMER_DEVICE", "cuda"),
        "sortformer_max_duration_s": float(mapping.get("SORTFORMER_MAX_DURATION_S", 300)),
        "sortformer_venv_python": mapping.get("SORTFORMER_VENV_PYTHON"),
        "sortformer_chunk_s": float(mapping.get("SORTFORMER_CHUNK_S", 240)),
        "sortformer_chunk_overlap_s": float(mapping.get("SORTFORMER_CHUNK_OVERLAP_S", 20)),
        "sortformer_use_daemon": _bool(mapping.get("SORTFORMER_USE_DAEMON"), True),
    }


def transcribe_wav_diarized(
    wav_path: Path,
    *,
    transcribe_options: dict[str, Any],
    diarization_options: dict[str, Any] | None = None,
    tracker: PipelineTracker | None = None,
) -> dict[str, Any]:
    diar_opts = diarization_options or {}
    diarization_request = {
        "wav_path": wav_path,
        "min_turn_ms": int(diar_opts.get("min_turn_ms", 400)),
        "model_id": str(diar_opts.get("sortformer_model_id", "nvidia/diar_sortformer_4spk-v1")),
    }
    t0 = time.perf_counter()
    from app.services.diarization_sortformer import diarize_wav_sortformer_chunked

    diarization_result = diarize_wav_sortformer_chunked(
        wav_path,
        chunk_s=diar_opts.get("sortformer_chunk_s", 240.0),
        overlap_s=diar_opts.get("sortformer_chunk_overlap_s", 20.0),
        model_id=diar_opts.get("sortformer_model_id", "nvidia/diar_sortformer_4spk-v1"),
        max_duration_s=diar_opts.get("sortformer_max_duration_s", 300.0),
        device=diar_opts.get("sortformer_device", "cuda"),
        min_turn_ms=diarization_request["min_turn_ms"],
        venv_python=diar_opts.get("sortformer_venv_python"),
        use_daemon=diar_opts.get("sortformer_use_daemon", True),
    )
    if tracker:
        tracker.record(
            TRANSCRIBE_01_DIARIZATION,
            request=diarization_request,
            response=diarization_result,
            duration_ms=(time.perf_counter() - t0) * 1000,
        )

    turns = diarization_result["turns"]
    if not turns:
        t1 = time.perf_counter()
        result = transcribe.transcribe_wav(
            wav_path,
            **_sequential_transcribe_options(transcribe_options),
        )
        if tracker:
            tracker.record(
                TRANSCRIBE_02_WHISPER,
                request={"wav_path": wav_path, **transcribe_options, "fallback": "no_turns"},
                response={
                    "text": result.get("text"),
                    "duration_ms": result.get("duration_ms"),
                    "run": result.get("run"),
                },
                duration_ms=(time.perf_counter() - t1) * 1000,
            )
            tracker.skip(
                TRANSCRIBE_03_FORMAT_SPEAKERS,
                reason="no_diarization_turns",
            )
        result["diarization"] = {
            **diarization_result,
            "fallback": "no_turns_full_file_transcription",
            "speaker_label_mapping": {},
        }
        return result

    speaker_label_mapping = speaker_label_map(diarization_result.get("speakers", []))
    alignment_turns = diarization_result.get("alignment_turns") or turns

    # Respects the configured inference_mode (e.g. batched) instead of forcing
    # sequential — faster-whisper's BatchedInferencePipeline.transcribe()
    # supports word_timestamps directly (verified: valid, chronologically
    # ordered timestamps), so there's no need to force sequential here just
    # to get word-level alignment for the diarization merge.
    full_options = dict(transcribe_options)
    full_options["word_timestamps"] = True
    t1 = time.perf_counter()
    full_result = transcribe.transcribe_wav(wav_path, **full_options)
    if tracker:
        tracker.record(
            TRANSCRIBE_02_WHISPER,
            request={"wav_path": wav_path, **full_options},
            response={
                "text": full_result.get("text"),
                "duration_ms": full_result.get("duration_ms"),
                "word_count": len(_collect_words(full_result)),
                "run": full_result.get("run"),
            },
            duration_ms=(time.perf_counter() - t1) * 1000,
        )
    words = _collect_words(full_result)

    transcription_mode = "per_turn"
    segments: list[dict[str, Any]]
    last_run: dict[str, Any] | None
    total_duration_ms: int

    if words and alignment_turns:
        segments = _segments_from_aligned_words(
            words,
            alignment_turns=alignment_turns,
            speaker_label_mapping=speaker_label_mapping,
        )
        last_run = full_result.get("run")
        total_duration_ms = int(full_result.get("duration_ms", 0))
        transcription_mode = "word_alignment"
    else:
        segments, last_run, total_duration_ms = _transcribe_turns(
            wav_path,
            turns,
            transcribe_options=transcribe_options,
            speaker_label_mapping=speaker_label_mapping,
        )

    labeled_text = format_speaker_transcript(segments)
    plain_text = " ".join(str(segment.get("text", "")).strip() for segment in segments if segment.get("text"))

    if tracker:
        tracker.record(
            TRANSCRIBE_03_FORMAT_SPEAKERS,
            request={
                "transcription_mode": transcription_mode,
                "speaker_label_mapping": speaker_label_mapping,
                "segment_count": len(segments),
            },
            response={
                "text": labeled_text,
                "plain_text": plain_text,
                "segments": segments,
            },
        )

    return {
        "text": labeled_text,
        "plain_text": plain_text,
        "language": transcribe_options.get("language", "pt"),
        "duration_ms": total_duration_ms,
        "segments": segments,
        "diarization": {
            **diarization_result,
            "speaker_label_mapping": speaker_label_mapping,
            "turns_transcribed": len(segments),
            "transcription_mode": transcription_mode,
        },
        "run": last_run,
        "diarized": True,
    }
