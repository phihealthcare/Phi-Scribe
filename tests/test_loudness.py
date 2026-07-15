"""Tests for loudness modes (lufs / lufs_fast / peak)."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.loudness import apply_loudness
from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH


def _write_tone(path: Path, *, seconds: float = 1.0, amplitude: float = 0.1) -> None:
    n = int(SAMPLE_RATE * seconds)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    audio = (amplitude * np.sin(2 * np.pi * 440.0 * t) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(audio.tobytes())


def test_lufs_fast_moves_toward_target(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_tone(wav, seconds=2.0, amplitude=0.05)
    result = apply_loudness(
        wav,
        mode="lufs_fast",
        target_lufs=-23.0,
        true_peak=-1.5,
    )
    assert result["mode"] == "lufs_fast"
    assert result["input_lufs"] is not None
    assert result["output_lufs"] is not None
    assert abs(float(result["output_lufs"]) - (-23.0)) < 1.5


def test_unknown_mode_raises(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_tone(wav)
    with pytest.raises(ValueError, match="Unknown loudness mode"):
        apply_loudness(wav, mode="not_a_mode")


def test_peak_mode_scales(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    _write_tone(wav, amplitude=0.25)
    result = apply_loudness(wav, mode="peak", peak_target_dbfs=-1.0)
    assert result["mode"] == "peak"
    assert result["output_peak_dbfs"] <= -0.5
    assert math.isfinite(result["applied_gain_db"])
