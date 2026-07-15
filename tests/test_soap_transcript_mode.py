from app.services.soap_draft import (
    SOAP_PRIVACY_PLACEHOLDER,
    SOAP_TRANSCRIPT_MODE_PLACEHOLDER,
    load_soap_prompt,
    load_soap_section_prompt,
    load_soap_privacy,
    load_soap_transcript_mode,
)


def test_load_soap_transcript_mode_plain() -> None:
    mode = load_soap_transcript_mode(diarization_enabled=False)
    assert "sem diarização" in mode.lower()
    assert "Médico:" in mode


def test_load_soap_privacy_forbids_personal_names() -> None:
    privacy = load_soap_privacy()
    assert "SEM NOMES PESSOAIS" in privacy
    assert "Legenda" in privacy


def test_load_soap_transcript_mode_diarized() -> None:
    mode = load_soap_transcript_mode(
        diarization_enabled=True,
        postprocess_applied=True,
    )
    assert "Médico:" in mode
    assert "Paciente:" in mode


def test_load_soap_prompt_injects_transcript_mode_and_privacy() -> None:
    prompt = load_soap_prompt(diarization_enabled=False)
    assert SOAP_TRANSCRIPT_MODE_PLACEHOLDER not in prompt
    assert SOAP_PRIVACY_PLACEHOLDER not in prompt
    assert "sem diarização" in prompt.lower()
    assert "SEM NOMES PESSOAIS" in prompt


def test_load_soap_section_prompt_injects_privacy() -> None:
    prompt = load_soap_section_prompt("objetivo", diarization_enabled=False, omit_transcript=True)
    assert "SEM NOMES PESSOAIS" in prompt
