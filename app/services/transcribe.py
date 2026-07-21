import os
import threading
from pathlib import Path
from typing import Any

from app.services import enhance_deep

_model = None
_model_key: tuple[str, str, str] | None = None
_batched_pipeline = None
_batched_pipeline_key: tuple[str, str, str] | None = None
# Guards the check-then-create sections below. Not needed while only one
# request ever runs Whisper inference at a time (today's single-threaded dev
# server), but real-time streaming introduces genuine concurrency: two
# threads racing on a cache-miss could otherwise both construct a
# WhisperModel, double-allocating VRAM on an already-tight GPU budget.
_model_lock = threading.Lock()

# faster-whisper defaults (see WhisperModel.transcribe)
DEFAULT_COMPRESSION_RATIO_THRESHOLD = 2.4
DEFAULT_LOG_PROB_THRESHOLD = -1.0
DEFAULT_INFERENCE_MODE = "sequential"
DEFAULT_BATCH_SIZE = 16
VALID_INFERENCE_MODES = frozenset({"sequential", "batched"})


def whisper_model_ids() -> frozenset[str]:
    try:
        from faster_whisper import available_models

        return frozenset(available_models())
    except ImportError:
        return frozenset()


def _normalize_whisper_model_id(model_id: str) -> str:
    return model_id.strip()


def _validate_whisper_model_id(model_id: str) -> None:
    if "/" in model_id:
        return
    known = whisper_model_ids()
    if known and model_id not in known:
        options = ", ".join(sorted(known))
        raise ValueError(f"Unknown whisper model_id={model_id!r}; expected one of: {options}")


def _clear_cuda_memory() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _reset_model() -> None:
    global _model, _model_key, _batched_pipeline, _batched_pipeline_key
    with _model_lock:
        _model = None
        _model_key = None
        _batched_pipeline = None
        _batched_pipeline_key = None


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


def _parse_optional_int(value: Any, default: int | None) -> int | None:
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return int(value)


def _resolve_inference_mode(value: str) -> str:
    mode = str(value).strip().lower() or DEFAULT_INFERENCE_MODE
    if mode not in VALID_INFERENCE_MODES:
        raise ValueError(
            f"Invalid inference_mode={value!r}; expected one of: {', '.join(sorted(VALID_INFERENCE_MODES))}"
        )
    return mode


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

    model_id = _normalize_whisper_model_id(str(_get("MODEL", _get("model", "small"))))
    _validate_whisper_model_id(model_id)
    return model_id


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
    inference_mode = _resolve_inference_mode(
        _get("INFERENCE_MODE", _get("inference_mode", DEFAULT_INFERENCE_MODE))
    )
    batch_size = int(_get("BATCH_SIZE", _get("batch_size", DEFAULT_BATCH_SIZE)))
    chunk_length = _parse_optional_int(
        _get("CHUNK_LENGTH", _get("chunk_length")),
        None,
    )

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
        "inference_mode": inference_mode,
        "batch_size": batch_size,
        "chunk_length": chunk_length,
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
            "faster-whisper is not installed. Install with: pip install -r requirements.txt"
        ) from exc

    resolved_compute_type = _resolve_compute_type(device, compute_type)
    key = (model_id, device, resolved_compute_type)
    with _model_lock:
        if _model is None or _model_key != key:
            if device == "cuda":
                enhance_deep.release_gpu_memory()
                _clear_cuda_memory()
            _model = WhisperModel(model_id, device=device, compute_type=resolved_compute_type)
            _model_key = key

    return _model, resolved_compute_type


def _get_batched_pipeline(model_id: str, device: str, compute_type: str):
    global _batched_pipeline, _batched_pipeline_key

    try:
        from faster_whisper import BatchedInferencePipeline
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Install with: pip install -r requirements.txt"
        ) from exc

    # _get_model() acquires/releases _model_lock itself — call it before our
    # own `with _model_lock:` below so the two acquisitions stay sequential,
    # not nested (Lock() isn't reentrant).
    base_model, resolved_compute_type = _get_model(model_id, device, compute_type)
    key = (model_id, device, resolved_compute_type)
    with _model_lock:
        if _batched_pipeline is None or _batched_pipeline_key != key:
            _batched_pipeline = BatchedInferencePipeline(model=base_model)
            _batched_pipeline_key = key

    return _batched_pipeline, resolved_compute_type


def _build_transcribe_kwargs(
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
) -> dict[str, Any]:
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
    return transcribe_kwargs


