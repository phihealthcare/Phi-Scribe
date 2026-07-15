from app.services.soap_draft import format_segmented_transcript, resolve_soap_input_transcript


def test_resolve_soap_input_uses_labeled_text_when_diarization_postprocess_applied() -> None:
    labeled_text = "Médico: Boa tarde.\nPaciente: Olá, doutor."
    segments = [
        {
            "text": "Boa",
            "speaker_label": "Falante 1",
            "start_ms": 0,
        }
    ]

    result = resolve_soap_input_transcript(
        labeled_text,
        segments=segments,
        diarization_enabled=True,
        postprocess_applied=True,
    )

    assert result == labeled_text
    assert "[00:" not in result
    assert "Falante" not in result


def test_resolve_soap_input_falls_back_to_segments_without_postprocess() -> None:
    text = "Falante 1: Boa tarde\nFalante 2: Olá, doutor."
    segments = [
        {
            "text": "Boa tarde",
            "speaker_label": "Falante 1",
            "start_ms": 1000,
        }
    ]

    result = resolve_soap_input_transcript(
        text,
        segments=segments,
        diarization_enabled=True,
        postprocess_applied=False,
    )

    assert result == text
    assert "Falante 1:" in result


def test_resolve_soap_input_uses_plain_text_when_diarization_disabled() -> None:
    fixed_text = "Olha, a urina continua um pouco forte. Vamos reavaliar com exames."
    segments = [
        {
            "text": "Olha,",
            "start_ms": 0,
        },
        {
            "text": "a urina continua um pouco forte.",
            "start_ms": 5000,
        },
    ]

    result = resolve_soap_input_transcript(
        fixed_text,
        segments=segments,
        diarization_enabled=False,
        postprocess_applied=True,
    )

    assert result == fixed_text
    assert "[00:" not in result

