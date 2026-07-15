import wave
from pathlib import Path

import noisereduce as nr
import numpy as np

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

def apply_stationary(wav_path: Path, prop_decrease: float = 0.6) -> Path:
    audio_int16, sample_rate, channels, sample_width = _read_wav(wav_path)
    reduced_int16 = apply_stationary_to_int16(audio_int16, sample_rate=sample_rate, prop_decrease=prop_decrease)
    _write_wav(
        wav_path,
        reduced_int16,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    return wav_path


def apply_stationary_to_int16(
    audio_int16: np.ndarray,
    *,
    sample_rate: int = SAMPLE_RATE,
    prop_decrease: float = 0.6,
) -> np.ndarray:
    audio = audio_int16.astype(np.float32) / 32768.0
    reduced = nr.reduce_noise(
        y=audio,
        sr=sample_rate,
        prop_decrease=prop_decrease,
        stationary=True,
    )
    return np.clip(reduced * 32768.0, -32768, 32767).astype(np.int16)


def _read_wav(wav_path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for denoise step")

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
