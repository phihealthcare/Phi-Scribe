import json
import logging
import tempfile
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from app.services import transcribe
from app.services.audio_processor import preprocess_audio
from app.services.normalize import concat_wavs, normalize_audio
from app.services.pipeline_steps import (
    TRANSCRIBE_01_DIARIZATION,
    TRANSCRIBE_02_WHISPER,
    TRANSCRIBE_03_FORMAT_SPEAKERS,
    TRANSCRIBE_04_LLM_ASR_FIX,
    TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
    TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION,
    UPLOAD_01_INPUT,
    soap_enabled_for_config,
    soap_split_enabled_for_config,
)
from app.services.pipeline_tracker import tracker_from_config
from app.services.transcribe_diarized import (
    diarization_options_from_mapping,
    transcribe_wav_diarized,
)
from app.services.soap_draft import (
    generate_soap_draft_from_config,
    resolve_soap_input_transcript,
    skip_soap_pipeline_steps,
)
from app.services.soap_prerequisites import can_generate_soap, soap_draft_skipped_result
from app.services.transcript_postprocess import (
    diarization_labels_applied,
    edit_transcript_from_config,
    manual_diarization_applied,
    save_postprocess_diff_file,
)
from app.services.upload_timing import (
    UploadStepTimer,
    pipeline_upload_timing_path,
    upload_timing_path,
)

audio_bp = Blueprint("audio", __name__, url_prefix="/api/v1/audio")

ALLOWED_EXTENSIONS = {"mp3", "wav", "mp4", "webm", "m4a", "ogg"}
EXTENSIONS_REQUIRING_EXTRACT = frozenset({"mp4"})


def _allowed_extensions_label() -> str:
    return ", ".join(sorted(ALLOWED_EXTENSIONS))


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _prepare_transcription_audio(audio_path: Path) -> tuple[Path, Path | None]:
    """Extract mono 16 kHz WAV from container formats (e.g. MP4) before transcribe."""
    if audio_path.suffix.lower() not in EXTENSIONS_REQUIRING_EXTRACT:
        return audio_path, None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    normalize_audio(audio_path, wav_path)
    return wav_path, wav_path


def _whisper_disabled_response():
    return (
        jsonify(
            {
                "error": "Experimental faster-whisper transcription is disabled. "
                "Set WHISPER_FASTER_ENABLED=true in .env to enable local stack testing."
            }
        ),
        503,
    )


def _resolve_public_audio(stem: str) -> Path:
    safe_stem = secure_filename(stem)
    if not safe_stem or safe_stem != stem:
        raise ValueError(f"Invalid audio name: {stem}")

    public_folder = Path(current_app.config["PUBLIC_FOLDER"])
    for extension in sorted(ALLOWED_EXTENSIONS):
        candidate = public_folder / f"{safe_stem}.{extension}"
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(safe_stem)


def _attach_pipeline_log(response: dict, tracker) -> None:
    if tracker is None:
        return
    response["pipeline_log"] = {
        "enabled": True,
        "run_id": tracker.run_id,
        "log_dir": str(tracker.log_dir),
        "manifest": str(tracker.manifest_path()),
        "llm_requests": str(tracker.llm_requests_path()),
        "upload_timing": str(pipeline_upload_timing_path(tracker.log_dir)),
    }


def _attach_upload_timing(response: dict, timing: UploadStepTimer | None, timing_file: Path | None) -> None:
    if timing is None:
        return
    payload = timing.to_dict()
    response["upload_timing"] = payload
    if timing_file is not None:
        response["upload_timing"]["file"] = str(timing_file)
    logging.getLogger(__name__).info(
        "[upload-timing] file_id=%s upload complete elapsed_s=%.2f",
        timing.file_id,
        payload["total_elapsed_s"],
    )


