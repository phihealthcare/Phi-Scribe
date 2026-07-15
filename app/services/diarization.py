from __future__ import annotations

import os
import wave
from pathlib import Path
from typing import Any

import numpy as np

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_DEFAULT_MODEL = "pyannote/speaker-diarization-community-1"
_pipeline = None
_pipeline_key: tuple[str, str] | None = None


def _read_wav(wav_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for diarization step")
        audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
    return audio, sample_rate


def _write_wav_slice(
    wav_path: Path,
    audio: np.ndarray,
    *,
    start_ms: int,
    end_ms: int,
) -> None:
    start_sample = int(start_ms / 1000 * SAMPLE_RATE)
    end_sample = int(end_ms / 1000 * SAMPLE_RATE)
    start_sample = max(0, min(start_sample, len(audio)))
    end_sample = max(start_sample, min(end_sample, len(audio)))
    slice_audio = audio[start_sample:end_sample]
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(slice_audio.tobytes())


def extract_turn_wav(
    source_wav: Path,
    output_wav: Path,
    *,
    start_ms: int,
    end_ms: int,
) -> Path:
    audio, _ = _read_wav(source_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    _write_wav_slice(output_wav, audio, start_ms=start_ms, end_ms=end_ms)
    return output_wav


def _resolve_hf_token(explicit: str | None = None) -> str:
    token = (explicit or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "Hugging Face token required for diarization. "
            "Set HF_TOKEN in .env and accept the model license on Hugging Face."
        )
    return token


def _get_pipeline(*, model_id: str, hf_token: str):
    global _pipeline, _pipeline_key
    key = (model_id, hf_token[:8])
    if _pipeline is not None and _pipeline_key == key:
        return _pipeline

    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise RuntimeError(
            "pyannote.audio is not installed. Install with: pip install pyannote.audio"
        ) from exc

    try:
        _pipeline = Pipeline.from_pretrained(model_id, token=hf_token)
    except TypeError:
        _pipeline = Pipeline.from_pretrained(model_id, use_auth_token=hf_token)
    device = os.environ.get("DIARIZATION_DEVICE", "").strip().lower()
    if not device:
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    try:
        import torch

        _pipeline.to(torch.device(device))
    except Exception:
        pass

    _pipeline_key = key
    return _pipeline


def _merge_consecutive_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not turns:
        return []
    merged: list[dict[str, Any]] = [dict(turns[0])]
    for turn in turns[1:]:
        if turn["speaker"] == merged[-1]["speaker"]:
            merged[-1]["end_ms"] = max(merged[-1]["end_ms"], turn["end_ms"])
        else:
            merged.append(dict(turn))
    return merged


def _annotation_to_turns(annotation: Any, *, min_turn_ms: int) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        start_ms = int(turn.start * 1000)
        end_ms = int(turn.end * 1000)
        if end_ms - start_ms < min_turn_ms:
            continue
        turns.append(
            {
                "speaker": str(speaker),
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
        )
    return turns


def _turns_from_pipeline_output(output: Any, *, min_turn_ms: int) -> list[dict[str, Any]]:
    """Support pyannote 3.x Annotation and pyannote 4.x DiarizeOutput."""
    if hasattr(output, "itertracks"):
        return _annotation_to_turns(output, min_turn_ms=min_turn_ms)

    exclusive = getattr(output, "exclusive_speaker_diarization", None)
    if exclusive is not None:
        turns = _annotation_to_turns(exclusive, min_turn_ms=min_turn_ms)
        if turns:
            return turns

    speaker_diarization = getattr(output, "speaker_diarization", None)
    if speaker_diarization is not None:
        return _annotation_to_turns(speaker_diarization, min_turn_ms=min_turn_ms)

    raise TypeError(
        f"Unsupported diarization output type: {type(output).__name__}. "
        "Expected pyannote Annotation or DiarizeOutput."
    )


def diarize_wav(
    wav_path: Path,
    *,
    num_speakers: int = 2,
    min_turn_ms: int = 400,
    model_id: str = _DEFAULT_MODEL,
    hf_token: str | None = None,
) -> dict[str, Any]:
    pipeline = _get_pipeline(model_id=model_id, hf_token=_resolve_hf_token(hf_token))
    diarization_output = pipeline(str(wav_path), num_speakers=num_speakers)

    turns = _turns_from_pipeline_output(diarization_output, min_turn_ms=min_turn_ms)
    turns.sort(key=lambda item: item["start_ms"])
    alignment_turns = [dict(turn) for turn in turns]
    merged_turns = _merge_consecutive_turns(turns)
    speakers = sorted({turn["speaker"] for turn in merged_turns})

    return {
        "model": model_id,
        "num_speakers": num_speakers,
        "min_turn_ms": min_turn_ms,
        "speakers": speakers,
        "alignment_turns": alignment_turns,
        "turns": merged_turns,
        "turn_count": len(merged_turns),
    }
