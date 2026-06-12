from flask import Flask

from app.routes.audio import audio_bp

def register_blueprints(app: Flask) -> None:
    app.register_blueprint(audio_bp)
