from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from app.services import agc, denoise, enhance_deep, enhance_voice, filters, loudness, normalize, vad
from app.services.agc import _read_wav as read_wav_int16
from app.services.agc import _write_wav as write_wav_int16
from app.services.pipeline_steps import (
    UPLOAD_02_NORMALIZE,
    UPLOAD_03_FILTER_ENHANCE,
    UPLOAD_04_OUTPUT,
)
from app.services.upload_timing import UploadStepTimer

if TYPE_CHECKING:
    from app.services.pipeline_tracker import PipelineTracker


def preprocess_audio(
    input_path: Path,
    output_wav_path: Path,
    *,
    hpf_enabled: bool = False,
    hpf_cutoff_hz: float = 80.0,
    lpf_enabled: bool = False,
    lpf_cutoff_hz: float = 7500.0,
    denoise_enabled: bool = False,
    prop_decrease: float = 0.6,
    enhance_voice_enabled: bool = False,
    enhance_deep_enabled: bool = False,
    enhance_deep_model: str = "DeepFilterNet3",
    enhance_deep_device: str = "cpu",
    enhance_deep_post_filter: bool = False,
    enhance_deep_atten_lim_db: float | None = None,
    agc_enabled: bool = False,
    agc_target_dbfs: float = -20.0,
    agc_max_gain_db: float = 12.0,
    agc_window_ms: int = 30,
    loudness_enabled: bool = False,
    loudness_mode: str = "lufs",
    loudness_target_lufs: float = -23.0,
    loudness_true_peak: float = -1.5,
    loudness_lra: float = 11.0,
    loudness_peak_target_dbfs: float = -1.0,
    vad_enabled: bool = False,
    vad_threshold: float = 0.5,
    vad_min_speech_duration_ms: int = 250,
    vad_min_silence_duration_ms: int = 1000,
    vad_speech_pad_ms: int = 300,
    export_pcm_enabled: bool = False,
    tracker: PipelineTracker | None = None,
    timing: UploadStepTimer | None = None,
) -> dict:
    stages = ["normalize"]

    with timing.step("normalize") if timing else nullcontext():
        normalize.normalize_audio(input_path, output_wav_path)
        normalize_metadata = normalize.read_audio_metadata(output_wav_path)

    normalize_duration_ms = timing.last_step_duration_ms() if timing else None
    if tracker:
        tracker.record(
            UPLOAD_02_NORMALIZE,
            request={
                "input_path": input_path,
                "output_wav_path": output_wav_path,
                "target_sample_rate_hz": 16000,
                "target_channels": 1,
            },
            response=normalize_metadata,
            duration_ms=normalize_duration_ms,
        )

    filter_request = {
        "hpf_enabled": hpf_enabled,
        "hpf_cutoff_hz": hpf_cutoff_hz,
        "lpf_enabled": lpf_enabled,
        "lpf_cutoff_hz": lpf_cutoff_hz,
        "denoise_enabled": denoise_enabled,
        "prop_decrease": prop_decrease,
        "enhance_voice_enabled": enhance_voice_enabled,
        "enhance_deep_enabled": enhance_deep_enabled,
        "enhance_deep_model": enhance_deep_model,
        "agc_enabled": agc_enabled,
        "loudness_enabled": loudness_enabled,
        "vad_enabled": vad_enabled,
        "export_pcm_enabled": export_pcm_enabled,
    }

    filter_enhance_started = timing.step_count() if timing else 0
    in_memory_chain = (
        hpf_enabled
        or lpf_enabled
        or denoise_enabled
        or enhance_voice_enabled
        or enhance_deep_enabled
        or agc_enabled
    )

    result: dict = {"stages": stages}
    sample_rate = normalize_metadata["sample_rate"]
    channels = normalize_metadata["channels"]
    sample_width_bits = normalize_metadata["sample_width_bits"]
    sample_width = sample_width_bits // 8

    audio_int16: np.ndarray | None = None

    if in_memory_chain:
        with timing.step("read_wav_buffer") if timing else nullcontext():
            audio_int16, sample_rate, channels, sample_width = read_wav_int16(output_wav_path)

        if hpf_enabled or lpf_enabled:
            with timing.step("band_filters", hpf_enabled=hpf_enabled, lpf_enabled=lpf_enabled) if timing else nullcontext():
                audio_int16 = filters.apply_band_filters_to_int16(
                    audio_int16,
                    sample_rate=sample_rate,
                    hpf_hz=hpf_cutoff_hz if hpf_enabled else None,
                    lpf_hz=lpf_cutoff_hz if lpf_enabled else None,
                )
            if hpf_enabled:
                stages.append("remove_hum")
            if lpf_enabled:
                stages.append("reduce_sibilance")

        if enhance_deep_enabled:
            with timing.step("enhance_deep", model=enhance_deep_model, device=enhance_deep_device) if timing else nullcontext():
                write_wav_int16(
                    output_wav_path,
                    audio_int16,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width=sample_width,
                )
                result["enhance_deep"] = enhance_deep.apply_enhance_deep(
                    output_wav_path,
                    model=enhance_deep_model,
                    device=enhance_deep_device,
                    post_filter=enhance_deep_post_filter,
                    atten_lim_db=enhance_deep_atten_lim_db,
                )
                audio_int16, sample_rate, channels, sample_width = read_wav_int16(output_wav_path)
            stages.append("enhance_deep")
        elif enhance_voice_enabled:
            with timing.step("enhance_voice") if timing else nullcontext():
                write_wav_int16(
                    output_wav_path,
                    audio_int16,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width=sample_width,
                )
                result["enhance_voice"] = enhance_voice.apply_enhance_voice(output_wav_path)
                audio_int16, sample_rate, channels, sample_width = read_wav_int16(output_wav_path)
            stages.append("enhance_voice")
        elif denoise_enabled:
            with timing.step("denoise", prop_decrease=prop_decrease) if timing else nullcontext():
                audio_int16 = denoise.apply_stationary_to_int16(
                    audio_int16,
                    sample_rate=sample_rate,
                    prop_decrease=prop_decrease,
                )
            stages.append("denoise")

        if agc_enabled:
            with timing.step("agc", target_dbfs=agc_target_dbfs, max_gain_db=agc_max_gain_db) if timing else nullcontext():
                audio_int16 = agc.apply_agc_to_audio(
                    audio_int16,
                    sample_rate=sample_rate,
                    target_dbfs=agc_target_dbfs,
                    max_gain_db=agc_max_gain_db,
                    window_ms=agc_window_ms,
                )
            stages.append("agc")

        with timing.step("write_wav_buffer") if timing else nullcontext():
            write_wav_int16(
                output_wav_path,
                audio_int16,
                sample_rate=sample_rate,
                channels=channels,
                sample_width=sample_width,
            )
    elif hpf_enabled or lpf_enabled:
        # Legacy disk path when only band filters run without denoise/agc (rare stack combo).
        with timing.step("band_filters", hpf_enabled=hpf_enabled, lpf_enabled=lpf_enabled) if timing else nullcontext():
            filters.apply_band_filters(
                output_wav_path,
                hpf_hz=hpf_cutoff_hz if hpf_enabled else None,
                lpf_hz=lpf_cutoff_hz if lpf_enabled else None,
            )
        if hpf_enabled:
            stages.append("remove_hum")
        if lpf_enabled:
            stages.append("reduce_sibilance")

    filter_enhance_duration_ms = timing.sum_since(filter_enhance_started) if timing else None
    if tracker:
        tracker.record(
            UPLOAD_03_FILTER_ENHANCE,
            request=filter_request,
            response={"stages": stages, **{key: value for key, value in result.items() if key != "stages"}},
            duration_ms=filter_enhance_duration_ms,
        )

    if loudness_enabled:
        with timing.step("loudness", mode=loudness_mode) if timing else nullcontext():
            result["loudness"] = loudness.apply_loudness(
                output_wav_path,
                mode=loudness_mode,
                target_lufs=loudness_target_lufs,
                true_peak=loudness_true_peak,
                loudness_range=loudness_lra,
                peak_target_dbfs=loudness_peak_target_dbfs,
            )
        stages.append("loudness")

    if vad_enabled:
        with timing.step("vad", threshold=vad_threshold) if timing else nullcontext():
            result["vad"] = vad.trim_silence(
                output_wav_path,
                threshold=vad_threshold,
                min_speech_duration_ms=vad_min_speech_duration_ms,
                min_silence_duration_ms=vad_min_silence_duration_ms,
                speech_pad_ms=vad_speech_pad_ms,
            )
        stages.append("vad")

    output_pcm_path = output_wav_path.with_suffix(".pcm")
    export_pcm_duration_ms = None
    if export_pcm_enabled:
        with timing.step("export_pcm") if timing else nullcontext():
            normalize.export_pcm(output_wav_path, output_pcm_path)
        export_pcm_duration_ms = timing.last_step_duration_ms() if timing else None

    audio_metadata = normalize.read_audio_metadata(output_wav_path)

    pcm_metadata = None
    if export_pcm_enabled and output_pcm_path.is_file():
        pcm_metadata = {
            "path": output_pcm_path,
            "format": "pcm",
            "size_bytes": output_pcm_path.stat().st_size,
            **audio_metadata,
        }

    result.update(
        {
            "wav": {
                "path": output_wav_path,
                "format": "wav",
                "size_bytes": output_wav_path.stat().st_size,
                **audio_metadata,
            },
        }
    )
    if pcm_metadata:
        result["pcm"] = pcm_metadata

    if tracker:
        tracker.record(
            UPLOAD_04_OUTPUT,
            request={
                "output_wav_path": output_wav_path,
                "output_pcm_path": output_pcm_path if export_pcm_enabled else None,
            },
            response=result,
            duration_ms=export_pcm_duration_ms,
        )

    return result
