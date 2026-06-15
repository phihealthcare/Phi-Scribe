import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

def _read_wav(wav_path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for filter step")

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


def _build_sos(sample_rate: int, cutoff_hz: float, btype: str, order: int):
    nyquist = sample_rate / 2
    normalized = min(cutoff_hz / nyquist, 0.99)
    return butter(order, normalized, btype=btype, output="sos")


def apply_band_filters(
    wav_path: Path,
    *,
    hpf_hz: float | None = None,
    lpf_hz: float | None = None,
    order: int = 2,
) -> Path:
    if hpf_hz is None and lpf_hz is None:
        return wav_path

    audio_int16, sample_rate, channels, sample_width = _read_wav(wav_path)
    audio = audio_int16.astype(np.float32) / 32768.0

    if hpf_hz is not None:
        audio = sosfiltfilt(_build_sos(sample_rate, hpf_hz, "highpass", order), audio)

    if lpf_hz is not None:
        # Audio is 16 kHz after normalize (Nyquist 8 kHz); use ~7–7.5 kHz, not 10–12 kHz.
        audio = sosfiltfilt(_build_sos(sample_rate, lpf_hz, "lowpass", order), audio)

    filtered_int16 = np.clip(audio * 32768.0, -32768, 32767).astype(np.int16)
    _write_wav(
        wav_path,
        filtered_int16,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    return wav_path


def apply_highpass(wav_path: Path, *, cutoff_hz: float = 80.0, order: int = 2) -> Path:
    return apply_band_filters(wav_path, hpf_hz=cutoff_hz, order=order)


def apply_lowpass(wav_path: Path, *, cutoff_hz: float = 7500.0, order: int = 2) -> Path:
    return apply_band_filters(wav_path, lpf_hz=cutoff_hz, order=order)
