import wave
from pathlib import Path

import numpy as np
import torch
from silero_vad import collect_chunks, get_speech_timestamps, load_silero_vad

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_model = None

def _get_model():
    global _model
    if _model is None:
        _model = load_silero_vad()
    return _model


def _read_wav(wav_path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for VAD step")

        audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)

    return audio, sample_rate, channels, sample_width


def _write_wav(
    wav_path: Path,
    audio: np.ndarray,
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> None:
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.tobytes())


def _samples_to_ms(sample_index: int) -> int:
    return int(sample_index / SAMPLE_RATE * 1000)


def trim_silence(
    wav_path: Path,
    *,
    threshold: float,
    min_speech_duration_ms: int,
    min_silence_duration_ms: int,
    speech_pad_ms: int,
) -> dict:
    audio_int16, sample_rate, channels, sample_width = _read_wav(wav_path)
    original_duration_ms = _samples_to_ms(len(audio_int16))

    audio = torch.from_numpy(audio_int16.astype(np.float32) / 32768.0)
    model = _get_model()

    speech_timestamps = get_speech_timestamps(
        audio,
        model,
        threshold=threshold,
        sampling_rate=sample_rate,
        min_speech_duration_ms=min_speech_duration_ms,
        min_silence_duration_ms=min_silence_duration_ms,
        speech_pad_ms=speech_pad_ms,
    )

    speech_segments = [
        {"start_ms": _samples_to_ms(segment["start"]), "end_ms": _samples_to_ms(segment["end"])}
        for segment in speech_timestamps
    ]

    if not speech_timestamps:
        return {
            "original_duration_ms": original_duration_ms,
            "trimmed_duration_ms": original_duration_ms,
            "removed_silence_ms": 0,
            "speech_segments": [],
        }

    trimmed_audio = collect_chunks(speech_timestamps, audio)
    trimmed_int16 = np.clip(trimmed_audio.numpy() * 32768.0, -32768, 32767).astype(np.int16)
    _write_wav(
        wav_path,
        trimmed_int16,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )

    trimmed_duration_ms = _samples_to_ms(len(trimmed_int16))

    return {
        "original_duration_ms": original_duration_ms,
        "trimmed_duration_ms": trimmed_duration_ms,
        "removed_silence_ms": original_duration_ms - trimmed_duration_ms,
        "speech_segments": speech_segments,
    }