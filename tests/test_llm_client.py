from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm_client import _read_response_with_deadline, medgemma_generate
from app.services.pipeline_steps import TRANSCRIBE_04B_LLM_DIARIZATION_LABELS
from app.services.pipeline_tracker import PipelineTracker


class _ChunkedResponse:
    """Minimal stand-in for http.client.HTTPResponse: .read(n) pops chunks."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def read(self, _size: int) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_medgemma_generate_logs_timeout_to_llm_requests(tmp_path: Path):
    tracker = PipelineTracker(run_id="timeout-run", log_dir=tmp_path)

    with patch("app.services.llm_client.urllib.request.urlopen") as urlopen_mock:
        urlopen_mock.side_effect = TimeoutError("The read operation timed out")
        with pytest.raises(RuntimeError, match="The read operation timed out"):
            medgemma_generate(
                prompt="user prompt body",
                system_prompt="system rules",
                model="gemma3:12b-it-qat",
                base_url="https://api.example.com",
                api_key="test-key",
                timeout=600,
                tracker=tracker,
                tracker_step_id=TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
                tracker_request_meta={"prompt_path": "/tmp/labels.md"},
            )

    log_path = tracker.llm_requests_path()
    document = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(document["requests"]) == 1
    entry = document["requests"][0]
    assert entry["step_id"] == TRANSCRIBE_04B_LLM_DIARIZATION_LABELS
    assert entry["error"] == "The read operation timed out"
    assert entry["request"]["prompt"] == "user prompt body"
    assert entry["request"]["system_prompt"] == "system rules"
    assert entry["request"]["timeout_seconds"] == 600
    assert entry["response"] is None

    step_path = tmp_path / "09_transcribe_04b_llm_diarization_labels.json"
    assert step_path.is_file()
    step = json.loads(step_path.read_text(encoding="utf-8"))
    assert step["error"] == "The read operation timed out"
    assert step["request"]["prompt"] == "user prompt body"


def test_read_response_with_deadline_raises_on_max_bytes():
    # Simulates a runaway/degenerate generation: the server keeps streaming
    # small chunks that individually never trip a read timeout, but the total
    # blows past what any legitimate SOAP-section response should be.
    chunks = [b"x" * 1000 for _ in range(500)]  # 500,000 bytes total
    response = _ChunkedResponse(chunks)
    with pytest.raises(RuntimeError, match="exceeded .* bytes"):
        _read_response_with_deadline(response, deadline_s=600, max_bytes=200_000)


def test_read_response_with_deadline_raises_on_wall_clock_timeout():
    # Each read "trickles" data slower than the reads accumulate, but no
    # single read blocks long enough to trip urllib's own per-read timeout —
    # only the wall-clock deadline here catches it.
    import time as time_module

    class _SlowResponse:
        def read(self, _size: int) -> bytes:
            time_module.sleep(0.03)
            return b"x"  # never returns b"" — simulates an endless stream

    with pytest.raises(TimeoutError, match="wall-clock deadline"):
        _read_response_with_deadline(_SlowResponse(), deadline_s=0.05, max_bytes=200_000)


def test_medgemma_generate_fails_cleanly_on_runaway_response(tmp_path: Path):
    tracker = PipelineTracker(run_id="runaway-run", log_dir=tmp_path)
    chunks = [b'{"start_of_turn": "model"' * 50 for _ in range(500)]  # well over 200KB

    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=_ChunkedResponse(chunks))
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("app.services.llm_client.urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(RuntimeError, match="likely a runaway/degenerate generation"):
            medgemma_generate(
                prompt="transcript body",
                model="gemma3:12b-it-qat",
                base_url="https://api.example.com",
                api_key="test-key",
                timeout=600,
                tracker=tracker,
                tracker_step_id=TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
            )

    log_path = tracker.llm_requests_path()
    document = json.loads(log_path.read_text(encoding="utf-8"))
    entry = document["requests"][0]
    assert "runaway/degenerate generation" in entry["error"]
