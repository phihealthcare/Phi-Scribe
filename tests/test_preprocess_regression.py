import wave
from pathlib import Path

import numpy as np
import pytest

from app.services.audio_processor import preprocess_audio
from benchmarks.stack_config import merge_stack_env, stack_env_to_preprocess_kwargs


def _write_test_wav(path: Path, *, seconds: float = 2.0, sample_rate: int = 16_000) -> None:
    t = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
    audio = (0.15 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.tobytes())


@pytest.fixture
def production_stack_kwargs() -> dict:
    stack_env = merge_stack_env(
        {
            "DENOISE_ENABLED": True,
            "DENOISE_PROP_DECREASE": 0.6,
            "HPF_ENABLED": True,
            "HPF_CUTOFF_HZ": 80,
            "LPF_ENABLED": False,
            "AGC_ENABLED": True,
            "AGC_TARGET_DBFS": -20,
            "AGC_MAX_GAIN_DB": 12,
            "AGC_WINDOW_MS": 30,
            "LOUDNESS_ENABLED": True,
            "LOUDNESS_MODE": "lufs",
            "LOUDNESS_TARGET_LUFS": -23,
            "LOUDNESS_TRUE_PEAK": -1.5,
            "LOUDNESS_LRA": 11,
            "VAD_ENABLED": True,
            "VAD_THRESHOLD": 0.35,
            "VAD_MIN_SPEECH_DURATION_MS": 100,
            "VAD_MIN_SILENCE_DURATION_MS": 2500,
            "VAD_SPEECH_PAD_MS": 600,
        }
    )
    kwargs = stack_env_to_preprocess_kwargs(stack_env)
    kwargs["export_pcm_enabled"] = False
    return kwargs


def test_preprocess_production_stack_runs(tmp_path: Path, production_stack_kwargs: dict) -> None:
    pytest.importorskip("noisereduce")
    input_wav = tmp_path / "input.wav"
    output_wav = tmp_path / "output.wav"
    _write_test_wav(input_wav, seconds=1.0)

    processed = preprocess_audio(input_wav, output_wav, **production_stack_kwargs)

    assert output_wav.is_file()
    assert "normalize" in processed["stages"]
    assert processed["wav"]["duration_ms"] > 0
