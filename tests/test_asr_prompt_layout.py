from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.transcript_postprocess import (
    ASR_USER_INSTRUCTIONS_SEPARATOR,
    DEFAULT_ASR_SYSTEM_PROMPT,
    _build_asr_user_message,
    compose_asr_user_prompt,
    edit_transcript,
    label_diarized_transcript,
    resolve_asr_system_prompt,
)


def test_resolve_asr_system_prompt_default() -> None:
    assert resolve_asr_system_prompt() == DEFAULT_ASR_SYSTEM_PROMPT
    assert len(resolve_asr_system_prompt()) < 200


def test_resolve_asr_system_prompt_override() -> None:
    assert resolve_asr_system_prompt("Custom role.") == "Custom role."


def test_compose_asr_user_prompt_orders_instructions_first() -> None:
    composed = compose_asr_user_prompt("INSTRUÇÕES", "TAREFA")
    assert composed.startswith("INSTRUÇÕES")
    assert composed.endswith("TAREFA")
    assert ASR_USER_INSTRUCTIONS_SEPARATOR in composed


def test_edit_transcript_puts_editor_rules_in_user_prompt(tmp_path: Path) -> None:
    prompt_path = tmp_path / "medical-transcript-editor.md"
    prompt_path.write_text("REGRAS DO EDITOR ASR", encoding="utf-8")

    captured: dict[str, str] = {}

    def fake_generate(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        captured["prompt"] = kwargs["prompt"]
        return "paciente com dor abdominal intensa", "paciente com dor abdominal intensa"

    with patch(
        "app.services.transcript_postprocess.medgemma_generate",
        side_effect=fake_generate,
    ):
        result = edit_transcript(
            "paciente com dor abdominal intensa",
            enabled=True,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            prompt_path=prompt_path,
            timeout=30,
        )

    assert result["text"] == "paciente com dor abdominal intensa"
    assert captured["system_prompt"] == DEFAULT_ASR_SYSTEM_PROMPT
    assert "REGRAS DO EDITOR ASR" in captured["prompt"]
    assert "paciente com dor abdominal intensa" in captured["prompt"]
    assert captured["prompt"].index("REGRAS DO EDITOR ASR") < captured["prompt"].index(
        "paciente com dor abdominal intensa"
    )


def test_label_diarized_puts_rules_in_user_prompt(tmp_path: Path) -> None:
    prompt_path = tmp_path / "medical-transcript-diarization-labels.md"
    prompt_path.write_text("REGRAS DE RÓTULOS", encoding="utf-8")

    captured: dict[str, str] = {}

    def fake_generate(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        captured["prompt"] = kwargs["prompt"]
        return '{"falante_1": "Médico", "falante_2": "Paciente"}', "raw"

    with patch(
        "app.services.transcript_postprocess.medgemma_generate",
        side_effect=fake_generate,
    ):
        result = label_diarized_transcript(
            "Falante 1: olá\nFalante 2: bom dia",
            enabled=True,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            prompt_path=prompt_path,
            timeout=30,
        )

    assert result["text"] == "Médico: olá\nPaciente: bom dia"
    assert len(captured["system_prompt"]) < 200
    assert "REGRAS DE RÓTULOS" in captured["prompt"]
    assert "Falante 1: olá" in captured["prompt"]


def test_build_asr_user_message_wraps_transcript() -> None:
    message = _build_asr_user_message("paciente com dor", preserve_speaker_labels=False)
    assert "<<<" in message
    assert "paciente com dor" in message
