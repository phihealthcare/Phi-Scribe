from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.routes.realtime import _handle_realtime_session


class _FakeWebSocket:
    """Minimal stand-in for flask_sock's ws object — no real network socket,
    just scripted .receive() values and a record of everything .send()."""

    def __init__(self, incoming: list) -> None:
        self._incoming = list(incoming)
        self.sent: list[dict] = []

    def receive(self):
        if not self._incoming:
            return None
        return self._incoming.pop(0)

    def send(self, data: str) -> None:
        self.sent.append(json.loads(data))


@pytest.fixture
def app_context():
    app = create_app("default")
    app.config["REALTIME_TRANSCRIPTION_ENABLED"] = True
    app.config["PIPELINE_DEBUG_LOG_ENABLED"] = False
    with app.app_context():
        yield app


def _fake_session_factory(stop_return=None):
    stop_return = stop_return or ({"file_id": "abc"}, 200)
    session = MagicMock()
    session.file_id = "abc"
    session.stopped = False
    session.push_audio_chunk.return_value = []

    def _stop():
        session.stopped = True
        return stop_return

    session.stop.side_effect = _stop
    return session


def test_client_sends_stop_triggers_soap_exactly_once(app_context):
    fake_session = _fake_session_factory()
    ws = _FakeWebSocket(
        incoming=[
            b"\x00\x01" * 100,  # a binary audio chunk
            b"\x00\x01" * 100,  # another chunk
            json.dumps({"type": "stop"}),
        ]
    )

    with patch("app.routes.realtime.RealtimeConsultationSession", return_value=fake_session):
        _handle_realtime_session(ws)

    assert fake_session.push_audio_chunk.call_count == 2
    assert fake_session.stop.call_count == 1
    event_types = [event["type"] for event in ws.sent]
    assert event_types[0] == "ready"
    assert event_types[-1] == "soap_ready"


def test_abrupt_disconnect_still_finalizes_exactly_once(app_context):
    """If the client disconnects without sending {"type":"stop"} (ws.receive()
    returns None), the session must still be finalized so the consultation's
    transcript/SOAP isn't silently lost — but only once."""
    fake_session = _fake_session_factory()
    ws = _FakeWebSocket(incoming=[b"\x00\x01" * 100])  # then receive() returns None

    with patch("app.routes.realtime.RealtimeConsultationSession", return_value=fake_session):
        _handle_realtime_session(ws)

    assert fake_session.push_audio_chunk.call_count == 1
    assert fake_session.stop.call_count == 1


def test_stop_never_called_twice_if_client_sends_stop_then_disconnects(app_context):
    fake_session = _fake_session_factory()
    ws = _FakeWebSocket(incoming=[json.dumps({"type": "stop"})])

    with patch("app.routes.realtime.RealtimeConsultationSession", return_value=fake_session):
        _handle_realtime_session(ws)

    assert fake_session.stop.call_count == 1


def test_unknown_control_message_sends_error_and_keeps_session_open(app_context):
    fake_session = _fake_session_factory()
    ws = _FakeWebSocket(
        incoming=[
            json.dumps({"type": "pause"}),
            json.dumps({"type": "stop"}),
        ]
    )

    with patch("app.routes.realtime.RealtimeConsultationSession", return_value=fake_session):
        _handle_realtime_session(ws)

    error_events = [e for e in ws.sent if e["type"] == "error"]
    assert len(error_events) == 1
    assert "pause" in error_events[0]["message"]
    assert fake_session.stop.call_count == 1


def test_finalize_failure_is_logged_not_raised(app_context, caplog):
    fake_session = _fake_session_factory()
    fake_session.stop.side_effect = RuntimeError("boom")
    ws = _FakeWebSocket(incoming=[json.dumps({"type": "stop"})])

    with patch("app.routes.realtime.RealtimeConsultationSession", return_value=fake_session):
        _handle_realtime_session(ws)  # must not raise

    assert fake_session.stop.call_count == 1