def _run_transcription(audio_path: Path, *, file_id: str, preprocessing: str) -> tuple[dict, int]:
    config = current_app.config
    tracker = tracker_from_config(config, run_id=file_id)
    transcribe_kwargs = transcribe.transcribe_options_from_mapping(config)
    diarization_opts = diarization_options_from_mapping(config)
    diarization_enabled = bool(diarization_opts.get("enabled"))

    transcribe_path, temp_wav_path = _prepare_transcription_audio(audio_path)
    try:
        if diarization_enabled:
            transcription = transcribe_wav_diarized(
                transcribe_path,
                transcribe_options=transcribe_kwargs,
                diarization_options=diarization_opts,
                tracker=tracker,
            )
        else:
            if tracker:
                tracker.skip(
                    TRANSCRIBE_01_DIARIZATION,
                    reason="diarization_disabled",
                    request={"enabled": False},
                )
            t0 = time.perf_counter()
            transcription = transcribe.transcribe_wav(transcribe_path, **transcribe_kwargs)
            if tracker:
                tracker.record(
                    TRANSCRIBE_02_WHISPER,
                    request={"wav_path": transcribe_path, **transcribe_kwargs},
                    response={
                        "text": transcription.get("text"),
                        "duration_ms": transcription.get("duration_ms"),
                        "run": transcription.get("run"),
                    },
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )
                tracker.skip(
                    TRANSCRIBE_03_FORMAT_SPEAKERS,
                    reason="diarization_disabled",
                )
    except RuntimeError as exc:
        return {"error": str(exc)}, 503
    except Exception as exc:
        return {"error": f"Transcription failed: {exc}"}, 500
    finally:
        if temp_wav_path is not None:
            temp_wav_path.unlink(missing_ok=True)

    raw_text = str(transcription.get("text", ""))
    postprocess_enabled = bool(config.get("TRANSCRIPT_POSTPROCESS_ENABLED"))
    soap_enabled = bool(postprocess_enabled and soap_enabled_for_config(config))

    response: dict = {
        "file_id": file_id,
        "source_audio": str(audio_path),
        "preprocessing": preprocessing,
        "transcription": transcription,
        "source": "faster-whisper",
        "experimental": True,
        "diarization_enabled": diarization_enabled,
    }
    _attach_pipeline_log(response, tracker)

    postprocess_applied = False
    if postprocess_enabled:
        transcription["raw_text"] = raw_text
        postprocess_result = edit_transcript_from_config(
            raw_text,
            config,
            diarization_enabled=diarization_enabled,
            tracker=tracker,
        )
        response["postprocess"] = {
            "enabled": True,
            "provider": postprocess_result["provider"],
            "model": postprocess_result["model"],
            "skipped": postprocess_result["skipped"],
            "error": postprocess_result["error"],
        }
        if asr_fix := postprocess_result.get("asr_fix"):
            response["postprocess"]["asr_fix"] = {
                "skipped": asr_fix.get("skipped"),
                "error": asr_fix.get("error"),
                "diff": asr_fix.get("diff"),
            }
        if diarization_labels := postprocess_result.get("diarization_labels"):
            response["postprocess"]["diarization_labels"] = {
                "skipped": diarization_labels.get("skipped"),
                "error": diarization_labels.get("error"),
                "diff": diarization_labels.get("diff"),
            }
        if manual_diarization := postprocess_result.get("manual_diarization"):
            response["postprocess"]["manual_diarization"] = {
                "skipped": manual_diarization.get("skipped"),
                "error": manual_diarization.get("error"),
                "diff": manual_diarization.get("diff"),
                "guardrail": manual_diarization.get("guardrail"),
            }
        if diff := postprocess_result.get("diff"):
            response["postprocess"]["diff"] = diff
            if tracker and not postprocess_result["skipped"]:
                asr_fix = postprocess_result.get("asr_fix") or {}
                diarization_labels = postprocess_result.get("diarization_labels") or {}
                manual_diarization = postprocess_result.get("manual_diarization") or {}
                if not asr_fix.get("skipped") and asr_fix.get("diff"):
                    tracker.amend(
                        TRANSCRIBE_04_LLM_ASR_FIX,
                        response={"diff": asr_fix["diff"]},
                    )
                if not diarization_labels.get("skipped") and diarization_labels.get("diff"):
                    tracker.amend(
                        TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
                        response={"diff": diarization_labels["diff"]},
                    )
                if not manual_diarization.get("skipped") and manual_diarization.get("diff"):
                    tracker.amend(
                        TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION,
                        response={"diff": manual_diarization["diff"]},
                    )
        if not postprocess_result["skipped"]:
            transcription["text"] = postprocess_result["text"]
            postprocess_applied = diarization_labels_applied(
                postprocess_result
            ) or manual_diarization_applied(postprocess_result)

        if soap_enabled:
            # SOAP's prompts branch on whether the transcript text actually has
            # Médico:/Doutor:/Paciente: line labels — that's `postprocess_applied`
            # (true when either the pyannote relabel step or manual diarization
            # actually succeeded), not the raw DIARIZATION_ENABLED flag. Using the
            # raw flag here caused a mismatch when manual diarization succeeded
            # (labels present) while DIARIZATION_ENABLED stayed false: the SOAP
            # prompt told the model "no speaker labels" while the text had them,
            # and the model ignored the schema entirely.
            soap_diarization_enabled = postprocess_applied
            soap_ok, soap_skip_reason = can_generate_soap(
                postprocess_result,
                diarization_enabled=soap_diarization_enabled,
            )
            if soap_ok:
                soap_result = generate_soap_draft_from_config(
                    str(transcription.get("text", "")),
                    config,
                    segments=transcription.get("segments")
                    if isinstance(transcription.get("segments"), list)
                    else None,
                    diarization_enabled=soap_diarization_enabled,
                    postprocess_applied=postprocess_applied,
                    tracker=tracker,
                )
            else:
                if tracker:
                    split_enabled = soap_split_enabled_for_config(config)
                    skip_soap_pipeline_steps(
                        tracker,
                        reason=soap_skip_reason,
                        split_enabled=split_enabled,
                    )
                soap_result = soap_draft_skipped_result(
                    config=config,
                    segmented_transcript=resolve_soap_input_transcript(
                        str(transcription.get("text", "")),
                        segments=transcription.get("segments")
                        if isinstance(transcription.get("segments"), list)
                        else None,
                        diarization_enabled=soap_diarization_enabled,
                        postprocess_applied=postprocess_applied,
                    ),
                    diarization_enabled=soap_diarization_enabled,
                    postprocess_applied=postprocess_applied,
                    error=soap_skip_reason,
                )
        else:
            if tracker:
                split_enabled = soap_split_enabled_for_config(config)
                skip_soap_pipeline_steps(
                    tracker,
                    reason="soap_disabled",
                    split_enabled=split_enabled,
                )
            soap_result = soap_draft_skipped_result(
                config=config,
                segmented_transcript=resolve_soap_input_transcript(
                    str(transcription.get("text", "")),
                    segments=transcription.get("segments")
                    if isinstance(transcription.get("segments"), list)
                    else None,
                    diarization_enabled=diarization_enabled,
                    postprocess_applied=postprocess_applied,
                ),
                diarization_enabled=diarization_enabled,
                postprocess_applied=postprocess_applied,
                error="soap_disabled",
            )
        response["soap_draft"] = {
            "enabled": soap_enabled,
            "provider": soap_result["provider"],
            "model": soap_result["model"],
            "prompt_path": soap_result["prompt_path"],
            "skipped": soap_result["skipped"],
            "error": soap_result["error"],
            "diarization_enabled": soap_result["diarization_enabled"],
            "postprocess_applied": soap_result["postprocess_applied"],
        }
        if soap_result.get("validation_errors"):
            response["soap_draft"]["validation_errors"] = soap_result["validation_errors"]
        if soap_result.get("raw"):
            response["soap_draft"]["raw"] = soap_result["raw"]
        if soap_result.get("document") and not soap_result.get("skipped"):
            response["soap_draft"]["document"] = soap_result["document"]
        if soap_result.get("plain_text"):
            response["soap_draft"]["plain_text"] = soap_result["plain_text"]
        if soap_result.get("sections"):
            response["soap_draft"]["sections"] = soap_result["sections"]
        if soap_result.get("prompt_paths"):
            response["soap_draft"]["prompt_paths"] = soap_result["prompt_paths"]
    else:
        if tracker:
            tracker.skip(TRANSCRIBE_04_LLM_ASR_FIX, reason="postprocess_disabled")
            tracker.skip(TRANSCRIBE_04B_LLM_DIARIZATION_LABELS, reason="postprocess_disabled")
            split_enabled = soap_split_enabled_for_config(config)
            skip_soap_pipeline_steps(
                tracker,
                reason="postprocess_disabled",
                split_enabled=split_enabled,
            )

    if isinstance(transcription.get("run"), dict):
        response["whisper"] = transcription["run"]

    return response, 200


