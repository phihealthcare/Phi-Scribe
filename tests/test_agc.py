import wave

import numpy as np
import pytest

from app.services.agc import _smooth_gain_numba, apply_agc_to_audio


def _python_smooth_gain(gain: np.ndarray, attack: float, release: float) -> np.ndarray:
    smoothed = np.empty_like(gain)
    smoothed[0] = gain[0]
    for index in range(1, len(gain)):
        coefficient = attack if gain[index] > smoothed[index - 1] else release
        smoothed[index] = coefficient * smoothed[index - 1] + (1.0 - coefficient) * gain[index]
    return smoothed


def test_smooth_gain_numba_matches_python_reference() -> None:
    rng = np.random.default_rng(0)
    gain = rng.uniform(0.05, 1.0, size=16_000).astype(np.float32)
    attack = np.exp(-1.0 / max(16_000 * 5 / 1000, 1))
    release = np.exp(-1.0 / max(16_000 * 50 / 1000, 1))

    expected = _python_smooth_gain(gain, attack, release)
    actual = _smooth_gain_numba(gain, attack, release)

    np.testing.assert_allclose(actual, expected, rtol=1e-6, atol=1e-6)


def test_apply_agc_to_audio_is_deterministic() -> None:
    sample_rate = 16_000
    t = np.linspace(0, 1, sample_rate, endpoint=False)
    audio = (0.2 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

    first = apply_agc_to_audio(audio, sample_rate=sample_rate)
    second = apply_agc_to_audio(audio, sample_rate=sample_rate)

    np.testing.assert_array_equal(first, second)
