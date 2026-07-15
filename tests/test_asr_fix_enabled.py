from unittest.mock import patch

from app.services.soap_prerequisites import can_generate_soap
from app.services.transcript_postprocess import (
    ASR_FIX_DISABLED_ERROR,
    asr_fix_enabled_for_config,
    edit_transcript_from_config,
)


def test_asr_fix_enabled_defaults_true() -> None:
    assert asr_fix_enabled_for_config({}) is True
    assert asr_fix_enabled_for_config({"ASR_FIX_ENABLED": "true"}) is True


def test_asr_fix_disabled_from_config() -> None:
    assert asr_fix_enabled_for_config({"ASR_FIX_ENABLED": "false"}) is False


def test_can_generate_soap_when_asr_fix_disabled() -> None:
    postprocess = {
        "skipped": False,
        "asr_fix": {"skipped": True, "error": ASR_FIX_DISABLED_ERROR},
        "diarization_labels": {"skipped": True, "error": "diarization_labels_disabled"},
    }
    ok, reason = can_generate_soap(postprocess, diarization_enabled=True)
    assert ok is True
    assert reason == ""


def test_can_generate_soap_still_blocks_on_asr_failure() -> None:
    postprocess = {
        "skipped": False,
        "asr_fix": {"skipped": True, "error": "missing_llm_api_key"},
    }
    ok, reason = can_generate_soap(postprocess, diarization_enabled=False)
    assert ok is False
    assert reason == "missing_llm_api_key"


@patch("app.services.transcript_postprocess.edit_transcript")
def test_edit_transcript_from_config_skips_asr_when_disabled(mock_edit) -> None:
    result = edit_transcript_from_config(
        "texto whisper",
        {
            "TRANSCRIPT_POSTPROCESS_ENABLED": True,
            "ASR_FIX_ENABLED": False,
            "DIARIZATION_ENABLED": False,
            "LLM_BASE_URL": "https://api.example.com",
            "LLM_API_KEY": "test-key",
        },
        diarization_enabled=False,
    )
    mock_edit.assert_not_called()
    assert result["text"] == "texto whisper"
    assert result["skipped"] is False
    assert result["asr_fix"]["error"] == ASR_FIX_DISABLED_ERROR
    assert result["asr_fix"]["skipped"] is True
