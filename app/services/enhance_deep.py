import math
import sys
import types
import wave
from pathlib import Path

import numpy as np
import torch
from scipy.signal import resample_poly

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_EPS = 1e-10
_NATIVE_SAMPLE_RATE = 48_000
_UPSAMPLE = 3
# Process ~15 s segments on CUDA to avoid VRAM spikes on long clinical recordings.
_CUDA_CHUNK_SECONDS = 15
_CUDA_CHUNK_SAMPLES_16K = _CUDA_CHUNK_SECONDS * SAMPLE_RATE
_model_cache: dict | None = None
_df_enhance_module = None


def _peak_dbfs(audio: np.ndarray) -> float:
    peak = float(np.max(np.abs(audio)))
    if peak < _EPS:
        return -120.0
    return 20.0 * math.log10(peak)


def _ensure_torchaudio_compat() -> None:
    if "torchaudio.backend.common" in sys.modules:
        return

    backend = types.ModuleType("torchaudio.backend")
    common = types.ModuleType("torchaudio.backend.common")

    class AudioMetaData:
        def __init__(self, sample_rate: int = _NATIVE_SAMPLE_RATE, num_frames: int = 0, num_channels: int = 1):
            self.sample_rate = sample_rate
            self.num_frames = num_frames
            self.num_channels = num_channels

    common.AudioMetaData = AudioMetaData
    backend.common = common
    sys.modules["torchaudio.backend"] = backend
    sys.modules["torchaudio.backend.common"] = common


def _import_deepfilter() -> tuple:
    global _df_enhance_module
    try:
        _ensure_torchaudio_compat()
        import importlib

        _df_enhance_module = importlib.import_module("df.enhance")
        enhance = _df_enhance_module.enhance
        init_df = _df_enhance_module.init_df
    except ImportError as exc:
        raise RuntimeError(
            "deepfilternet is not installed. Install it with: pip install deepfilternet"
        ) from exc
    return enhance, init_df


def resolve_device(device: str) -> dict[str, str | bool]:
    requested_device = device.lower()
    cuda_available = torch.cuda.is_available()

    if requested_device == "cuda" and cuda_available:
        resolved_device = "cuda"
    else:
        resolved_device = "cpu"

    return {
        "requested_device": requested_device,
        "device": resolved_device,
        "cuda_available": cuda_available,
        "fallback_to_cpu": requested_device == "cuda" and resolved_device == "cpu",
    }


def _resolve_device(device: str) -> str:
    return str(resolve_device(device)["device"])


def _clear_model_cache() -> None:
    global _model_cache
    _model_cache = None


def _clear_cuda_memory() -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def release_gpu_memory() -> None:
    """Drop cached DeepFilterNet weights and free CUDA memory for other stages."""
    _clear_model_cache()
    _clear_cuda_memory()


def _patch_df_device(resolved_device: str) -> None:
    import df.modules as df_modules
    import df.utils as df_utils

    device = torch.device("cuda:0" if resolved_device == "cuda" else "cpu")

    def _get_device():
        return device

    df_utils.get_device = _get_device
    df_modules.get_device = _get_device
    if _df_enhance_module is not None:
        _df_enhance_module.get_device = _get_device


def _get_model(*, model: str, device: str, post_filter: bool):
    global _model_cache
    enhance, init_df = _import_deepfilter()

    resolved_device = _resolve_device(device)
    cache_key = (model, resolved_device, post_filter)

    if _model_cache is not None and _model_cache["key"] == cache_key:
        return enhance, _model_cache["model"], _model_cache["df_state"], resolved_device

    _patch_df_device(resolved_device)
    model_obj, df_state, _ = init_df(
        model_base_dir=model,
        post_filter=post_filter,
        config_allow_defaults=True,
        log_file=None,
    )
    _model_cache = {
        "key": cache_key,
        "model": model_obj,
        "df_state": df_state,
    }
    return enhance, model_obj, df_state, resolved_device


