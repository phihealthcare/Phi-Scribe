import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    DEBUG = False
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
    PROCESSED_FOLDER = os.environ.get("PROCESSED_FOLDER", "uploads/processed")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 50 * 1024 * 1024))
    DENOISE_ENABLED = os.environ.get("DENOISE_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    DENOISE_PROP_DECREASE = float(os.environ.get("DENOISE_PROP_DECREASE", 0.6))
    VAD_ENABLED = os.environ.get("VAD_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", 0.5))
    VAD_MIN_SPEECH_DURATION_MS = int(os.environ.get("VAD_MIN_SPEECH_DURATION_MS", 250))
    VAD_MIN_SILENCE_DURATION_MS = int(os.environ.get("VAD_MIN_SILENCE_DURATION_MS", 1000))
    VAD_SPEECH_PAD_MS = int(os.environ.get("VAD_SPEECH_PAD_MS", 300))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
