from pathlib import Path

from app.services import denoise, normalize, vad

def preprocess_audio(
    input_path: Path,
    output_wav_path: Path,
    *,
    denoise_enabled: bool = False,
    prop_decrease: float = 0.6,
    vad_enabled: bool = False,
    vad_threshold: float = 0.5,
    vad_min_speech_duration_ms: int = 250,
    vad_min_silence_duration_ms: int = 1000,
    vad_speech_pad_ms: int = 300,
) -> dict:
    stages = ["normalize"]

    normalize.normalize_audio(input_path, output_wav_path)

    if denoise_enabled:
        denoise.apply_stationary(output_wav_path, prop_decrease=prop_decrease)
        stages.append("denoise")

    result = {"stages": stages}

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
