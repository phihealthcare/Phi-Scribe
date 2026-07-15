from unittest.mock import patch

from app.services.transcript_postprocess import (
    _build_asr_user_message,
    asr_fix_output_passes_guardrail,
    count_speaker_lines,
    edit_transcript,
    resolve_asr_fix_guardrail_settings,
)


def _speaker_line(n: int, text: str) -> str:
    return f"Falante {n}: {text}"


def test_count_speaker_lines() -> None:
    text = "\n".join(
        [
            _speaker_line(1, "oi"),
            _speaker_line(2, "bom dia"),
            "sem prefixo",
        ]
    )
    assert count_speaker_lines(text) == 2


def test_guardrail_rejects_massive_truncation() -> None:
    before = " ".join(["palavra"] * 200)
    after = " ".join(["palavra"] * 50)
    ok, reason = asr_fix_output_passes_guardrail(before, after)
    assert not ok
    assert reason is not None
    assert "word_count_ratio" in reason


def test_guardrail_accepts_minor_word_fixes() -> None:
    before = " ".join(["ciprofluxacina"] * 120)
    after = " ".join(["ciprofloxacina"] * 120)
    ok, reason = asr_fix_output_passes_guardrail(before, after)
    assert ok
    assert reason is None


def test_guardrail_rejects_speaker_line_loss() -> None:
    chunk = "um dois tres quatro cinco seis sete oito nove dez"
    before = "\n".join(_speaker_line(i % 2 + 1, chunk) for i in range(20))
    after = "\n".join(_speaker_line(1, chunk) for _ in range(5))
    ok, reason = asr_fix_output_passes_guardrail(
        before,
        after,
        min_word_ratio=0.0,
        min_speaker_line_ratio=0.90,
    )
    assert not ok
    assert reason is not None
    assert "speaker_line_ratio" in reason


def test_build_asr_user_message_wraps_transcript() -> None:
    message = _build_asr_user_message("paciente com dor", preserve_speaker_labels=True)
    assert "Falante 1:" in message or "generic diarization labels" in message
    assert "<<<" in message
    assert "paciente com dor" in message


def test_resolve_asr_fix_guardrail_settings_from_config() -> None:
    settings = resolve_asr_fix_guardrail_settings(
        {"ASR_FIX_MIN_WORD_RATIO": "0.85", "ASR_FIX_MIN_SPEAKER_LINE_RATIO": "0.80"}
    )
    assert settings["min_word_ratio"] == 0.85
    assert settings["min_speaker_line_ratio"] == 0.80


def test_edit_transcript_falls_back_when_guardrail_fails() -> None:
    original = "\n".join(_speaker_line(i % 2 + 1, f"token{i}") for i in range(30))
    truncated = "\n".join(_speaker_line(1, "resumo curto") for _ in range(5))

    def fake_generate(**_kwargs):
        return truncated, truncated

    with patch(
        "app.services.transcript_postprocess.medgemma_generate",
        side_effect=fake_generate,
    ):
        result = edit_transcript(
            original,
            enabled=True,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            timeout=30,
        )

    assert result["text"] == original
    assert result["guardrail"]["rejected"] is True
    assert result["diff"]["guardrail_rejected"] is True
    assert result["skipped"] is False
    assert result.get("error") is None


def test_edit_transcript_keeps_llm_output_when_guardrail_passes() -> None:
    original = "\n".join(_speaker_line(i % 2 + 1, f"token{i}") for i in range(12))
    corrected = original.replace("token0", "tokén0")

    def fake_generate(**_kwargs):
        return corrected, corrected

    with patch(
        "app.services.transcript_postprocess.medgemma_generate",
        side_effect=fake_generate,
    ):
        result = edit_transcript(
            original,
            enabled=True,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            timeout=30,
        )

    assert result["text"] == corrected
    assert result["guardrail"]["rejected"] is False