def _transcription_from_segments(segments_iter, info, *, word_timestamps: bool) -> dict:
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

    duration_after_vad = getattr(info, "duration_after_vad", None)
    result: dict[str, Any] = {
        "text": " ".join(text_parts),
        "language": info.language,
        "language_probability": round(info.language_probability, 4),
        "duration_ms": int(info.duration * 1000),
        "segments": segments,
    }
    if duration_after_vad is not None:
        result["duration_after_vad_ms"] = int(duration_after_vad * 1000)
    return result


def _transcribe_sequential(model, wav_path: Path, transcribe_kwargs: dict[str, Any]) -> dict:
    word_timestamps = bool(transcribe_kwargs.get("word_timestamps"))
    segments_iter, info = model.transcribe(str(wav_path), **transcribe_kwargs)
    return _transcription_from_segments(segments_iter, info, word_timestamps=word_timestamps)


def _transcribe_batched(
    pipeline,
    wav_path: Path,
    transcribe_kwargs: dict[str, Any],
    *,
    batch_size: int,
    chunk_length: int | None,
) -> dict:
    word_timestamps = bool(transcribe_kwargs.get("word_timestamps"))
    batched_kwargs = dict(transcribe_kwargs)
    batched_kwargs["vad_filter"] = True
    batched_kwargs["batch_size"] = batch_size
    if chunk_length is not None:
        batched_kwargs["chunk_length"] = chunk_length
    segments_iter, info = pipeline.transcribe(str(wav_path), **batched_kwargs)
    return _transcription_from_segments(segments_iter, info, word_timestamps=word_timestamps)


def _run_inference(
    *,
    wav_path: Path,
    model_id: str,
    device: str,
    compute_type: str,
    inference_mode: str,
    batch_size: int,
    chunk_length: int | None,
    transcribe_kwargs: dict[str, Any],
) -> tuple[dict, str]:
    if inference_mode == "batched":
        pipeline, resolved_compute_type = _get_batched_pipeline(model_id, device, compute_type)
        result = _transcribe_batched(
            pipeline,
            wav_path,
            transcribe_kwargs,
            batch_size=batch_size,
            chunk_length=chunk_length,
        )
        return result, resolved_compute_type

    model, resolved_compute_type = _get_model(model_id, device, compute_type)
    result = _transcribe_sequential(model, wav_path, transcribe_kwargs)
    return result, resolved_compute_type


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
    requested_inference_mode: str,
    inference_mode: str,
    batch_size: int,
    chunk_length: int | None,
    force_sequential: bool,
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
        "requested_inference_mode": requested_inference_mode,
        "inference_mode": inference_mode,
        "batch_size": batch_size,
        "chunk_length": chunk_length,
        "force_sequential": force_sequential,
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
    inference_mode: str = DEFAULT_INFERENCE_MODE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    chunk_length: int | None = None,
    force_sequential: bool = False,
) -> dict:
    if model_size is not None:
        model_id = model_size

    model_id = _normalize_whisper_model_id(model_id)
    _validate_whisper_model_id(model_id)

    requested_device = device
    requested_compute_type = compute_type
    requested_inference_mode = _resolve_inference_mode(inference_mode)
    effective_inference_mode = (
        "sequential" if force_sequential else requested_inference_mode
    )
    resolved_device = device
    resolved_compute_type = _resolve_compute_type(device, compute_type)
    fallback_to_cpu = False
    fallback_reason = None

    transcribe_kwargs = _build_transcribe_kwargs(
        language=language,
        beam_size=beam_size,
        initial_prompt=initial_prompt,
        vad_filter=vad_filter,
        compression_ratio_threshold=compression_ratio_threshold,
        log_prob_threshold=log_prob_threshold,
        hallucination_silence_threshold=hallucination_silence_threshold,
        condition_on_previous_text=condition_on_previous_text,
        word_timestamps=word_timestamps,
    )

    try:
        result, resolved_compute_type = _run_inference(
            wav_path=wav_path,
            model_id=model_id,
            device=resolved_device,
            compute_type=resolved_compute_type,
            inference_mode=effective_inference_mode,
            batch_size=batch_size,
            chunk_length=chunk_length,
            transcribe_kwargs=transcribe_kwargs,
        )
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

        result, resolved_compute_type = _run_inference(
            wav_path=wav_path,
            model_id=model_id,
            device=resolved_device,
            compute_type=resolved_compute_type,
            inference_mode=effective_inference_mode,
            batch_size=batch_size,
            chunk_length=chunk_length,
            transcribe_kwargs=transcribe_kwargs,
        )

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
        requested_inference_mode=requested_inference_mode,
        inference_mode=effective_inference_mode,
        batch_size=batch_size,
        chunk_length=chunk_length,
        force_sequential=force_sequential,
    )
    return result