def _save_transcript(response: dict, *, label: str) -> None:
    processed_folder = Path(current_app.config["PROCESSED_FOLDER"])
    processed_folder.mkdir(parents=True, exist_ok=True)
    transcript_path = processed_folder / f"{label}.json"
    transcript_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

    postprocess = response.get("postprocess", {})
    transcription = response.get("transcription", {})
    if (
        postprocess
        and not postprocess.get("skipped")
        and isinstance(transcription, dict)
        and transcription.get("raw_text")
        and transcription.get("text")
    ):
        save_postprocess_diff_file(
            processed_folder / f"{label}.postprocess.diff.txt",
            raw_text=str(transcription["raw_text"]),
            corrected_text=str(transcription["text"]),
            diff=postprocess.get("diff"),
            meta={
                "file_id": response.get("file_id", label),
                "provider": postprocess.get("provider"),
                "model": postprocess.get("model"),
            },
            label=label,
        )


def _process_uploaded_audio(
    filepath: Path,
    *,
    file_id: str,
    original_filename: str,
    stored_filename: str,
    content_type: str | None,
    upload_timer: UploadStepTimer | None,
    tracker,
) -> tuple[dict, int]:
    """Shared tail of /upload: run preprocess_audio on an already-saved audio
    file at `filepath` and build the response dict. Used by both the normal
    single-file upload and the multi-segment (recording continuation) upload —
    the latter passes an already-normalized, already-concatenated WAV, which
    preprocess_audio just re-normalizes (a harmless no-op re-encode, since it's
    already 16k/mono/s16) before running the usual filter/VAD chain."""
    processed_folder = Path(current_app.config["PROCESSED_FOLDER"])
    processed_wav_filename = f"{file_id}.wav"
    processed_pcm_filename = f"{file_id}.pcm"
    processed_wav_path = processed_folder / processed_wav_filename

    try:
        processed = preprocess_audio(
            filepath,
            processed_wav_path,
            hpf_enabled=current_app.config["HPF_ENABLED"],
            hpf_cutoff_hz=current_app.config["HPF_CUTOFF_HZ"],
            lpf_enabled=current_app.config["LPF_ENABLED"],
            lpf_cutoff_hz=current_app.config["LPF_CUTOFF_HZ"],
            denoise_enabled=current_app.config["DENOISE_ENABLED"],
            prop_decrease=current_app.config["DENOISE_PROP_DECREASE"],
            enhance_voice_enabled=current_app.config["ENHANCE_VOICE_ENABLED"],
            enhance_deep_enabled=current_app.config["ENHANCE_DEEP_ENABLED"],
            enhance_deep_model=current_app.config["ENHANCE_DEEP_MODEL"],
            enhance_deep_device=current_app.config["ENHANCE_DEEP_DEVICE"],
            enhance_deep_post_filter=current_app.config["ENHANCE_DEEP_POST_FILTER"],
            enhance_deep_atten_lim_db=current_app.config["ENHANCE_DEEP_ATTEN_LIM_DB"],
            agc_enabled=current_app.config["AGC_ENABLED"],
            agc_target_dbfs=current_app.config["AGC_TARGET_DBFS"],
            agc_max_gain_db=current_app.config["AGC_MAX_GAIN_DB"],
            agc_window_ms=current_app.config["AGC_WINDOW_MS"],
            loudness_enabled=current_app.config["LOUDNESS_ENABLED"],
            loudness_mode=current_app.config["LOUDNESS_MODE"],
            loudness_target_lufs=current_app.config["LOUDNESS_TARGET_LUFS"],
            loudness_true_peak=current_app.config["LOUDNESS_TRUE_PEAK"],
            loudness_lra=current_app.config["LOUDNESS_LRA"],
            loudness_peak_target_dbfs=current_app.config["LOUDNESS_PEAK_TARGET_DBFS"],
            vad_enabled=current_app.config["VAD_ENABLED"],
            vad_threshold=current_app.config["VAD_THRESHOLD"],
            vad_min_speech_duration_ms=current_app.config["VAD_MIN_SPEECH_DURATION_MS"],
            vad_min_silence_duration_ms=current_app.config["VAD_MIN_SILENCE_DURATION_MS"],
            vad_speech_pad_ms=current_app.config["VAD_SPEECH_PAD_MS"],
            export_pcm_enabled=current_app.config["EXPORT_PCM_ENABLED"],
            tracker=tracker,
            timing=upload_timer,
        )
    except Exception as exc:
        filepath.unlink(missing_ok=True)
        return {"error": f"Failed to process audio: {exc}"}, 500

    timing_file: Path | None = None
    if upload_timer is not None:
        upload_timer.log_summary()
        if tracker is not None:
            timing_file = upload_timer.write_json(pipeline_upload_timing_path(tracker.log_dir))
        else:
            processed_folder.mkdir(parents=True, exist_ok=True)
            timing_file = upload_timer.write_json(upload_timing_path(processed_folder, file_id))

    response = {
        "message": "File uploaded and processed successfully",
        "file_id": file_id,
        "filename": original_filename,
        "stored_as": stored_filename,
        "size_bytes": filepath.stat().st_size,
        "content_type": content_type,
        "stages": processed["stages"],
        "processed": {
            "wav": {
                "stored_as": processed_wav_filename,
                "format": processed["wav"]["format"],
                "sample_rate": processed["wav"]["sample_rate"],
                "channels": processed["wav"]["channels"],
                "sample_width_bits": processed["wav"]["sample_width_bits"],
                "duration_ms": processed["wav"]["duration_ms"],
                "size_bytes": processed["wav"]["size_bytes"],
            },
        },
    }

    if "pcm" in processed:
        response["processed"]["pcm"] = {
            "stored_as": processed_pcm_filename,
            "format": processed["pcm"]["format"],
            "sample_rate": processed["pcm"]["sample_rate"],
            "channels": processed["pcm"]["channels"],
            "sample_width_bits": processed["pcm"]["sample_width_bits"],
            "duration_ms": processed["pcm"]["duration_ms"],
            "size_bytes": processed["pcm"]["size_bytes"],
        }

    if "vad" in processed:
        response["vad"] = processed["vad"]

    if "loudness" in processed:
        response["loudness"] = processed["loudness"]

    if "enhance_voice" in processed:
        response["enhance_voice"] = processed["enhance_voice"]

    if "enhance_deep" in processed:
        response["enhance_deep"] = processed["enhance_deep"]

    _attach_pipeline_log(response, tracker)
    _attach_upload_timing(response, upload_timer, timing_file)

    return response, 201


