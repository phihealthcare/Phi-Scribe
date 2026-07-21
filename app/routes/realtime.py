"""Live transcription+diarization over a WebSocket. Only registered when
REALTIME_TRANSCRIPTION_ENABLED is true (see app/routes/__init__.py) — the
batch /upload + /<file_id>/transcribe flow in app/routes/audio.py is
completely unaffected either way.

Protocol:
    client -> server: binary frames = raw PCM16 mono 16kHz audio;
                       a {"type": "stop"} text frame ends the session.
    server -> client: {"type": "ready", "file_id"}
                       {"type": "partial"|"final", "start_ms", "end_ms", "text", "speaker_label"}
                       {"type": "speaker_update", "start_ms", "end_ms", "speaker"}
                       {"type": "soap_ready", "status", "response"} — same response
                           shape as a batch POST /<file_id>/transcribe, sent exactly
                           once, when the session stops (SOAP is never incremental).
                       {"type": "error", "message"}
"""
from __future__ import annotations

import json
import logging
import uuid

from flask import Blueprint, current_app
from flask_sock import Sock

from app.services.pipeline_tracker import tracker_from_config
from app.services.realtime_session import RealtimeConsultationSession

logger = logging.getLogger(__name__)

realtime_bp = Blueprint("realtime", __name__, url_prefix="/api/v1/realtime")
sock = Sock()


def _handle_realtime_session(ws) -> None:
    """The actual session loop — kept separate from the route registration
    below because flask_sock's @sock.route decorator doesn't return the
    original function (it registers a wrapper on the blueprint and the
    decorated name ends up bound to None), so this wouldn't otherwise be
    directly callable from tests without a real WebSocket upgrade request."""
    config = current_app.config
    file_id = str(uuid.uuid4())
    tracker = tracker_from_config(config, run_id=file_id)
    session = RealtimeConsultationSession(config=config, file_id=file_id, tracker=tracker)

    try:
        ws.send(json.dumps({"type": "ready", "file_id": session.file_id}))
        while True:
            message = ws.receive()
            if message is None:
                break
            if isinstance(message, (bytes, bytearray)):
                for event in session.push_audio_chunk(bytes(message)):
                    ws.send(json.dumps(event))
                continue
            try:
                control = json.loads(message)
            except (TypeError, ValueError):
                ws.send(json.dumps({"type": "error", "message": "invalid control message"}))
                continue
            if control.get("type") == "stop":
                break
            ws.send(
                json.dumps(
                    {"type": "error", "message": f"unknown control type: {control.get('type')!r}"}
                )
            )
    finally:
        if not session.stopped:
            try:
                response, status = session.stop()
            except Exception:
                logger.exception("[realtime] failed to finalize session %s", session.file_id)
            else:
                try:
                    ws.send(json.dumps({"type": "soap_ready", "status": status, "response": response}))
                except Exception:
                    logger.info(
                        "[realtime] session %s finalized but client already disconnected",
                        session.file_id,
                    )


@sock.route("/transcribe", bp=realtime_bp)
def realtime_transcribe(ws) -> None:
    _handle_realtime_session(ws)
