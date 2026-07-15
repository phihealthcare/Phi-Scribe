import math
import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import pyloudnorm as pyln

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_EPS = 1e-10
_INPUT_INTEGRATED_PATTERN = re.compile(r"Input Integrated:\s+(-?\d+(?:\.\d+)?)\s+LUFS")
_OUTPUT_INTEGRATED_PATTERN = re.compile(r"Output Integrated:\s+(-?\d+(?:\.\d+)?)\s+LUFS")
_INPUT_TRUE_PEAK_PATTERN = re.compile(r"Input True Peak:\s+(-?\d+(?:\.\d+)?)\s+dBFS")
_OUTPUT_TRUE_PEAK_PATTERN = re.compile(r"Output True Peak:\s+(-?\d+(?:\.\d+)?)\s+dBFS")

_VALID_MODES = frozenset({"lufs", "lufs_fast", "peak"})


def _read_wav(wav_path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for loudness step")

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


def _peak_dbfs(audio: np.ndarray) -> float:
    peak = float(np.max(np.abs(audio)))
    if peak < _EPS:
        return -120.0
    return 20.0 * math.log10(peak)


def _parse_loudnorm_summary(stderr: str) -> dict[str, float | None]:
    def _first(pattern: re.Pattern[str]) -> float | None:
        match = pattern.search(stderr)
        return float(match.group(1)) if match else None

    return {
        "input_lufs": _first(_INPUT_INTEGRATED_PATTERN),
        "output_lufs": _first(_OUTPUT_INTEGRATED_PATTERN),
        "input_true_peak_dbfs": _first(_INPUT_TRUE_PEAK_PATTERN),
        "output_true_peak_dbfs": _first(_OUTPUT_TRUE_PEAK_PATTERN),
    }


def _apply_lufs(
    wav_path: Path,
    *,
    target_lufs: float,
    true_peak: float,
    loudness_range: float,
) -> dict[str, float | None]:
    """Single ffmpeg pass: loudnorm applies normalization and prints before/after summary."""
    temp_path = wav_path.with_suffix(".loudness.wav")
    filter_chain = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={loudness_range}:print_format=summary"
    )

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(wav_path),
            "-af",
            filter_chain,
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-sample_fmt",
            "s16",
            str(temp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    temp_path.replace(wav_path)
    return _parse_loudnorm_summary(result.stderr)


def _apply_lufs_fast(
    wav_path: Path,
    *,
    target_lufs: float,
    true_peak: float,
) -> dict[str, float | None]:
    """Measure integrated LUFS (pyloudnorm) and apply a constant gain + peak ceiling.

    Faster than ffmpeg loudnorm: no dynamics/LRA processing, one in-memory pass.
    """
    audio_int16, sample_rate, channels, sample_width = _read_wav(wav_path)
    audio = audio_int16.astype(np.float64) / 32768.0

    meter = pyln.Meter(sample_rate)
    try:
        input_lufs = float(meter.integrated_loudness(audio))
    except ValueError:
        # Too quiet / silent for BS.1770
        return {
            "input_lufs": None,
            "output_lufs": None,
            "input_true_peak_dbfs": _peak_dbfs(audio.astype(np.float32)),
            "output_true_peak_dbfs": _peak_dbfs(audio.astype(np.float32)),
            "applied_gain_db": 0.0,
        }

    if not math.isfinite(input_lufs):
        return {
            "input_lufs": None,
            "output_lufs": None,
            "input_true_peak_dbfs": _peak_dbfs(audio.astype(np.float32)),
            "output_true_peak_dbfs": _peak_dbfs(audio.astype(np.float32)),
            "applied_gain_db": 0.0,
        }

    gain_db = target_lufs - input_lufs
    gain_linear = 10 ** (gain_db / 20.0)
    normalized = audio * gain_linear

    # Soft true-peak ceiling (sample peak approximation of TP).
    peak_limit = 10 ** (true_peak / 20.0)
    peak = float(np.max(np.abs(normalized)))
    if peak > peak_limit and peak > _EPS:
        normalized = normalized * (peak_limit / peak)
        gain_db += 20.0 * math.log10(peak_limit / peak)

    output_lufs = float(meter.integrated_loudness(normalized))
    normalized_int16 = np.clip(normalized * 32768.0, -32768, 32767).astype(np.int16)
    _write_wav(
        wav_path,
        normalized_int16,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    return {
        "input_lufs": round(input_lufs, 2),
        "output_lufs": round(output_lufs, 2),
        "input_true_peak_dbfs": None,
        "output_true_peak_dbfs": None,
        "applied_gain_db": round(gain_db, 2),
    }


def _apply_peak(wav_path: Path, *, peak_target_dbfs: float) -> float:
    audio_int16, sample_rate, channels, sample_width = _read_wav(wav_path)
    audio = audio_int16.astype(np.float32) / 32768.0

    peak_linear = float(np.max(np.abs(audio)))
    target_linear = 10 ** (peak_target_dbfs / 20.0)

    if peak_linear < _EPS:
        applied_gain_db = 0.0
        normalized = audio
    else:
        gain = target_linear / peak_linear
        applied_gain_db = 20.0 * math.log10(gain)
        normalized = np.clip(audio * gain, -1.0, 1.0)

    normalized_int16 = np.clip(normalized * 32768.0, -32768, 32767).astype(np.int16)
    _write_wav(
        wav_path,
        normalized_int16,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    return applied_gain_db


def apply_loudness(
    wav_path: Path,
    *,
    mode: str = "lufs",
    target_lufs: float = -23.0,
    true_peak: float = -1.5,
    loudness_range: float = 11.0,
    peak_target_dbfs: float = -1.0,
) -> dict:
    mode = mode.lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown loudness mode: {mode}")

    audio_int16, _, _, _ = _read_wav(wav_path)
    audio = audio_int16.astype(np.float32) / 32768.0
    input_peak_dbfs = _peak_dbfs(audio)

    if mode == "lufs":
        summary = _apply_lufs(
            wav_path,
            target_lufs=target_lufs,
            true_peak=true_peak,
            loudness_range=loudness_range,
        )
        input_lufs = summary.get("input_lufs")
        output_lufs = summary.get("output_lufs")
        audio_int16, _, _, _ = _read_wav(wav_path)
        output_peak_dbfs = _peak_dbfs(audio_int16.astype(np.float32) / 32768.0)
        applied_gain_db = 0.0
        if input_peak_dbfs > -120 and output_peak_dbfs > -120:
            applied_gain_db = output_peak_dbfs - input_peak_dbfs
    elif mode == "lufs_fast":
        summary = _apply_lufs_fast(
            wav_path,
            target_lufs=target_lufs,
            true_peak=true_peak,
        )
        input_lufs = summary.get("input_lufs")
        output_lufs = summary.get("output_lufs")
        applied_gain_db = float(summary.get("applied_gain_db") or 0.0)
        audio_int16, _, _, _ = _read_wav(wav_path)
        output_peak_dbfs = _peak_dbfs(audio_int16.astype(np.float32) / 32768.0)
    else:
        input_lufs = None
        applied_gain_db = _apply_peak(wav_path, peak_target_dbfs=peak_target_dbfs)
        audio_int16, _, _, _ = _read_wav(wav_path)
        output_peak_dbfs = _peak_dbfs(audio_int16.astype(np.float32) / 32768.0)
        output_lufs = None

    return {
        "mode": mode,
        "input_lufs": input_lufs,
        "output_lufs": output_lufs,
        "input_peak_dbfs": round(input_peak_dbfs, 2),
        "output_peak_dbfs": round(output_peak_dbfs, 2),
        "applied_gain_db": round(applied_gain_db, 2),
    }
