import wave
from pathlib import Path

import numpy as np

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_EPS = 1e-10

try:
    from numba import njit

    @njit(cache=True)
    def _smooth_gain_numba(gain: np.ndarray, attack: float, release: float) -> np.ndarray:
        smoothed = np.empty_like(gain)
        smoothed[0] = gain[0]
        for index in range(1, len(gain)):
            coefficient = attack if gain[index] > smoothed[index - 1] else release
            smoothed[index] = coefficient * smoothed[index - 1] + (1.0 - coefficient) * gain[index]
        return smoothed

    _SMOOTH_GAIN_IMPL = "numba"
except ImportError:  # pragma: no cover - numba optional at runtime
    _SMOOTH_GAIN_IMPL = "python"

    def _smooth_gain_numba(gain: np.ndarray, attack: float, release: float) -> np.ndarray:
        smoothed = np.empty_like(gain)
        smoothed[0] = gain[0]
        for index in range(1, len(gain)):
            coefficient = attack if gain[index] > smoothed[index - 1] else release
            smoothed[index] = coefficient * smoothed[index - 1] + (1.0 - coefficient) * gain[index]
        return smoothed


def _read_wav(wav_path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for AGC step")

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


def _smooth_gain(
    gain: np.ndarray,
    sample_rate: int,
    *,
    attack_ms: float = 5.0,
    release_ms: float = 50.0,
) -> np.ndarray:
    attack = np.exp(-1.0 / max(sample_rate * attack_ms / 1000, 1))
    release = np.exp(-1.0 / max(sample_rate * release_ms / 1000, 1))
    return _smooth_gain_numba(gain.astype(np.float32, copy=False), attack, release)


def apply_agc_to_audio(
    audio_int16: np.ndarray,
    *,
    sample_rate: int = SAMPLE_RATE,
    target_dbfs: float = -20.0,
    max_gain_db: float = 12.0,
    window_ms: int = 30,
) -> np.ndarray:
    audio = audio_int16.astype(np.float32) / 32768.0

    frame_length = max(int(sample_rate * window_ms / 1000), 1)
    target_rms = 10 ** (target_dbfs / 20.0)
    max_gain = 10 ** (max_gain_db / 20.0)

    frame_count = max((len(audio) + frame_length - 1) // frame_length, 1)
    padded_length = frame_count * frame_length
    padded = np.zeros(padded_length, dtype=np.float32)
    padded[: len(audio)] = audio

    frames = padded.reshape(frame_count, frame_length)
    rms = np.sqrt(np.mean(frames**2, axis=1) + _EPS)
    frame_gain = target_rms / rms
    frame_gain = np.minimum(frame_gain, max_gain)

    sample_gain = np.repeat(frame_gain, frame_length)[: len(audio)]
    sample_gain = _smooth_gain(sample_gain, sample_rate)
    processed = np.clip(audio * sample_gain, -1.0, 1.0)

    return np.clip(processed * 32768.0, -32768, 32767).astype(np.int16)


def apply_agc(
    wav_path: Path,
    *,
    target_dbfs: float = -20.0,
    max_gain_db: float = 12.0,
    window_ms: int = 30,
) -> Path:
    audio_int16, sample_rate, channels, sample_width = _read_wav(wav_path)
    processed_int16 = apply_agc_to_audio(
        audio_int16,
        sample_rate=sample_rate,
        target_dbfs=target_dbfs,
        max_gain_db=max_gain_db,
        window_ms=window_ms,
    )
    _write_wav(
        wav_path,
        processed_int16,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    return wav_path
