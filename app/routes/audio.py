import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from app.services.audio_processor import preprocess_audio

audio_bp = Blueprint("audio", __name__, url_prefix="/api/v1/audio")

ALLOWED_EXTENSIONS = {"mp3", "wav"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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
            denoise_enabled=current_app.config["DENOISE_ENABLED"],
            prop_decrease=current_app.config["DENOISE_PROP_DECREASE"],
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

    return jsonify(response), 201
