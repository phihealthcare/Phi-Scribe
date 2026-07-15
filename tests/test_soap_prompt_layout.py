from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.services.soap_draft import (
    DEFAULT_SOAP_SYSTEM_PROMPT,
    SOAP_SECTIONS,
    SOAP_USER_INSTRUCTIONS_SEPARATOR,
    _generate_soap_monolithic,
    _generate_soap_section,
    compose_soap_user_prompt,
    resolve_soap_system_prompt,
)
from app.services.soap_validation import EXPECTED_SOAP_STATUS


def test_resolve_soap_system_prompt_default() -> None:
    assert resolve_soap_system_prompt() == DEFAULT_SOAP_SYSTEM_PROMPT
    assert len(resolve_soap_system_prompt()) < 200


def test_resolve_soap_system_prompt_override() -> None:
    assert resolve_soap_system_prompt("Custom role.") == "Custom role."


def test_compose_soap_user_prompt_orders_instructions_first() -> None:
    composed = compose_soap_user_prompt("INSTRUÇÕES", "TAREFA")
    assert composed.startswith("INSTRUÇÕES")
    assert composed.endswith("TAREFA")
    assert SOAP_USER_INSTRUCTIONS_SEPARATOR in composed


def _valid_monolithic_json() -> str:
    return (
        '{"status":"'
        + EXPECTED_SOAP_STATUS
        + '","soap":{"subjetivo":"Refere dor.","objetivo":"Sem dados objetivos suficientes na transcrição.",'
        '"avaliacao":"Avaliação não explicitada de forma suficiente na consulta.",'
        '"plano":"Conduta não explicitada de forma suficiente na consulta."},'
        '"alertas_revisao":[],"evidencias_chave":[]}'
    )


def test_monolithic_puts_soap_draft_in_user_prompt(tmp_path: Path) -> None:
    (tmp_path / "soap-transcript-mode-plain.md").write_text("Modo plain.", encoding="utf-8")
    (tmp_path / "soap-privacy.md").write_text("SEM NOMES PESSOAIS", encoding="utf-8")
    (tmp_path / "soap-style-ambulatorio.md").write_text("", encoding="utf-8")
    prompt_path = tmp_path / "soap-draft.md"
    prompt_path.write_text("REGRAS SOAP MONOLÍTICAS", encoding="utf-8")

    captured: dict[str, str] = {}

    def fake_generate(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        captured["prompt"] = kwargs["prompt"]
        return _valid_monolithic_json(), _valid_monolithic_json()

    with patch("app.services.soap_draft.medgemma_generate", side_effect=fake_generate):
        result = _generate_soap_monolithic(
            segmented_transcript="Paciente refere dor abdominal.",
            diarization_enabled=False,
            postprocess_applied=False,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            prompt_path=prompt_path,
            system_prompt=None,
            tracker=None,
            timeout=30,
            max_retries=0,
        )

    assert result["document"] is not None
    assert captured["system_prompt"] == DEFAULT_SOAP_SYSTEM_PROMPT
    assert "REGRAS SOAP MONOLÍTICAS" in captured["prompt"]
    assert "TRANSCRIÇÃO:" in captured["prompt"]
    assert captured["prompt"].index("REGRAS SOAP MONOLÍTICAS") < captured["prompt"].index("TRANSCRIÇÃO:")


def test_split_section_puts_instructions_in_user_prompt(tmp_path: Path) -> None:
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "soap-common.md").write_text(
        "{{SOAP_TRANSCRIPT_MODE}}\n\n{{SOAP_PRIVACY}}",
        encoding="utf-8",
    )
    (prompts_dir / "soap-transcript-mode-plain.md").write_text("Modo plain.", encoding="utf-8")
    (prompts_dir / "soap-privacy.md").write_text("SEM NOMES PESSOAIS", encoding="utf-8")
    (prompts_dir / "soap-style-ambulatorio.md").write_text("", encoding="utf-8")
    (prompts_dir / "soap-plano.md").write_text(
        "{{SOAP_COMMON}}\n\nGERE PLANO.",
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    def fake_generate(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        captured["prompt"] = kwargs["prompt"]
        return (
            '{"plano_conduta":"Solicito exames.","alertas_revisao":[]}',
            '{"plano_conduta":"Solicito exames.","alertas_revisao":[]}',
        )

    spec = next(item for item in SOAP_SECTIONS if item.section_id == "plano")

    with patch("app.services.soap_draft.medgemma_generate", side_effect=fake_generate):
        result = _generate_soap_section(
            spec,
            segmented_transcript="Médico: Solicito exames.",
            diarization_enabled=False,
            postprocess_applied=False,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            prompts_dir=prompts_dir,
            tracker=None,
            timeout=30,
            max_retries=0,
        )

    assert result["partial"] is not None
    assert captured["system_prompt"] == DEFAULT_SOAP_SYSTEM_PROMPT
    assert "GERE PLANO." in captured["prompt"]
    assert "SEM NOMES PESSOAIS" in captured["prompt"]
