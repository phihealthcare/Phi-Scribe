import pytest

from app import create_app
from app.services import transcribe


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app("default")
    app.config["WHISPER_FASTER_ENABLED"] = True
    app.config["PROCESSED_FOLDER"] = str(tmp_path)
    app.config["TRANSCRIPT_POSTPROCESS_ENABLED"] = False
    app.config["PIPELINE_DEBUG_LOG_ENABLED"] = False
    return app.test_client()


def _write_processed_wav(tmp_path, file_id: str) -> None:
    (tmp_path / f"{file_id}.wav").write_bytes(b"RIFF....WAVEfmt ")


def test_transcribe_failure_returns_500_and_keeps_audio_on_disk(client, tmp_path, monkeypatch):
    file_id = "consulta-123"
    _write_processed_wav(tmp_path, file_id)

    def _boom(*args, **kwargs):
        raise RuntimeError("faster-whisper crashed")

    monkeypatch.setattr(transcribe, "transcribe_wav", _boom)

    response = client.post(f"/api/v1/audio/{file_id}/transcribe")

    assert response.status_code == 503
    assert "faster-whisper crashed" in response.get_json()["error"]
    assert (tmp_path / f"{file_id}.wav").is_file()


def test_transcribe_retry_succeeds_without_reupload_after_prior_failure(
    client, tmp_path, monkeypatch
):
    file_id = "consulta-456"
    _write_processed_wav(tmp_path, file_id)

    calls = {"count": 0}

    def _fail_then_succeed(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient failure")
        return {"text": "ok", "duration_ms": 10, "run": "faster-whisper"}

    monkeypatch.setattr(transcribe, "transcribe_wav", _fail_then_succeed)

    first = client.post(f"/api/v1/audio/{file_id}/transcribe")
    assert first.status_code == 503

    retry = client.post(f"/api/v1/audio/{file_id}/transcribe")
    assert retry.status_code == 200
    assert retry.get_json()["transcription"]["text"] == "ok"
    assert calls["count"] == 2
