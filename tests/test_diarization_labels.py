from app.services.soap_prerequisites import can_generate_soap
from app.services.transcript_postprocess import (
    diarization_labels_applied,
    diarization_labels_enabled,
)


def test_diarization_labels_disabled_by_default() -> None:
    assert diarization_labels_enabled({}) is False
    assert diarization_labels_enabled({"TRANSCRIPT_DIARIZATION_LABELS_ENABLED": "false"}) is False


def test_diarization_labels_enabled_when_configured() -> None:
    assert diarization_labels_enabled({"TRANSCRIPT_DIARIZATION_LABELS_ENABLED": "true"}) is True


def test_diarization_labels_applied_when_step_succeeded() -> None:
    postprocess = {
        "diarization_labels": {"skipped": False, "error": None},
    }
    assert diarization_labels_applied(postprocess) is True


def test_diarization_labels_not_applied_when_disabled() -> None:
    postprocess = {
        "skipped": False,
        "asr_fix": {"skipped": False},
        "diarization_labels": {"skipped": True, "error": "diarization_labels_disabled"},
    }
    assert diarization_labels_applied(postprocess) is False
    ok, reason = can_generate_soap(postprocess, diarization_enabled=True)
    assert ok is True
    assert reason == ""
