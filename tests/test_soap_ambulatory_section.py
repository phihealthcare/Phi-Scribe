from app.services.soap_draft import (
    SOAP_AMBULATORY_STYLE_PLACEHOLDER,
    SOAP_AMBULATORY_STYLE_SECTION_PLACEHOLDER,
    load_soap_ambulatory_style,
    load_soap_prompt,
    load_soap_section_prompt,
)


def test_load_soap_ambulatory_style_full_master_unchanged() -> None:
    style = load_soap_ambulatory_style()
    assert "ESTILO AMBULATORIAL" in style
    assert "Produza o SOAP" in style
    assert "soap.subjetivo" in style


def test_load_soap_ambulatory_style_section_plano_is_scoped() -> None:
    style = load_soap_ambulatory_style(section="plano")
    assert "ESTILO AMBULATORIAL — PLANO" in style
    assert "plano_conduta" in style
    assert "Produza o SOAP" not in style
    assert "soap.subjetivo" not in style
    assert "Em uso:" not in style


def test_load_soap_ambulatory_style_section_subjetivo_includes_chart_rules() -> None:
    style = load_soap_ambulatory_style(section="subjetivo")
    assert "DADOS DO PRONTUÁRIO" in style
    assert "Em uso:" in style
    assert "Produza o SOAP" not in style
    assert "Labs DD/MM/AAAA" not in style


def test_load_soap_ambulatory_style_section_objetivo_includes_labs_format() -> None:
    style = load_soap_ambulatory_style(section="objetivo")
    assert "Labs DD/MM/AAAA" in style
    assert "Produza o SOAP" not in style
    assert "Vem para reavaliação por" not in style


def test_load_soap_section_prompt_plano_excludes_monolithic_ambulatory_phrases() -> None:
    prompt = load_soap_section_prompt("plano", diarization_enabled=False, omit_transcript=True)
    assert SOAP_AMBULATORY_STYLE_SECTION_PLACEHOLDER not in prompt
    assert "Produza o SOAP" not in prompt
    assert "soap.subjetivo" not in prompt
    assert "ESTILO AMBULATORIAL — PLANO" in prompt
    assert "plano_conduta" in prompt
    fmt_idx = prompt.index("JSON obrigatório")
    assert "ESTILO AMBULATORIAL — PLANO" in prompt[:fmt_idx]
    assert prompt.index("ESTILO AMBULATORIAL — PLANO") < fmt_idx


def test_load_soap_section_prompt_injects_style_before_response_format() -> None:
    prompt = load_soap_section_prompt("objetivo", diarization_enabled=False, omit_transcript=True)
    assert SOAP_AMBULATORY_STYLE_SECTION_PLACEHOLDER not in prompt
    assert "ESTILO AMBULATORIAL — OBJETIVO" in prompt
    fmt_idx = prompt.index("JSON obrigatório")
    assert prompt.index("ESTILO AMBULATORIAL — OBJETIVO") < fmt_idx


def test_load_soap_section_prompt_compact_omits_ambulatory_style() -> None:
    verbose = load_soap_section_prompt(
        "subjetivo",
        diarization_enabled=False,
        omit_transcript=True,
        prompt_compact=False,
    )
    compact = load_soap_section_prompt(
        "subjetivo",
        diarization_enabled=False,
        omit_transcript=True,
        prompt_compact=True,
    )
    assert "ESTILO AMBULATORIAL" not in compact
    assert len(compact) < len(verbose)
    assert "JSON obrigatório" in compact
    assert "chief_complaint" in compact


def test_load_soap_prompt_monolithic_still_uses_full_ambulatory_style() -> None:
    prompt = load_soap_prompt(diarization_enabled=False)
    assert SOAP_AMBULATORY_STYLE_PLACEHOLDER not in prompt
    assert SOAP_AMBULATORY_STYLE_SECTION_PLACEHOLDER not in prompt
    assert "Produza o SOAP" in prompt
    assert "soap.subjetivo" in prompt
    assert "Vem para reavaliação por" in prompt
