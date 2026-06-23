import os
from pathlib import Path
from typing import Any

from app.services import enhance_deep

_model = None
_model_key: tuple[str, str, str] | None = None

# faster-whisper defaults (see WhisperModel.transcribe)
DEFAULT_COMPRESSION_RATIO_THRESHOLD = 2.4
DEFAULT_LOG_PROB_THRESHOLD = -1.0


def _clear_cuda_memory() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _reset_model() -> None:
    global _model, _model_key
    _model = None
    _model_key = None


def _is_cuda_oom(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "out of memory" in message or "cuda failed" in message


def _resolve_compute_type(device: str, compute_type: str) -> str:
    if device == "cpu":
        return "int8"
    return compute_type


def _parse_optional_float(value: Any, default: float | None) -> float | None:
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return float(value)


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"true", "1", "yes"}


def _mapping_has_key(mapping: dict[str, Any], *keys: str) -> bool:
    return any(key in mapping for key in keys)


def _env_was_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _is_explicit_whisper_setting(mapping: dict[str, Any], env_name: str, *mapping_keys: str) -> bool:
    if _env_was_set(env_name):
        return True
    return _mapping_has_key(mapping, *mapping_keys)


def _resolve_model_id(mapping: dict[str, Any]) -> str:
    prefix = "WHISPER_FASTER_"

    def _get(name: str, default: Any = None) -> Any:
        if name in mapping:
            return mapping[name]
        env_name = f"{prefix}{name}"
        if env_name in mapping:
            return mapping[env_name]
        return default

    return str(_get("MODEL", _get("model", "small")))


