import math
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_EPS = 1e-10
_LUFS_PATTERN = re.compile(r"^\s*I:\s+(-?\d+(?:\.\d+)?)\s+LUFS")


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


def _measure_lufs(wav_path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(wav_path),
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    for line in reversed(result.stderr.splitlines()):
        match = _LUFS_PATTERN.search(line)
        if match:
            return float(match.group(1))

    return None


def _apply_lufs(
    wav_path: Path,
    *,
    target_lufs: float,
    true_peak: float,
    loudness_range: float,
) -> None:
    temp_path = wav_path.with_suffix(".loudness.wav")
    filter_chain = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={loudness_range}"

    subprocess.run(
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
    if mode not in {"lufs", "peak"}:
        raise ValueError(f"Unknown loudness mode: {mode}")

    audio_int16, _, _, _ = _read_wav(wav_path)
    audio = audio_int16.astype(np.float32) / 32768.0
    input_peak_dbfs = _peak_dbfs(audio)
    input_lufs = _measure_lufs(wav_path) if mode == "lufs" else None

    if mode == "lufs":
        _apply_lufs(
            wav_path,
            target_lufs=target_lufs,
            true_peak=true_peak,
            loudness_range=loudness_range,
        )
        applied_gain_db = 0.0
    else:
        applied_gain_db = _apply_peak(wav_path, peak_target_dbfs=peak_target_dbfs)

    audio_int16, _, _, _ = _read_wav(wav_path)
    audio = audio_int16.astype(np.float32) / 32768.0
    output_peak_dbfs = _peak_dbfs(audio)
    output_lufs = _measure_lufs(wav_path) if mode == "lufs" else None

    if mode == "lufs" and input_peak_dbfs > -120 and output_peak_dbfs > -120:
        applied_gain_db = output_peak_dbfs - input_peak_dbfs

    return {
        "mode": mode,
        "input_lufs": input_lufs,
        "output_lufs": output_lufs,
        "input_peak_dbfs": round(input_peak_dbfs, 2),
        "output_peak_dbfs": round(output_peak_dbfs, 2),
        "applied_gain_db": round(applied_gain_db, 2),
    }