def _upload_segments(segment_files: list) -> tuple:
    """RE-02/RNF-06: merge an interrupted-then-resumed recording (2+ audio
    segments recovered from IndexedDB + the continuation) into one recording
    before running the normal pipeline. Each segment is normalized on its own
    first (same canonical 16k/mono/s16 format regardless of input container),
    so concat_wavs can losslessly append raw PCM frames — no re-encoding, and
    no risk of the two segments having mismatched codec parameters."""
    for segment in segment_files:
        if not segment.filename or not _allowed_file(segment.filename):
            return (
                jsonify({"error": f"Invalid segment file type. Allowed types: {_allowed_extensions_label()}"}),
                400,
            )

    file_id = str(uuid.uuid4())
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)

    timing_enabled = bool(current_app.config.get("UPLOAD_STEP_TIMING_ENABLED", True))
    upload_timer = UploadStepTimer(file_id=file_id) if timing_enabled else None
    tracker = tracker_from_config(current_app.config, run_id=file_id)

    raw_paths: list[Path] = []
    normalized_paths: list[Path] = []
    combined_path = upload_folder / f"{file_id}.wav"
    try:
        with upload_timer.step("save_file") if upload_timer else nullcontext():
            for index, segment in enumerate(segment_files, start=1):
                extension = secure_filename(segment.filename).rsplit(".", 1)[1].lower()
                raw_path = upload_folder / f"{file_id}.part{index}.{extension}"
                segment.save(raw_path)
                raw_paths.append(raw_path)

        for index, raw_path in enumerate(raw_paths, start=1):
            normalized_path = upload_folder / f"{file_id}.part{index}.norm.wav"
            normalize_audio(raw_path, normalized_path)
            normalized_paths.append(normalized_path)

        concat_wavs(normalized_paths, combined_path)
    except Exception as exc:
        for path in [*raw_paths, *normalized_paths, combined_path]:
            path.unlink(missing_ok=True)
        return jsonify({"error": f"Failed to merge recording segments: {exc}"}), 500
    finally:
        for path in normalized_paths:
            path.unlink(missing_ok=True)

    save_duration_ms = upload_timer.last_step_duration_ms() if upload_timer else None
    if tracker:
        tracker.record(
            UPLOAD_01_INPUT,
            request={
                "segment_count": len(segment_files),
                "content_types": [segment.content_type for segment in segment_files],
            },
            response={
                "file_id": file_id,
                "stored_as": f"{file_id}.wav",
                "size_bytes": combined_path.stat().st_size,
                "stored_path": str(combined_path),
            },
            duration_ms=save_duration_ms,
        )

    response, status = _process_uploaded_audio(
        combined_path,
        file_id=file_id,
        original_filename=f"{len(segment_files)} segments (merged)",
        stored_filename=f"{file_id}.wav",
        content_type="audio/wav",
        upload_timer=upload_timer,
        tracker=tracker,
    )
    if status == 201:
        response["segments_merged"] = len(segment_files)
    return jsonify(response), status


