from app.services.prompt_format import compact_prompt_text
from app.services.soap_draft import (
    SOAP_USER_INSTRUCTIONS_SEPARATOR,
    _build_user_message,
    compose_soap_user_prompt,
    load_soap_prompt,
)


def test_compact_prompt_text_strips_markdown() -> None:
    raw = "## TÍTULO\n\n**Negrito** e `código`.\n\n---\n\n```json\n{\"a\": 1}\n```"
    compact = compact_prompt_text(raw)
    assert "##" not in compact
    assert "**" not in compact
    assert "```" not in compact
    assert "---" not in compact
    assert "TÍTULO" in compact
    assert "Negrito" in compact


def test_build_user_message_compact_omits_transcript_envelope() -> None:
    transcript = "Falante 1: Olá, bom dia!\nFalante 2: Bom dia!"
    message = _build_user_message(
        segmented_transcript=transcript,
        diarization_enabled=True,
        prompt_compact=True,
    )
    assert "TRANSCRIÇÃO:" not in message
    assert "<<<" not in message
    assert "Falante 1: Olá, bom dia!" in message
    assert "Falante 2: Bom dia!" in message


def test_build_user_message_verbose_keeps_envelope() -> None:
    message = _build_user_message(
        segmented_transcript="Falante 1: teste",
        prompt_compact=False,
    )
    assert "TRANSCRIÇÃO:" in message
    assert "<<<" in message


def test_compose_soap_user_prompt_compact_separator() -> None:
    composed = compose_soap_user_prompt("INSTR", "TAREFA", prompt_compact=True)
    assert SOAP_USER_INSTRUCTIONS_SEPARATOR not in composed
    assert composed == "INSTR\n\nTAREFA"


def test_load_soap_prompt_compact_is_shorter() -> None:
    verbose = load_soap_prompt(diarization_enabled=False, prompt_compact=False)
    compact = load_soap_prompt(diarization_enabled=False, prompt_compact=True)
    assert len(compact) < len(verbose)
    assert "##" not in compact
    assert "{{SOAP_AMBULATORY_STYLE}}" not in compact
