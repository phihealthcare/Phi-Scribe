import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_HOTWORDS_PROMPT_PATH = _ROOT / "benchmarks" / "prompts" / "whisper-initial-hotwords.txt"


def _default_whisper_initial_prompt() -> str:
    if _DEFAULT_HOTWORDS_PROMPT_PATH.is_file():
        return _DEFAULT_HOTWORDS_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return (
        "Transcrição literal de consulta médica em português brasileiro. "
        "Preservar a fala original, incluindo expressões informais."
    )


def _optional_float_env(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    DEBUG = False
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
    PROCESSED_FOLDER = os.environ.get("PROCESSED_FOLDER", "uploads/processed")
    PUBLIC_FOLDER = os.environ.get("PUBLIC_FOLDER", "public")
    # Sized for a ~90 min consultation: measured MediaRecorder output (Chrome,
    # audio/webm;codecs=opus, continuous audio) is ~125 kbps; budgeted at
    # ~165 kbps to leave margin for Safari's audio/mp4 (AAC) fallback.
    # Keep in sync with VITE_MAX_UPLOAD_BYTES (frontend/.env.example) and
    # DEFAULT_MAX_UPLOAD_BYTES (frontend/src/api/validateAudioFile.ts).
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 110 * 1024 * 1024))
    DENOISE_ENABLED = os.environ.get("DENOISE_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    DENOISE_PROP_DECREASE = float(os.environ.get("DENOISE_PROP_DECREASE", 0.6))
    ENHANCE_VOICE_ENABLED = os.environ.get("ENHANCE_VOICE_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    ENHANCE_DEEP_ENABLED = os.environ.get("ENHANCE_DEEP_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    ENHANCE_DEEP_MODEL = os.environ.get("ENHANCE_DEEP_MODEL", "DeepFilterNet3")
    ENHANCE_DEEP_DEVICE = os.environ.get("ENHANCE_DEEP_DEVICE", "cpu").lower()
    ENHANCE_DEEP_POST_FILTER = os.environ.get("ENHANCE_DEEP_POST_FILTER", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    _enhance_deep_atten_lim_db = os.environ.get("ENHANCE_DEEP_ATTEN_LIM_DB", "").strip()
    ENHANCE_DEEP_ATTEN_LIM_DB = (
        float(_enhance_deep_atten_lim_db) if _enhance_deep_atten_lim_db else None
    )
    HPF_ENABLED = os.environ.get("HPF_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    HPF_CUTOFF_HZ = float(os.environ.get("HPF_CUTOFF_HZ", 80))
    LPF_ENABLED = os.environ.get("LPF_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    LPF_CUTOFF_HZ = float(os.environ.get("LPF_CUTOFF_HZ", 7500))
    AGC_ENABLED = os.environ.get("AGC_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    AGC_TARGET_DBFS = float(os.environ.get("AGC_TARGET_DBFS", -20))
    AGC_MAX_GAIN_DB = float(os.environ.get("AGC_MAX_GAIN_DB", 12))
    AGC_WINDOW_MS = int(os.environ.get("AGC_WINDOW_MS", 30))
    LOUDNESS_ENABLED = os.environ.get("LOUDNESS_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    LOUDNESS_MODE = os.environ.get("LOUDNESS_MODE", "lufs").lower()
    LOUDNESS_TARGET_LUFS = float(os.environ.get("LOUDNESS_TARGET_LUFS", -23))
    LOUDNESS_TRUE_PEAK = float(os.environ.get("LOUDNESS_TRUE_PEAK", -1.5))
    LOUDNESS_LRA = float(os.environ.get("LOUDNESS_LRA", 11))
    LOUDNESS_PEAK_TARGET_DBFS = float(os.environ.get("LOUDNESS_PEAK_TARGET_DBFS", -1.0))
    VAD_ENABLED = os.environ.get("VAD_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", 0.5))
    VAD_MIN_SPEECH_DURATION_MS = int(os.environ.get("VAD_MIN_SPEECH_DURATION_MS", 250))
    VAD_MIN_SILENCE_DURATION_MS = int(os.environ.get("VAD_MIN_SILENCE_DURATION_MS", 1000))
    VAD_SPEECH_PAD_MS = int(os.environ.get("VAD_SPEECH_PAD_MS", 300))
    EXPORT_PCM_ENABLED = os.environ.get("EXPORT_PCM_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    WHISPER_FASTER_ENABLED = os.environ.get("WHISPER_FASTER_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    WHISPER_FASTER_MODEL = os.environ.get("WHISPER_FASTER_MODEL", "small")
    WHISPER_FASTER_DEVICE = os.environ.get("WHISPER_FASTER_DEVICE", "cpu")
    WHISPER_FASTER_COMPUTE_TYPE = os.environ.get("WHISPER_FASTER_COMPUTE_TYPE", "int8")
    WHISPER_FASTER_LANGUAGE = os.environ.get("WHISPER_FASTER_LANGUAGE", "pt")
    WHISPER_FASTER_BEAM_SIZE = int(os.environ.get("WHISPER_FASTER_BEAM_SIZE", 5))
    WHISPER_FASTER_INITIAL_PROMPT = os.environ.get(
        "WHISPER_FASTER_INITIAL_PROMPT",
        _default_whisper_initial_prompt(),
    )
    WHISPER_FASTER_VAD_FILTER = os.environ.get("WHISPER_FASTER_VAD_FILTER", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    WHISPER_FASTER_COMPRESSION_RATIO_THRESHOLD = _optional_float_env(
        "WHISPER_FASTER_COMPRESSION_RATIO_THRESHOLD",
        2.4,
    )
    WHISPER_FASTER_LOG_PROB_THRESHOLD = _optional_float_env(
        "WHISPER_FASTER_LOG_PROB_THRESHOLD",
        -1.0,
    )
    WHISPER_FASTER_HALLUCINATION_SILENCE_THRESHOLD = _optional_float_env(
        "WHISPER_FASTER_HALLUCINATION_SILENCE_THRESHOLD",
        None,
    )
    WHISPER_FASTER_CONDITION_ON_PREVIOUS_TEXT = os.environ.get(
        "WHISPER_FASTER_CONDITION_ON_PREVIOUS_TEXT",
        "true",
    ).lower() in {"true", "1", "yes"}
    WHISPER_FASTER_INFERENCE_MODE = os.environ.get(
        "WHISPER_FASTER_INFERENCE_MODE",
        "sequential",
    ).lower()
    WHISPER_FASTER_BATCH_SIZE = int(os.environ.get("WHISPER_FASTER_BATCH_SIZE", "16"))
    _whisper_chunk_length = os.environ.get("WHISPER_FASTER_CHUNK_LENGTH", "").strip()
    WHISPER_FASTER_CHUNK_LENGTH = (
        int(_whisper_chunk_length) if _whisper_chunk_length else None
    )
    DIARIZATION_ENABLED = os.environ.get("DIARIZATION_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    DIARIZATION_NUM_SPEAKERS = int(os.environ.get("DIARIZATION_NUM_SPEAKERS", 2))
    DIARIZATION_MIN_TURN_MS = int(os.environ.get("DIARIZATION_MIN_TURN_MS", 400))
    DIARIZATION_MODEL = os.environ.get(
        "DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"
    )
    DIARIZATION_DEVICE = os.environ.get("DIARIZATION_DEVICE", "").strip() or None
    HF_TOKEN = os.environ.get("HF_TOKEN", "").strip() or None

    # Experimental alternative diarization backend (nvidia/diar_sortformer_4spk-v1
    # via NeMo, run in an isolated .venv-sortformer/ subprocess — see
    # app/services/diarization_sortformer.py for why it's isolated). Only takes
    # effect when DIARIZATION_ENABLED is also true; "pyannote" (default) keeps
    # today's behavior unchanged.
    DIARIZATION_BACKEND = os.environ.get("DIARIZATION_BACKEND", "pyannote").strip().lower()
    SORTFORMER_MODEL_ID = os.environ.get("SORTFORMER_MODEL_ID", "nvidia/diar_sortformer_4spk-v1")
    SORTFORMER_DEVICE = os.environ.get("SORTFORMER_DEVICE", "cuda")
    # Per-call ceiling — Sortformer's VRAM use scales much faster than linearly
    # with audio length (empirically: 5min ≈ 3.7GB, 6min OOMs on a 6GB GPU).
    # Audio longer than this is chunked (SORTFORMER_CHUNK_S/OVERLAP_S below)
    # rather than rejected.
    SORTFORMER_MAX_DURATION_S = float(os.environ.get("SORTFORMER_MAX_DURATION_S", 300))
    SORTFORMER_VENV_PYTHON = os.environ.get("SORTFORMER_VENV_PYTHON", "").strip() or None
    # Chunk size/overlap used to diarize audio longer than SORTFORMER_MAX_DURATION_S
    # (see diarize_wav_sortformer_chunked in diarization_sortformer.py). Overlap
    # is used to stitch speaker identities across chunk boundaries.
    SORTFORMER_CHUNK_S = float(os.environ.get("SORTFORMER_CHUNK_S", 240))
    SORTFORMER_CHUNK_OVERLAP_S = float(os.environ.get("SORTFORMER_CHUNK_OVERLAP_S", 20))
    # Keep a persistent worker process (NeMo imported, model loaded in GPU
    # memory) alive across requests instead of paying the ~4s import + ~1.6s
    # model-load cost on every single call — see sortformer_daemon.py. Falls
    # back to the one-shot subprocess automatically if the daemon can't be
    # reached, so this is safe to leave on; set false only to force the old
    # one-shot-per-call behavior (e.g. while debugging).
    SORTFORMER_USE_DAEMON = os.environ.get("SORTFORMER_USE_DAEMON", "true").strip().lower() in {"true", "1", "yes"}
    TRANSCRIPT_POSTPROCESS_ENABLED = os.environ.get(
        "TRANSCRIPT_POSTPROCESS_ENABLED",
        "false",
    ).lower() in {"true", "1", "yes"}
    ASR_FIX_ENABLED = os.environ.get("ASR_FIX_ENABLED", "true").lower() in {
        "true",
        "1",
        "yes",
    }
    TRANSCRIPT_POSTPROCESS_PROVIDER = os.environ.get("TRANSCRIPT_POSTPROCESS_PROVIDER", "phihc")
    TRANSCRIPT_POSTPROCESS_MODEL = os.environ.get(
        "TRANSCRIPT_POSTPROCESS_MODEL",
        "gemma3:12b-it-qat",
    )
    TRANSCRIPT_POSTPROCESS_PROMPT_PATH = os.environ.get(
        "TRANSCRIPT_POSTPROCESS_PROMPT_PATH",
        "benchmarks/prompts/medical-transcript-editor.md",
    )
    TRANSCRIPT_DIARIZATION_LABEL_PROMPT_PATH = os.environ.get(
        "TRANSCRIPT_DIARIZATION_LABEL_PROMPT_PATH",
        "benchmarks/prompts/medical-transcript-diarization-labels.md",
    )
    TRANSCRIPT_DIARIZATION_LABELS_ENABLED = os.environ.get(
        "TRANSCRIPT_DIARIZATION_LABELS_ENABLED",
        "false",
    ).lower() in {"true", "1", "yes"}
    # LLM-only diarization (no pyannote): split plain ASR-fixed text into
    # Doutor:/Paciente: turns. Runs after ASR fix, before SOAP. Independent of
    # DIARIZATION_ENABLED/TRANSCRIPT_DIARIZATION_LABELS_ENABLED (pyannote path).
    MANUAL_DIARIZATION_PROMPT_PATH = os.environ.get(
        "MANUAL_DIARIZATION_PROMPT_PATH",
        "benchmarks/prompts/medical-transcript-manual-diarization.md",
    )
    MANUAL_DIARIZATION_ENABLED = os.environ.get(
        "MANUAL_DIARIZATION_ENABLED",
        "false",
    ).lower() in {"true", "1", "yes"}
    MANUAL_DIARIZATION_MIN_WORD_RATIO = float(
        os.environ.get("MANUAL_DIARIZATION_MIN_WORD_RATIO", 0.90)
    )
    SOAP_DRAFT_PROMPT_PATH = os.environ.get(
        "SOAP_DRAFT_PROMPT_PATH",
        "benchmarks/prompts/soap-draft.md",
    )
    SOAP_PROMPTS_DIR = os.environ.get(
        "SOAP_PROMPTS_DIR",
        "benchmarks/prompts",
    )
    SOAP_ENABLED = os.environ.get("SOAP_ENABLED", "true").lower() in {
        "true",
        "1",
        "yes",
    }
    SOAP_SPLIT_ENABLED = os.environ.get("SOAP_SPLIT_ENABLED", "true").lower() in {
        "true",
        "1",
        "yes",
    }
    _prompt_compact_raw = os.environ.get("PROMPT_COMPACT", "").strip()
    if _prompt_compact_raw:
        PROMPT_COMPACT = _prompt_compact_raw.lower() in {"true", "1", "yes"}
    else:
        PROMPT_COMPACT = os.environ.get("SOAP_PROMPT_COMPACT", "false").lower() in {
            "true",
            "1",
            "yes",
        }
    SOAP_PROMPT_COMPACT = PROMPT_COMPACT
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.phihc.com").strip().rstrip("/")
    _llm_api_key = os.environ.get("LLM_API_KEY", "").strip()
    LLM_API_KEY = _llm_api_key if _llm_api_key.lower() not in {"", "null", "none"} else None
    LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS", "600"))
    LLM_ASR_FIX_TIMEOUT_SECONDS = int(os.environ.get("LLM_ASR_FIX_TIMEOUT_SECONDS", "900"))
    ASR_FIX_MIN_WORD_RATIO = float(os.environ.get("ASR_FIX_MIN_WORD_RATIO", "0.90"))
    ASR_FIX_MIN_SPEAKER_LINE_RATIO = float(
        os.environ.get("ASR_FIX_MIN_SPEAKER_LINE_RATIO", "0.90")
    )
    ASR_FIX_CHUNK_MAX_WORDS = int(os.environ.get("ASR_FIX_CHUNK_MAX_WORDS", "450"))
    ASR_FIX_CHUNK_PARALLEL = os.environ.get("ASR_FIX_CHUNK_PARALLEL", "true").lower() in {
        "true",
        "1",
        "yes",
    }
    ASR_FIX_CHUNK_MAX_WORKERS = int(os.environ.get("ASR_FIX_CHUNK_MAX_WORKERS", "2"))
    LLM_ASR_FIX_MAX_RETRIES = int(os.environ.get("LLM_ASR_FIX_MAX_RETRIES", "2"))
    LLM_SOAP_MAX_RETRIES = int(os.environ.get("LLM_SOAP_MAX_RETRIES", "0"))
    SOAP_PATIENT_CHART_CONTEXT = os.environ.get("SOAP_PATIENT_CHART_CONTEXT", "").strip()
    SOAP_PATIENT_CHART_FILE = os.environ.get("SOAP_PATIENT_CHART_FILE", "").strip()
    PIPELINE_DEBUG_LOG_ENABLED = os.environ.get("PIPELINE_DEBUG_LOG_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    # Per-step wall-clock timing for POST /upload (logs + upload_timing.json + API field).
    UPLOAD_STEP_TIMING_ENABLED = os.environ.get("UPLOAD_STEP_TIMING_ENABLED", "true").lower() in {
        "true",
        "1",
        "yes",
    }


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
