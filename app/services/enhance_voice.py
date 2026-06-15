import importlib.metadata
import importlib.util
import math
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

_EPS = 1e-10
_RNNOISE_UPSAMPLE = 3
_RNNOISE_NATIVE_RATE = 48_000
_rnnoise_module = None


def _peak_dbfs(audio: np.ndarray) -> float:
    peak = float(np.max(np.abs(audio)))
    if peak < _EPS:
        return -120.0
    return 20.0 * math.log10(peak)


def _load_rnnoise_module():
    global _rnnoise_module
    if _rnnoise_module is not None:
        return _rnnoise_module

    try:
        from pyrnnoise import RNNoise  # noqa: F401
        from pyrnnoise import rnnoise as rnnoise_module
    except ImportError:
        try:
            distribution = importlib.metadata.distribution("pyrnnoise")
            rnnoise_path = distribution.locate_file("pyrnnoise/rnnoise.py")
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                "pyrnnoise is not installed. Install it with: pip install pyrnnoise"
            ) from exc

        if not Path(rnnoise_path).is_file():
            raise RuntimeError(
                "pyrnnoise is installed but its RNNoise backend could not be loaded. "
                "Reinstall with: pip install pyrnnoise"
            )

        spec = importlib.util.spec_from_file_location("_phi_scribe_rnnoise", rnnoise_path)
        rnnoise_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rnnoise_module)

    _rnnoise_module = rnnoise_module
    return _rnnoise_module


def _read_wav(wav_path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for enhance_voice step")

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


def _denoise_with_rnnoise(audio_int16: np.ndarray, rnnoise) -> tuple[np.ndarray, list[float]]:
    if len(audio_int16) == 0:
        return audio_int16, []

    audio_48k = resample_poly(audio_int16.astype(np.float64), _RNNOISE_UPSAMPLE, 1).astype(np.int16)
    frame_size = rnnoise.FRAME_SIZE
    state = rnnoise.create()
    output_frames: list[np.ndarray] = []
    speech_probs: list[float] = []

    try:
        for start in range(0, len(audio_48k), frame_size):
            frame = audio_48k[start : start + frame_size]
            original_len = len(frame)
            if original_len < frame_size:
                frame = np.pad(frame, (0, frame_size - original_len))

            denoised_frame, speech_prob = rnnoise.process_frame(state, frame)
            denoised_frame = np.asarray(denoised_frame).reshape(-1)
            if isinstance(speech_prob, np.ndarray):
                speech_probs.append(float(speech_prob.flat[0]))
            else:
                speech_probs.append(float(speech_prob))
            output_frames.append(denoised_frame[:original_len])
    finally:
        rnnoise.destroy(state)

    denoised_48k = np.concatenate(output_frames) if output_frames else audio_48k
    denoised = resample_poly(denoised_48k.astype(np.float64), 1, _RNNOISE_UPSAMPLE)

    if len(denoised) > len(audio_int16):
        denoised = denoised[: len(audio_int16)]
    elif len(denoised) < len(audio_int16):
        denoised = np.pad(denoised, (0, len(audio_int16) - len(denoised)))

    return np.clip(denoised, -32768, 32767).astype(np.int16), speech_probs


def apply_enhance_voice(wav_path: Path) -> dict:
    rnnoise = _load_rnnoise_module()
    audio_int16, sample_rate, channels, sample_width = _read_wav(wav_path)
    input_peak_dbfs = _peak_dbfs(audio_int16.astype(np.float32) / 32768.0)

    denoised_int16, speech_probs = _denoise_with_rnnoise(audio_int16, rnnoise)
    _write_wav(
        wav_path,
        denoised_int16,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )

    output_peak_dbfs = _peak_dbfs(denoised_int16.astype(np.float32) / 32768.0)
    mean_speech_probability = (
        round(sum(speech_probs) / len(speech_probs), 4) if speech_probs else None
    )

    return {
        "engine": "rnnoise",
        "input_peak_dbfs": round(input_peak_dbfs, 2),
        "output_peak_dbfs": round(output_peak_dbfs, 2),
        "mean_speech_probability": mean_speech_probability,
        "frames_processed": len(speech_probs),
        "native_sample_rate_hz": _RNNOISE_NATIVE_RATE,
    }
