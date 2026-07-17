from __future__ import annotations

from unittest.mock import patch

from app.services.llm_client import WARMUP_PROMPT, warm_up_llm


def _config(**overrides) -> dict:
    config = {"LLM_API_KEY": "test-key", "LLM_BASE_URL": "https://api.example.com"}
    config.update(overrides)
    return config


def test_warmup_sends_short_prompt() -> None:
    with patch("app.services.llm_client.medgemma_generate") as mock_generate:
        mock_generate.return_value = "ok"
        warm_up_llm(_config())

    assert mock_generate.call_count == 1
    kwargs = mock_generate.call_args.kwargs
    assert len(kwargs["prompt"]) < 50
    assert kwargs["prompt"] == WARMUP_PROMPT
    assert kwargs["max_retries"] == 0


def test_warmup_never_passes_tracker_step_id() -> None:
    """tracker_step_id must stay unset — medgemma_generate's main success path
    calls tracker.record(tracker_step_id, ...) whenever tracker_step_id is
    truthy (regardless of tracker_record_step), and "llm_warmup" isn't a
    registered PIPELINE_STEPS id, so passing it would raise KeyError deep
    inside a fire-and-forget background thread."""
    with patch("app.services.llm_client.medgemma_generate") as mock_generate:
        mock_generate.return_value = "ok"
        warm_up_llm(_config(), tracker=object())

    kwargs = mock_generate.call_args.kwargs
    assert kwargs.get("tracker_step_id") is None


def test_warmup_forwards_tracker_and_start_timestamp_in_meta() -> None:
    """When a tracker is given, it must reach medgemma_generate (which appends
    to llm_requests.json via append_llm_request) with an explicit started_at
    in meta — that's what lets a reader compare this call's [start, end]
    window against transcribe_01_diarization/transcribe_02_whisper's to see
    they overlap."""
    fake_tracker = object()
    with patch("app.services.llm_client.medgemma_generate") as mock_generate:
        mock_generate.return_value = "ok"
        warm_up_llm(_config(), tracker=fake_tracker)

    kwargs = mock_generate.call_args.kwargs
    assert kwargs["tracker"] is fake_tracker
    meta = kwargs["tracker_request_meta"]
    assert meta["kind"] == "warmup"
    assert "started_at" in meta


def test_warmup_swallows_medgemma_exceptions() -> None:
    with patch("app.services.llm_client.medgemma_generate", side_effect=RuntimeError("LLM HTTP 502")):
        warm_up_llm(_config())  # must not raise


def test_warmup_swallows_value_errors() -> None:
    with patch("app.services.llm_client.medgemma_generate", side_effect=ValueError("boom")):
        warm_up_llm(_config())  # must not raise


def test_warmup_skips_call_without_api_key() -> None:
    with patch("app.services.llm_client.medgemma_generate") as mock_generate:
        warm_up_llm(_config(LLM_API_KEY=""))

    mock_generate.assert_not_called()
