from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_STACK_ENV: dict[str, Any] = {
    "DENOISE_ENABLED": False,
    "DENOISE_PROP_DECREASE": 0.6,
    "ENHANCE_VOICE_ENABLED": False,
    "ENHANCE_DEEP_ENABLED": False,
    "ENHANCE_DEEP_MODEL": "DeepFilterNet3",
    "ENHANCE_DEEP_DEVICE": "cpu",
    "ENHANCE_DEEP_POST_FILTER": False,
    "ENHANCE_DEEP_ATTEN_LIM_DB": None,
    "HPF_ENABLED": False,
    "HPF_CUTOFF_HZ": 80.0,
    "LPF_ENABLED": False,
    "LPF_CUTOFF_HZ": 7500.0,
    "AGC_ENABLED": False,
    "AGC_TARGET_DBFS": -20.0,
    "AGC_MAX_GAIN_DB": 12.0,
    "AGC_WINDOW_MS": 30,
    "LOUDNESS_ENABLED": False,
    "LOUDNESS_MODE": "lufs",
    "LOUDNESS_TARGET_LUFS": -23.0,
    "LOUDNESS_TRUE_PEAK": -1.5,
    "LOUDNESS_LRA": 11.0,
    "LOUDNESS_PEAK_TARGET_DBFS": -1.0,
    "VAD_ENABLED": False,
    "VAD_THRESHOLD": 0.5,
    "VAD_MIN_SPEECH_DURATION_MS": 250,
    "VAD_MIN_SILENCE_DURATION_MS": 1000,
    "VAD_SPEECH_PAD_MS": 300,
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "1", "yes"}


def merge_stack_env(overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged = DEFAULT_STACK_ENV.copy()
    if overrides:
        merged.update(overrides)
    return merged


def stack_env_to_preprocess_kwargs(stack_env: dict[str, Any]) -> dict[str, Any]:
    return {
        "hpf_enabled": _as_bool(stack_env["HPF_ENABLED"]),
        "hpf_cutoff_hz": float(stack_env["HPF_CUTOFF_HZ"]),
        "lpf_enabled": _as_bool(stack_env["LPF_ENABLED"]),
        "lpf_cutoff_hz": float(stack_env["LPF_CUTOFF_HZ"]),
        "denoise_enabled": _as_bool(stack_env["DENOISE_ENABLED"]),
        "prop_decrease": float(stack_env["DENOISE_PROP_DECREASE"]),
        "enhance_voice_enabled": _as_bool(stack_env["ENHANCE_VOICE_ENABLED"]),
        "enhance_deep_enabled": _as_bool(stack_env["ENHANCE_DEEP_ENABLED"]),
        "enhance_deep_model": str(stack_env["ENHANCE_DEEP_MODEL"]),
        "enhance_deep_device": str(stack_env["ENHANCE_DEEP_DEVICE"]).lower(),
        "enhance_deep_post_filter": _as_bool(stack_env["ENHANCE_DEEP_POST_FILTER"]),
        "enhance_deep_atten_lim_db": stack_env["ENHANCE_DEEP_ATTEN_LIM_DB"],
        "agc_enabled": _as_bool(stack_env["AGC_ENABLED"]),
        "agc_target_dbfs": float(stack_env["AGC_TARGET_DBFS"]),
        "agc_max_gain_db": float(stack_env["AGC_MAX_GAIN_DB"]),
        "agc_window_ms": int(stack_env["AGC_WINDOW_MS"]),
        "loudness_enabled": _as_bool(stack_env["LOUDNESS_ENABLED"]),
        "loudness_mode": str(stack_env["LOUDNESS_MODE"]).lower(),
        "loudness_target_lufs": float(stack_env["LOUDNESS_TARGET_LUFS"]),
        "loudness_true_peak": float(stack_env["LOUDNESS_TRUE_PEAK"]),
        "loudness_lra": float(stack_env["LOUDNESS_LRA"]),
        "loudness_peak_target_dbfs": float(stack_env["LOUDNESS_PEAK_TARGET_DBFS"]),
        "vad_enabled": _as_bool(stack_env["VAD_ENABLED"]),
        "vad_threshold": float(stack_env["VAD_THRESHOLD"]),
        "vad_min_speech_duration_ms": int(stack_env["VAD_MIN_SPEECH_DURATION_MS"]),
        "vad_min_silence_duration_ms": int(stack_env["VAD_MIN_SILENCE_DURATION_MS"]),
        "vad_speech_pad_ms": int(stack_env["VAD_SPEECH_PAD_MS"]),
        "export_pcm_enabled": _as_bool(stack_env.get("EXPORT_PCM_ENABLED", False)),
    }


def resolve_whisper_block(whisper_cfg: dict[str, Any]) -> dict[str, Any]:
    """Resolve whisper YAML block (e.g. initial_prompt_file → initial_prompt)."""
    resolved = dict(whisper_cfg)
    prompt_file = resolved.pop("initial_prompt_file", None)
    if prompt_file and "initial_prompt" not in resolved:
        path = Path(prompt_file)
        if not path.is_absolute():
            path = ROOT / path
        resolved["initial_prompt"] = path.read_text(encoding="utf-8").strip()
    return resolved