@audio_bp.post("/upload")
def upload_audio():
    segment_files = [segment for segment in request.files.getlist("segments") if segment and segment.filename]
    if len(segment_files) >= 2:
        return _upload_segments(segment_files)

    if "file" not in request.files:
        return jsonify({"error": "No file part in the request. Use field name 'file'."}), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"error": f"Invalid file type. Allowed types: {_allowed_extensions_label()}"}), 400

    original_filename = secure_filename(file.filename)
    file_id = str(uuid.uuid4())
    extension = original_filename.rsplit(".", 1)[1].lower()
    stored_filename = f"{file_id}.{extension}"

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)

    filepath = upload_folder / stored_filename
    timing_enabled = bool(current_app.config.get("UPLOAD_STEP_TIMING_ENABLED", True))
    upload_timer = UploadStepTimer(file_id=file_id) if timing_enabled else None

    with upload_timer.step("save_file") if upload_timer else nullcontext():
        file.save(filepath)

    save_duration_ms = upload_timer.last_step_duration_ms() if upload_timer else None

    tracker = tracker_from_config(current_app.config, run_id=file_id)
    if tracker:
        tracker.record(
            UPLOAD_01_INPUT,
            request={
                "original_filename": original_filename,
                "extension": extension,
                "content_type": file.content_type,
            },
            response={
                "file_id": file_id,
                "stored_as": stored_filename,
                "size_bytes": filepath.stat().st_size,
                "stored_path": str(filepath),
            },
            duration_ms=save_duration_ms,
        )

    response, status = _process_uploaded_audio(
        filepath,
        file_id=file_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        content_type=file.content_type,
        upload_timer=upload_timer,
        tracker=tracker,
    )
    return jsonify(response), status


