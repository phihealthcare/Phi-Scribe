from app.services.soap_prerequisites import can_generate_soap
from app.services.transcript_postprocess import (
    DIARIZATION_LABEL_SAMPLE_RATIO_CAP,
    _apply_diarization_label_mapping,
    _parse_diarization_label_mapping,
    _sample_for_diarization_labels,
    apply_diarization_label_mapping_to_segments,
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


def test_sample_returns_everything_when_text_is_short() -> None:
    text = "Falante 1: Bom dia.\nFalante 2: Bom dia, doutor."
    assert _sample_for_diarization_labels(text) == text


def test_sample_extends_until_both_speakers_appear() -> None:
    # Falante 2 only shows up at line 50 (past the default 15% of 200 lines = 30 lines) —
    # the sample must extend past the initial slice to include it, staying under the 30% cap.
    lines = [f"Falante 1: fala {i}." for i in range(49)]
    lines.append("Falante 2: primeira fala do paciente.")
    lines += [f"Falante 1: fala {i}." for i in range(50, 200)]
    text = "\n".join(lines)

    sample = _sample_for_diarization_labels(text)

    assert "Falante 2:" in sample
    assert len(sample.splitlines()) <= round(len(lines) * DIARIZATION_LABEL_SAMPLE_RATIO_CAP)


def test_sample_caps_out_if_second_speaker_never_shows_up() -> None:
    text = "\n".join(f"Falante 1: fala {i}." for i in range(200))
    sample = _sample_for_diarization_labels(text)
    assert len(sample.splitlines()) == round(200 * DIARIZATION_LABEL_SAMPLE_RATIO_CAP)


def test_parse_mapping_accepts_valid_json() -> None:
    mapping = _parse_diarization_label_mapping('{"falante_1": "Médico", "falante_2": "Paciente"}')
    assert mapping == {"Falante 1": "Médico", "Falante 2": "Paciente"}


def test_parse_mapping_rejects_same_role_twice() -> None:
    assert _parse_diarization_label_mapping('{"falante_1": "Médico", "falante_2": "Médico"}') is None


def test_parse_mapping_rejects_invalid_json() -> None:
    assert _parse_diarization_label_mapping("not json") is None


def test_parse_mapping_rejects_missing_keys() -> None:
    assert _parse_diarization_label_mapping('{"falante_1": "Médico"}') is None


def test_apply_mapping_swaps_prefix_and_preserves_rest_of_line() -> None:
    text = "Falante 1: Como está a dor?\nFalante 2: Melhorou um pouco.\nNota sem rótulo."
    mapping = {"Falante 1": "Médico", "Falante 2": "Paciente"}

    result = _apply_diarization_label_mapping(text, mapping)

    assert result == (
        "Médico: Como está a dor?\nPaciente: Melhorou um pouco.\nNota sem rótulo."
    )


def test_apply_mapping_to_segments_keeps_text_and_timestamps_consistent() -> None:
    segments = [
        {"speaker_id": "speaker_G0", "speaker_label": "Falante 1", "start_ms": 0, "text": "Como está a dor?"},
        {"speaker_id": "speaker_G1", "speaker_label": "Falante 2", "start_ms": 1000, "text": "Melhorou."},
    ]
    mapping = {"Falante 1": "Médico", "Falante 2": "Paciente"}

    result = apply_diarization_label_mapping_to_segments(segments, mapping)

    assert result == [
        {"speaker_id": "speaker_G0", "speaker_label": "Médico", "start_ms": 0, "text": "Como está a dor?"},
        {"speaker_id": "speaker_G1", "speaker_label": "Paciente", "start_ms": 1000, "text": "Melhorou."},
    ]
    # original list/dicts untouched (routes/audio.py reassigns the return value)
    assert segments[0]["speaker_label"] == "Falante 1"


def test_apply_mapping_to_segments_leaves_unknown_labels_untouched() -> None:
    segments = [{"speaker_id": "x", "speaker_label": "SPEAKER_00", "start_ms": 0, "text": "..."}]
    result = apply_diarization_label_mapping_to_segments(segments, {"Falante 1": "Médico", "Falante 2": "Paciente"})
    assert result[0]["speaker_label"] == "SPEAKER_00"
