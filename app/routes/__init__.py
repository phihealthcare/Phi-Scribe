from flask import Flask

from app.routes.audio import audio_bp

def register_blueprints(app: Flask) -> None:
    app.register_blueprint(audio_bp)

    if app.config.get("REALTIME_TRANSCRIPTION_ENABLED"):
        from app.routes.realtime import realtime_bp

        app.register_blueprint(realtime_bp)
