from app.services.soap_draft import (
    SOAP_AMBULATORY_STYLE_PLACEHOLDER,
    load_soap_ambulatory_style,
    load_soap_prompt,
    load_soap_section_prompt,
)
from app.services.soap_format import format_soap_plain_text


def test_load_soap_ambulatory_style_has_header_and_labs_format() -> None:
    style = load_soap_ambulatory_style()
    assert "ESTILO AMBULATORIAL" in style
    assert "Em uso:" in style
    assert "Labs DD/MM/AAAA" in style
    assert "IRA vs DRC ??" in style


def test_load_soap_prompt_injects_ambulatory_style_for_full_soap() -> None:
    prompt = load_soap_prompt(diarization_enabled=False)
    assert SOAP_AMBULATORY_STYLE_PLACEHOLDER not in prompt
    assert "ESTILO AMBULATORIAL" in prompt
    assert "Vem para reavaliação por" in prompt


def test_load_soap_section_prompt_appends_ambulatory_style() -> None:
    prompt = load_soap_section_prompt("objetivo", diarization_enabled=False, omit_transcript=True)
    assert "ESTILO AMBULATORIAL — OBJETIVO" in prompt
    assert "Ecografia" in prompt
    assert "Produza o SOAP" not in prompt


def test_format_soap_plain_text_ambulatory_layout() -> None:
    document = {
        "soap": {
            "subjetivo": "67 anos.\n\n# HAS\n\nVem para reavaliação por dor.",
            "objetivo": "Labs 12/05/2026: creat 1,21",
            "avaliacao": "IRA vs DRC ??",
            "plano": "Solicito labs.\nReforço ingesta hídrica.",
        }
    }
    text = format_soap_plain_text(document)
    assert text.startswith("67 anos.")
    assert "Objetivo\n\nLabs" in text
    assert "Avaliação\n\nIRA vs DRC ??" in text
    assert "Plano\n\nSolicito labs." in text
