from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH


def read_wav(wav_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for diarization step")
        audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
    return audio, sample_rate


def write_wav_slice(
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
    audio, _ = read_wav(source_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    write_wav_slice(output_wav, audio, start_ms=start_ms, end_ms=end_ms)
    return output_wav
