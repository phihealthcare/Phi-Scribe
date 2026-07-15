from app.services.pipeline_steps import prompt_compact_for_config
from app.services.prompt_format import compact_prompt_text
from app.services.transcript_postprocess import (
    ASR_USER_INSTRUCTIONS_SEPARATOR,
    _build_asr_user_message,
    _split_transcript_for_asr_fix,
    compose_asr_user_prompt,
    load_editor_prompt,
)


def test_prompt_compact_for_config_prefers_prompt_compact() -> None:
    assert prompt_compact_for_config({"PROMPT_COMPACT": True}) is True
    assert prompt_compact_for_config({"PROMPT_COMPACT": False, "SOAP_PROMPT_COMPACT": True}) is False
    assert prompt_compact_for_config({"SOAP_PROMPT_COMPACT": True}) is True


def test_compose_asr_user_prompt_compact_separator() -> None:
    composed = compose_asr_user_prompt("INSTR", "TAREFA", prompt_compact=True)
    assert ASR_USER_INSTRUCTIONS_SEPARATOR not in composed
    assert composed == "INSTR\n\nTAREFA"


def test_build_asr_user_message_compact_omits_envelope() -> None:
    message = _build_asr_user_message("paciente com dor", prompt_compact=True)
    assert "<<<" not in message
    assert "paciente com dor" in message


def test_load_editor_prompt_compact_uses_compact_file_when_path_is_default() -> None:
    from app.services.transcript_postprocess import DEFAULT_PROMPT_PATH, load_editor_prompt

    verbose = load_editor_prompt(prompt_path=DEFAULT_PROMPT_PATH, prompt_compact=False)
    compact = load_editor_prompt(prompt_path=DEFAULT_PROMPT_PATH, prompt_compact=True)
    assert len(compact) < len(verbose) * 0.5


def test_load_editor_prompt_compact_is_much_shorter() -> None:
    verbose = load_editor_prompt(prompt_compact=False)
    compact = load_editor_prompt(prompt_compact=True)
    assert len(compact) < len(verbose) * 0.5
    assert "**" not in compact


def test_split_transcript_for_asr_fix_respects_max_words() -> None:
    text = " ".join(f"word{i}" for i in range(1000))
    chunks = _split_transcript_for_asr_fix(text, max_words=450)
    assert len(chunks) >= 2
    assert all(len(chunk.split()) <= 450 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()