def _read_wav(wav_path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for enhance_deep step")

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


def _enhance_48k_tensor(
    enhance,
    model,
    df_state,
    audio_48k: np.ndarray,
    *,
    atten_lim_db: float | None,
    chunked: bool,
) -> np.ndarray:
    if len(audio_48k) == 0:
        return audio_48k

    if not chunked:
        audio_tensor = torch.from_numpy(audio_48k).unsqueeze(0)
        enhanced_48k = enhance(
            model,
            df_state,
            audio_tensor,
            pad=True,
            atten_lim_db=atten_lim_db,
        )
        return enhanced_48k.squeeze(0).cpu().numpy()

    chunk_samples_48k = _CUDA_CHUNK_SAMPLES_16K * _UPSAMPLE
    outputs: list[np.ndarray] = []
    for start in range(0, len(audio_48k), chunk_samples_48k):
        chunk = audio_48k[start : start + chunk_samples_48k]
        audio_tensor = torch.from_numpy(chunk).unsqueeze(0)
        enhanced_chunk = enhance(
            model,
            df_state,
            audio_tensor,
            pad=True,
            atten_lim_db=atten_lim_db,
        )
        outputs.append(enhanced_chunk.squeeze(0).cpu().numpy())
        _clear_cuda_memory()

    return np.concatenate(outputs) if outputs else audio_48k


def _match_length(audio: np.ndarray, target_length: int) -> np.ndarray:
    if len(audio) > target_length:
        return audio[:target_length]
    if len(audio) < target_length:
        return np.pad(audio, (0, target_length - len(audio)))
    return audio


def _enhance_audio(
    audio_int16: np.ndarray,
    *,
    model_name: str,
    device: str,
    post_filter: bool,
    atten_lim_db: float | None,
) -> tuple[np.ndarray, dict]:
    if len(audio_int16) == 0:
        return audio_int16, {"chunked": False, "chunks_processed": 0}

    enhance, model, df_state, resolved_device = _get_model(
        model=model_name,
        device=device,
        post_filter=post_filter,
    )
    _patch_df_device(resolved_device)

    chunked = resolved_device == "cuda" and len(audio_int16) > _CUDA_CHUNK_SAMPLES_16K
    audio_48k = resample_poly(audio_int16.astype(np.float64), _UPSAMPLE, 1).astype(np.float32)
    enhanced_48k = _enhance_48k_tensor(
        enhance,
        model,
        df_state,
        audio_48k,
        atten_lim_db=atten_lim_db,
        chunked=chunked,
    )
    enhanced = resample_poly(enhanced_48k.astype(np.float64), 1, _UPSAMPLE)
    enhanced = _match_length(enhanced, len(audio_int16))

    chunks_processed = 0
    if chunked:
        chunks_processed = math.ceil(len(audio_48k) / (_CUDA_CHUNK_SAMPLES_16K * _UPSAMPLE))

    enhanced_int16 = np.clip(enhanced * 32768.0, -32768, 32767).astype(np.int16)
    return enhanced_int16, {
        "chunked": chunked,
        "chunks_processed": chunks_processed,
        "resolved_device": resolved_device,
        "model": model,
    }


def apply_enhance_deep(
    wav_path: Path,
    *,
    model: str = "DeepFilterNet3",
    device: str = "cpu",
    post_filter: bool = False,
    atten_lim_db: float | None = None,
) -> dict:
    device_info = resolve_device(device)
    audio_int16, sample_rate, channels, sample_width = _read_wav(wav_path)
    input_peak_dbfs = _peak_dbfs(audio_int16.astype(np.float32) / 32768.0)

    fallback_to_cpu = device_info["fallback_to_cpu"]
    fallback_reason = None

    try:
        enhanced_int16, run_info = _enhance_audio(
            audio_int16,
            model_name=model,
            device=device,
            post_filter=post_filter,
            atten_lim_db=atten_lim_db,
        )
    except torch.cuda.OutOfMemoryError:
        _clear_cuda_memory()
        _clear_model_cache()
        fallback_to_cpu = True
        fallback_reason = "cuda_oom"
        enhanced_int16, run_info = _enhance_audio(
            audio_int16,
            model_name=model,
            device="cpu",
            post_filter=post_filter,
            atten_lim_db=atten_lim_db,
        )

    _write_wav(
        wav_path,
        enhanced_int16,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )

    output_peak_dbfs = _peak_dbfs(enhanced_int16.astype(np.float32) / 32768.0)
    model_obj = run_info["model"]
    resolved_device = str(run_info["resolved_device"])
    model_device = str(next(model_obj.parameters()).device)

    return {
        "engine": "deepfilternet",
        "model": model,
        "requested_device": device_info["requested_device"],
        "device": resolved_device,
        "model_device": model_device,
        "cuda_available": device_info["cuda_available"],
        "fallback_to_cpu": fallback_to_cpu,
        "fallback_reason": fallback_reason,
        "chunked": run_info["chunked"],
        "chunks_processed": run_info["chunks_processed"],
        "input_peak_dbfs": round(input_peak_dbfs, 2),
        "output_peak_dbfs": round(output_peak_dbfs, 2),
        "native_sample_rate_hz": _NATIVE_SAMPLE_RATE,
        "post_filter": post_filter,
        "atten_lim_db": atten_lim_db,
    }