def transcribe_options_from_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Build transcribe_wav keyword args from Flask config or stacks.yaml whisper block."""
    prefix = "WHISPER_FASTER_"

    def _get(name: str, default: Any = None) -> Any:
        if name in mapping:
            return mapping[name]
        env_name = f"{prefix}{name}"
        if env_name in mapping:
            return mapping[env_name]
        return default

    if not _is_explicit_whisper_setting(
        mapping, "WHISPER_FASTER_BEAM_SIZE", "BEAM_SIZE", "beam_size"
    ):
        beam_size = int(_get("BEAM_SIZE", _get("beam_size", 5)))
    else:
        beam_size = int(_get("BEAM_SIZE", _get("beam_size", 5)))

    if not _is_explicit_whisper_setting(
        mapping, "WHISPER_FASTER_COMPUTE_TYPE", "COMPUTE_TYPE", "compute_type"
    ):
        compute_type = _get("COMPUTE_TYPE", _get("compute_type", "int8"))
    else:
        compute_type = _get("COMPUTE_TYPE", _get("compute_type", "int8"))

    compression_ratio_threshold = _parse_optional_float(
        _get("COMPRESSION_RATIO_THRESHOLD", _get("compression_ratio_threshold")),
        DEFAULT_COMPRESSION_RATIO_THRESHOLD,
    )
    log_prob_threshold = _parse_optional_float(
        _get("LOG_PROB_THRESHOLD", _get("log_prob_threshold")),
        DEFAULT_LOG_PROB_THRESHOLD,
    )
    hallucination_silence_threshold = _parse_optional_float(
        _get("HALLUCINATION_SILENCE_THRESHOLD", _get("hallucination_silence_threshold")),
        None,
    )
    condition_on_previous_text = _parse_bool(
        _get("CONDITION_ON_PREVIOUS_TEXT", _get("condition_on_previous_text")),
        True,
    )
    initial_prompt = _get("INITIAL_PROMPT", _get("initial_prompt")) or None

    return {
        "model_id": _resolve_model_id(mapping),
        "device": _get("DEVICE", _get("device", "cpu")),
        "compute_type": compute_type,
        "language": _get("LANGUAGE", _get("language", "pt")),
        "beam_size": beam_size,
        "initial_prompt": initial_prompt,
        "vad_filter": _parse_bool(_get("VAD_FILTER", _get("vad_filter")), False),
        "word_timestamps": _parse_bool(_get("WORD_TIMESTAMPS", _get("word_timestamps")), False),
        "compression_ratio_threshold": compression_ratio_threshold,
        "log_prob_threshold": log_prob_threshold,
        "hallucination_silence_threshold": hallucination_silence_threshold,
        "condition_on_previous_text": condition_on_previous_text,
    }


def _segment_words(segment) -> list[dict[str, int | str]] | None:
    words = getattr(segment, "words", None)
    if not words:
        return None
    entries: list[dict[str, int | str]] = []
    for word in words:
        display_word = word.word.strip()
        if not display_word:
            continue
        entries.append(
            {
                "word": display_word,
                "start_ms": int(word.start * 1000),
                "end_ms": int(word.end * 1000),
            }
        )
    return entries or None


def _get_model(model_id: str, device: str, compute_type: str):
    global _model, _model_key

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. "
            "Install with: pip install -r requirements-experimental.txt"
        ) from exc

    resolved_compute_type = _resolve_compute_type(device, compute_type)
    key = (model_id, device, resolved_compute_type)
    if _model is None or _model_key != key:
        if device == "cuda":
            enhance_deep.release_gpu_memory()
            _clear_cuda_memory()
        _model = WhisperModel(model_id, device=device, compute_type=resolved_compute_type)
        _model_key = key

    return _model, resolved_compute_type


def _transcribe_with_model(
    model,
    wav_path: Path,
    *,
    language: str,
    beam_size: int,
    initial_prompt: str | None,
    vad_filter: bool,
    compression_ratio_threshold: float | None,
    log_prob_threshold: float | None,
    hallucination_silence_threshold: float | None,
    condition_on_previous_text: bool,
    word_timestamps: bool,
) -> dict:
    transcribe_kwargs: dict[str, Any] = {
        "language": language,
        "beam_size": beam_size,
        "initial_prompt": initial_prompt,
        "vad_filter": vad_filter,
        "compression_ratio_threshold": compression_ratio_threshold,
        "log_prob_threshold": log_prob_threshold,
        "hallucination_silence_threshold": hallucination_silence_threshold,
        "condition_on_previous_text": condition_on_previous_text,
    }
    if word_timestamps:
        transcribe_kwargs["word_timestamps"] = True

    segments_iter, info = model.transcribe(str(wav_path), **transcribe_kwargs)

    segments = []
    text_parts = []

    for segment in segments_iter:
        text = segment.text.strip()
        segment_entry: dict[str, Any] = {
            "start_ms": int(segment.start * 1000),
            "end_ms": int(segment.end * 1000),
            "text": text,
        }
        if word_timestamps:
            if segment_words := _segment_words(segment):
                segment_entry["words"] = segment_words
        segments.append(segment_entry)
        if text:
            text_parts.append(text)

    return {
        "text": " ".join(text_parts),
        "language": info.language,
        "language_probability": round(info.language_probability, 4),
        "duration_ms": int(info.duration * 1000),
        "segments": segments,
    }


def _build_run_metadata(
    *,
    model_id: str,
    requested_device: str,
    resolved_device: str,
    requested_compute_type: str,
    resolved_compute_type: str,
    fallback_to_cpu: bool,
    fallback_reason: str | None,
    beam_size: int,
    vad_filter: bool,
    word_timestamps: bool,
    compression_ratio_threshold: float | None,
    log_prob_threshold: float | None,
    hallucination_silence_threshold: float | None,
    condition_on_previous_text: bool,
) -> dict:
    return {
        "model_id": model_id,
        "model_size": model_id,
        "requested_device": requested_device,
        "device": resolved_device,
        "requested_compute_type": requested_compute_type,
        "compute_type": resolved_compute_type,
        "fallback_to_cpu": fallback_to_cpu,
        "fallback_reason": fallback_reason,
        "beam_size": beam_size,
        "vad_filter": vad_filter,
        "word_timestamps": word_timestamps,
        "compression_ratio_threshold": compression_ratio_threshold,
        "log_prob_threshold": log_prob_threshold,
        "hallucination_silence_threshold": hallucination_silence_threshold,
        "condition_on_previous_text": condition_on_previous_text,
    }


def transcribe_wav(
    wav_path: Path,
    *,
    model_id: str = "small",
    model_size: str | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
    language: str = "pt",
    beam_size: int = 5,
    initial_prompt: str | None = None,
    vad_filter: bool = False,
    word_timestamps: bool = False,
    compression_ratio_threshold: float | None = DEFAULT_COMPRESSION_RATIO_THRESHOLD,
    log_prob_threshold: float | None = DEFAULT_LOG_PROB_THRESHOLD,
    hallucination_silence_threshold: float | None = None,
    condition_on_previous_text: bool = True,
) -> dict:
    if model_size is not None:
        model_id = model_size

    requested_device = device
    requested_compute_type = compute_type
    resolved_device = device
    resolved_compute_type = _resolve_compute_type(device, compute_type)
    fallback_to_cpu = False
    fallback_reason = None

    transcribe_kwargs = {
        "language": language,
        "beam_size": beam_size,
        "initial_prompt": initial_prompt,
        "vad_filter": vad_filter,
        "compression_ratio_threshold": compression_ratio_threshold,
        "log_prob_threshold": log_prob_threshold,
        "hallucination_silence_threshold": hallucination_silence_threshold,
        "condition_on_previous_text": condition_on_previous_text,
        "word_timestamps": word_timestamps,
    }

    try:
        model, resolved_compute_type = _get_model(model_id, resolved_device, resolved_compute_type)
        result = _transcribe_with_model(model, wav_path, **transcribe_kwargs)
    except Exception as exc:
        if requested_device != "cuda" or not _is_cuda_oom(exc):
            raise

        _reset_model()
        enhance_deep.release_gpu_memory()
        _clear_cuda_memory()

        resolved_device = "cpu"
        resolved_compute_type = "int8"
        fallback_to_cpu = True
        fallback_reason = "cuda_oom"

        model, resolved_compute_type = _get_model(model_id, resolved_device, resolved_compute_type)
        result = _transcribe_with_model(model, wav_path, **transcribe_kwargs)

    result["run"] = _build_run_metadata(
        model_id=model_id,
        requested_device=requested_device,
        resolved_device=resolved_device,
        requested_compute_type=requested_compute_type,
        resolved_compute_type=resolved_compute_type,
        fallback_to_cpu=fallback_to_cpu,
        fallback_reason=fallback_reason,
        beam_size=beam_size,
        vad_filter=vad_filter,
        word_timestamps=word_timestamps,
        compression_ratio_threshold=compression_ratio_threshold,
        log_prob_threshold=log_prob_threshold,
        hallucination_silence_threshold=hallucination_silence_threshold,
        condition_on_previous_text=condition_on_previous_text,
    )
    return result
