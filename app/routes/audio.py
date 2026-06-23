import json
import tempfile
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from app.services import transcribe
from app.services.audio_processor import preprocess_audio
from app.services.transcript_postprocess import edit_transcript_from_config, save_postprocess_diff_file

audio_bp = Blueprint("audio", __name__, url_prefix="/api/v1/audio")

ALLOWED_EXTENSIONS = {"mp3", "wav"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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


def _run_transcription(audio_path: Path, *, file_id: str, preprocessing: str) -> tuple[dict, int]:
    try:
        transcription = transcribe.transcribe_wav(
            audio_path,
            **transcribe.transcribe_options_from_mapping(current_app.config),
        )
    except RuntimeError as exc:
        return {"error": str(exc)}, 503
    except Exception as exc:
        return {"error": f"Transcription failed: {exc}"}, 500

    raw_text = str(transcription.get("text", ""))
    postprocess_enabled = bool(current_app.config.get("TRANSCRIPT_POSTPROCESS_ENABLED"))

    response: dict = {
        "file_id": file_id,
        "source_audio": str(audio_path),
        "preprocessing": preprocessing,
        "transcription": transcription,
        "source": "faster-whisper",
        "experimental": True,
    }

    if postprocess_enabled:
        transcription["raw_text"] = raw_text
        postprocess_result = edit_transcript_from_config(raw_text, current_app.config)
        response["postprocess"] = {
            "enabled": True,
            "provider": postprocess_result["provider"],
            "model": postprocess_result["model"],
            "skipped": postprocess_result["skipped"],
            "error": postprocess_result["error"],
        }
        if diff := postprocess_result.get("diff"):
            response["postprocess"]["diff"] = diff
        if not postprocess_result["skipped"]:
            transcription["text"] = postprocess_result["text"]

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


@audio_bp.post("/upload")
def upload_audio():
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request. Use field name 'file'."}), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed types: mp3, wav"}), 400

    original_filename = secure_filename(file.filename)
    file_id = str(uuid.uuid4())
    extension = original_filename.rsplit(".", 1)[1].lower()
    stored_filename = f"{file_id}.{extension}"

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)

    filepath = upload_folder / stored_filename
    file.save(filepath)

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
        )
    except Exception as exc:
        filepath.unlink(missing_ok=True)
        return jsonify({"error": f"Failed to process audio: {exc}"}), 500

    response = {
        "message": "File uploaded and processed successfully",
        "file_id": file_id,
        "filename": original_filename,
        "stored_as": stored_filename,
        "size_bytes": filepath.stat().st_size,
        "content_type": file.content_type,
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
            "pcm": {
                "stored_as": processed_pcm_filename,
                "format": processed["pcm"]["format"],
                "sample_rate": processed["pcm"]["sample_rate"],
                "channels": processed["pcm"]["channels"],
                "sample_width_bits": processed["pcm"]["sample_width_bits"],
                "duration_ms": processed["pcm"]["duration_ms"],
                "size_bytes": processed["pcm"]["size_bytes"],
            },
        },
    }

    if "vad" in processed:
        response["vad"] = processed["vad"]

    if "loudness" in processed:
        response["loudness"] = processed["loudness"]

    if "enhance_voice" in processed:
        response["enhance_voice"] = processed["enhance_voice"]

    if "enhance_deep" in processed:
        response["enhance_deep"] = processed["enhance_deep"]

    return jsonify(response), 201


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
                    "error": f"Audio not found in {public_folder}: {stem}.mp3 or {stem}.wav",
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
    """Transcribe an uploaded MP3/WAV directly with no preprocessing."""
    if not current_app.config["WHISPER_FASTER_ENABLED"]:
        return _whisper_disabled_response()

    if "file" not in request.files:
        return jsonify({"error": "No file part in the request. Use field name 'file'."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed types: mp3, wav"}), 400

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