@audio_bp.post("/public/<stem>/transcribe")
def transcribe_public_audio(stem: str):
    """Transcribe a file from PUBLIC_FOLDER (e.g. public/anamnesia-1.mp3) with no preprocessing."""
    if not current_app.config["WHISPER_FASTER_ENABLED"]:
        return _whisper_disabled_response()

    try:
        audio_path = _resolve_public_audio(stem)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except FileNotFoundError:
        public_folder = current_app.config["PUBLIC_FOLDER"]
        return (
            jsonify(
                {
                    "error": (
                        f"Audio not found in {public_folder}: {stem} "
                        f"({_allowed_extensions_label()})"
                    ),
                }
            ),
            404,
        )

    response, status = _run_transcription(
        audio_path,
        file_id=stem,
        preprocessing="none",
    )
    if status == 200:
        _save_transcript(response, label=f"raw-{stem}")
    return jsonify(response), status


@audio_bp.post("/transcribe/raw")
def transcribe_raw_upload():
    """Transcribe an uploaded MP3/WAV/MP4 directly with no preprocessing."""
    if not current_app.config["WHISPER_FASTER_ENABLED"]:
        return _whisper_disabled_response()

    if "file" not in request.files:
        return jsonify({"error": "No file part in the request. Use field name 'file'."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"error": f"Invalid file type. Allowed types: {_allowed_extensions_label()}"}), 400

    original_filename = secure_filename(file.filename)
    suffix = Path(original_filename).suffix

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = Path(tmp.name)

    try:
        response, status = _run_transcription(
            tmp_path,
            file_id=Path(original_filename).stem,
            preprocessing="none",
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    if status == 200:
        _save_transcript(response, label=f"raw-{Path(original_filename).stem}")
    return jsonify(response), status


@audio_bp.post("/<file_id>/transcribe")
def transcribe_audio(file_id: str):
    if not current_app.config["WHISPER_FASTER_ENABLED"]:
        return _whisper_disabled_response()

    processed_folder = Path(current_app.config["PROCESSED_FOLDER"])
    wav_path = processed_folder / f"{file_id}.wav"

    if not wav_path.is_file():
        return jsonify({"error": f"Processed audio not found for file_id: {file_id}"}), 404

    response, status = _run_transcription(
        wav_path,
        file_id=file_id,
        preprocessing="upload_pipeline",
    )
    if status == 200:
        _save_transcript(response, label=file_id)
    return jsonify(response), status
