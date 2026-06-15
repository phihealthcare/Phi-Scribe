from pathlib import Path

from app.services import agc, denoise, enhance_deep, enhance_voice, filters, loudness, normalize, vad

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
) -> dict:
    stages = ["normalize"]

    normalize.normalize_audio(input_path, output_wav_path)

    if hpf_enabled or lpf_enabled:
        filters.apply_band_filters(
            output_wav_path,
            hpf_hz=hpf_cutoff_hz if hpf_enabled else None,
            lpf_hz=lpf_cutoff_hz if lpf_enabled else None,
        )
        if hpf_enabled:
            stages.append("remove_hum")
        if lpf_enabled:
            stages.append("reduce_sibilance")

    result = {"stages": stages}

    if enhance_deep_enabled:
        result["enhance_deep"] = enhance_deep.apply_enhance_deep(
            output_wav_path,
            model=enhance_deep_model,
            device=enhance_deep_device,
            post_filter=enhance_deep_post_filter,
            atten_lim_db=enhance_deep_atten_lim_db,
        )
        stages.append("enhance_deep")
    elif enhance_voice_enabled:
        result["enhance_voice"] = enhance_voice.apply_enhance_voice(output_wav_path)
        stages.append("enhance_voice")
    elif denoise_enabled:
        denoise.apply_stationary(output_wav_path, prop_decrease=prop_decrease)
        stages.append("denoise")

    if agc_enabled:
        agc.apply_agc(
            output_wav_path,
            target_dbfs=agc_target_dbfs,
            max_gain_db=agc_max_gain_db,
            window_ms=agc_window_ms,
        )
        stages.append("agc")

    if loudness_enabled:
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
        result["vad"] = vad.trim_silence(
            output_wav_path,
            threshold=vad_threshold,
            min_speech_duration_ms=vad_min_speech_duration_ms,
            min_silence_duration_ms=vad_min_silence_duration_ms,
            speech_pad_ms=vad_speech_pad_ms,
        )
        stages.append("vad")

    output_pcm_path = output_wav_path.with_suffix(".pcm")
    normalize.export_pcm(output_wav_path, output_pcm_path)

    audio_metadata = normalize.read_audio_metadata(output_wav_path)

    result.update(
        {
            "wav": {
                "path": output_wav_path,
                "format": "wav",
                "size_bytes": output_wav_path.stat().st_size,
                **audio_metadata,
            },
            "pcm": {
                "path": output_pcm_path,
                "format": "pcm",
                "size_bytes": output_pcm_path.stat().st_size,
                **audio_metadata,
            },
        }
    )

    return result
