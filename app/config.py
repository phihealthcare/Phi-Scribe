import os


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
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 50 * 1024 * 1024))
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
        "Transcrição de consulta médica em português brasileiro.",
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


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
