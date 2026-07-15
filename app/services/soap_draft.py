from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from app.services.llm_client import medgemma_generate, resolve_llm_settings, strip_markdown_fences
from app.services.pipeline_steps import prompt_compact_for_config
from app.services.prompt_format import compact_prompt_text
from app.services.pipeline_steps import (
    SOAP_LLM_STEP_IDS_SPLIT_WITH_MERGE,
    TRANSCRIBE_05_LLM_SOAP,
    TRANSCRIBE_05E_MERGE_SOAP,
    TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO,
    TRANSCRIBE_05B_LLM_SOAP_OBJETIVO,
    TRANSCRIBE_05C_LLM_SOAP_AVALIACAO,
    TRANSCRIBE_05D_LLM_SOAP_PLANO,
    soap_enabled_for_config,
)
from app.services.soap_validation import (
    normalize_monolithic_soap_document,
    EMPTY_AVALIACAO_TEXT,
    EMPTY_OBJETIVO_TEXT,
    EMPTY_PLANO_TEXT,
    EMPTY_SUBJETIVO_TEXT,
    EXPECTED_SOAP_STATUS,
    merge_soap_sections,
    monolithic_document_degraded,
    canonicalize_section_partial,
    normalize_llm_response_document,
    normalize_soap_section_partial,
    strip_coercion_metadata,
    soap_retry_user_appendix,
    soap_section_retry_appendix,
    validate_soap_document,
    validate_soap_section,
)
from app.services.soap_format import format_soap_plain_text

if TYPE_CHECKING:
    from app.services.pipeline_tracker import PipelineTracker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOAP_PROMPTS_DIR = ROOT / "benchmarks" / "prompts"
DEFAULT_SOAP_PROMPT_PATH = DEFAULT_SOAP_PROMPTS_DIR / "soap-draft.md"
SOAP_STYLE_PROMPT_PATH = DEFAULT_SOAP_PROMPTS_DIR / "soap-style-ambulatorio.md"
DEFAULT_SOAP_SYSTEM_PROMPT = (
    "Você redige documentação SOAP clínica em português brasileiro (pt-BR). "
    "Responda EXCLUSIVAMENTE com JSON válido usando somente as chaves pedidas "
    "(subjetivo, objetivo, avaliacao ou plano_conduta + alertas_revisao). "
    "Nunca use chief_complaint, patient_id, physical_exam, assessment, plan ou outras chaves EMR em inglês."
)
SOAP_USER_INSTRUCTIONS_SEPARATOR = "\n\n---\n\n"
SOAP_COMMON_PLACEHOLDER = "{{SOAP_COMMON}}"
SOAP_TRANSCRIPT_MODE_PLACEHOLDER = "{{SOAP_TRANSCRIPT_MODE}}"
SOAP_PRIVACY_PLACEHOLDER = "{{SOAP_PRIVACY}}"
SOAP_AMBULATORY_STYLE_PLACEHOLDER = "{{SOAP_AMBULATORY_STYLE}}"
SOAP_AMBULATORY_STYLE_SECTION_PLACEHOLDER = "{{SOAP_AMBULATORY_STYLE_SECTION}}"
_AMBULATORY_SECTION_IDS = frozenset({"subjetivo", "objetivo", "avaliacao", "plano"})
_AMBULATORY_SOAP_HEADING_RE = re.compile(
    r"^### `(soap\.(?:subjetivo|objetivo|avaliacao|plano))`[^\n]*\n(.*?)(?=^---\s*$|\Z)",
    re.M | re.S,
)
_AMBULATORY_CHART_BLOCK_RE = re.compile(
    r"^### DADOS DO PRONTUÁRIO\n(.*?)(?=^---\s*$)",
    re.M | re.S,
)
_SOAP_KEY_TO_SECTION = {
    "soap.subjetivo": "subjetivo",
    "soap.objetivo": "objetivo",
    "soap.avaliacao": "avaliacao",
    "soap.plano": "plano",
}
_SECTION_AMBULATORY_SCOPE: dict[str, str] = {
    "subjetivo": (
        "## ESTILO AMBULATORIAL — SUBJETIVO\n\n"
        "As regras abaixo aplicam-se APENAS à formatação do texto do campo "
        '`subjetivo` na sua resposta JSON. '
        "NÃO produza objetivo, avaliação, plano nem chaves soap.*."
    ),
    "objetivo": (
        "## ESTILO AMBULATORIAL — OBJETIVO\n\n"
        "As regras abaixo aplicam-se APENAS à formatação do texto do campo "
        '`objetivo` na sua resposta JSON. '
        "NÃO produza subjetivo, avaliação, plano nem chaves soap.*."
    ),
    "avaliacao": (
        "## ESTILO AMBULATORIAL — AVALIAÇÃO\n\n"
        "As regras abaixo aplicam-se APENAS à formatação do texto do campo "
        '`avaliacao` na sua resposta JSON. '
        "NÃO produza subjetivo, objetivo, plano nem chaves soap.*."
    ),
    "plano": (
        "## ESTILO AMBULATORIAL — PLANO\n\n"
        "As regras abaixo aplicam-se APENAS à formatação do texto do campo "
        '`plano_conduta` na sua resposta JSON. '
        "NÃO produza subjetivo, objetivo, avaliação nem chaves soap.*."
    ),
}
_TRANSCRIPT_IN_USER_STUB = (
    "A transcrição completa da consulta está na mensagem do usuário abaixo."
)
_TRANSCRIPT_PLACEHOLDER_KEYS = (
    "TRANSCRICAO_SEGMENTADA",
    "TRANSCRICAO_E_DADOS_OBJETIVOS",
    "TRANSCRICAO_AVALIACAO",
)
_SECTIONS_TRANSCRIPT_IN_USER = frozenset({"subjetivo", "objetivo", "avaliacao"})

_PORTUGUESE_ONLY = ""

_SECTION_USER_INTROS_PLAIN = {
    "subjetivo": (
        'JSON obrigatório: {"subjetivo":"...","alertas_revisao":[]}. '
        "Extraia relato do paciente da transcrição (queixa, HDA, temporalidade, negações, medicamentos). "
        "Pt-BR. Sem chaves EMR em inglês."
    ),
    "objetivo": (
        'JSON obrigatório: {"objetivo":"...","alertas_revisao":[]}. '
        "Extraia laudos/exames citados pelo profissional e exame físico verbalizado. Pt-BR. "
        'Sem chaves physical_exam, labs_and_imaging. Se vazio: "Sem dados objetivos suficientes na transcrição."'
    ),
    "avaliacao": (
        'JSON obrigatório: {"avaliacao":"...","alertas_revisao":[]}. '
        "Hipóteses do profissional (investigação, vs, ??). Uma linha por item. Pt-BR. "
        "Sem assessment, patient_concerns, plan."
    ),
    "plano": (
        'JSON obrigatório: {"plano_conduta":"...","alertas_revisao":[]}. '
        "Condutas verbalizadas pelo profissional, uma por linha. Pt-BR. Sem chave plan."
    ),
}

_SECTION_USER_INTROS = {
    "subjetivo": (
        "Monte o campo subjetivo no estilo ambulatorial: cabeçalho (idade se constar, linhas # antecedentes, "
        "Em uso: com medicamentos) somente se constar na transcrição ou em DADOS DO PRONTUÁRIO; "
        "não inclua nomes próprios de participantes. "
        "depois narrativa iniciando com Vem para reavaliação por... ou Vem por.... "
        'Retorne SOMENTE JSON com "subjetivo" e "alertas_revisao". '
        "NÃO use summary, key_concerns ou outras chaves."
    ),
    "objetivo": (
        "Extraia dados objetivos no estilo ambulatorial: exame físico (se houver), "
        "Labs DD/MM/AAAA: com // entre resultados, ECG DD/MM/AAAA:, Ecografia região DD/MM/AAAA:. "
        'Retorne JSON com objetivo como texto. '
        'Se não houver dados objetivos, use: "Sem dados objetivos suficientes na transcrição."'
    ),
    "avaliacao": (
        "Extraia hipóteses formuladas pelo médico em formato telegráfico (uma linha por item; "
        "preserve vs e ??). "
        'Retorne JSON com avaliacao como texto. NÃO use summary, key_concerns ou recommendations.'
    ),
    "plano": (
        "Extraia condutas verbalizadas pelo profissional, uma por linha (Solicito, Reforço, Oriento, "
        "Reavaliação com exames, Orientações gerais). "
        'Retorne JSON com plano_conduta como STRING (linhas separadas por \\n) e alertas_revisao.'
    ),
}

_CONDUTA_LINE_RE = re.compile(
    r"(vou passar|solicito|eletrocardiograma|exames?|enzimas?|reavali|oriento|"
    r"prescrevo|encaminho|libero|plano de|conduta|realizar)",
    re.I,
)


@dataclass(frozen=True)
class SoapSectionSpec:
    section_id: str
    prompt_filename: str
    tracker_step_id: str
    user_intro: str
    embed_context_in_system: bool = False


SOAP_SECTIONS: tuple[SoapSectionSpec, ...] = (
    SoapSectionSpec(
        "subjetivo",
        "soap-subjetivo.md",
        TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO,
        _SECTION_USER_INTROS["subjetivo"],
        embed_context_in_system=True,
    ),
    SoapSectionSpec(
        "objetivo",
        "soap-objetivo.md",
        TRANSCRIBE_05B_LLM_SOAP_OBJETIVO,
        _SECTION_USER_INTROS["objetivo"],
        embed_context_in_system=True,
    ),
    SoapSectionSpec(
        "avaliacao",
        "soap-avaliacao.md",
        TRANSCRIBE_05C_LLM_SOAP_AVALIACAO,
        _SECTION_USER_INTROS["avaliacao"],
        embed_context_in_system=True,
    ),
    SoapSectionSpec(
        "plano",
        "soap-plano.md",
        TRANSCRIBE_05D_LLM_SOAP_PLANO,
        _SECTION_USER_INTROS["plano"],
        embed_context_in_system=True,
    ),
)


def _resolve_prompts_dir(prompts_dir: Path | None = None) -> Path:
    return (prompts_dir or DEFAULT_SOAP_PROMPTS_DIR).resolve()


def resolve_soap_system_prompt(override: str | None = None) -> str:
    """Short system role sent to the LLM; detailed SOAP rules go in the user prompt."""
    if override and str(override).strip():
        return str(override).strip()
    return DEFAULT_SOAP_SYSTEM_PROMPT


def compose_soap_user_prompt(
    instructions: str,
    user_message: str,
    *,
    prompt_compact: bool = False,
) -> str:
    """Prepend soap-draft / section instructions before transcript and task text."""
    instructions_text = instructions.strip()
    user_text = user_message.strip()
    if not instructions_text:
        return user_text
    if not user_text:
        return instructions_text
    separator = "\n\n" if prompt_compact else SOAP_USER_INSTRUCTIONS_SEPARATOR
    return f"{instructions_text}{separator}{user_text}"


def _finalize_soap_instructions(text: str, *, prompt_compact: bool) -> str:
    if not prompt_compact:
        return text.strip()
    return compact_prompt_text(text)


def _transcript_mode_filename(
    *,
    diarization_enabled: bool,
    postprocess_applied: bool,
) -> str:
    if not diarization_enabled:
        return "soap-transcript-mode-plain.md"
    if postprocess_applied:
        return "soap-transcript-mode-diarized.md"
    return "soap-transcript-mode-falante.md"


def load_soap_transcript_mode(
    *,
    prompts_dir: Path | None = None,
    diarization_enabled: bool = False,
    postprocess_applied: bool = False,
) -> str:
    filename = _transcript_mode_filename(
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
    )
    path = _resolve_prompts_dir(prompts_dir) / filename
    if not path.is_file():
        raise FileNotFoundError(f"SOAP transcript mode prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_soap_privacy(*, prompts_dir: Path | None = None) -> str:
    path = _resolve_prompts_dir(prompts_dir) / "soap-privacy.md"
    if not path.is_file():
        raise FileNotFoundError(f"SOAP privacy prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _resolve_soap_prompt_template(
    template: str,
    *,
    prompts_dir: Path | None,
    diarization_enabled: bool,
    postprocess_applied: bool,
    prompt_compact: bool = False,
) -> str:
    text = template.strip()
    mode = load_soap_transcript_mode(
        prompts_dir=prompts_dir,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
    )
    privacy = load_soap_privacy(prompts_dir=prompts_dir)
    if prompt_compact:
        mode = compact_prompt_text(mode)
        privacy = compact_prompt_text(privacy)

    has_mode_placeholder = SOAP_TRANSCRIPT_MODE_PLACEHOLDER in text
    has_privacy_placeholder = SOAP_PRIVACY_PLACEHOLDER in text

    if has_mode_placeholder:
        text = text.replace(SOAP_TRANSCRIPT_MODE_PLACEHOLDER, mode)
    if has_privacy_placeholder:
        text = text.replace(SOAP_PRIVACY_PLACEHOLDER, privacy)

    prefix_parts: list[str] = []
    if not has_mode_placeholder:
        prefix_parts.append(mode)
    if not has_privacy_placeholder:
        prefix_parts.append(privacy)
    if prefix_parts:
        block_sep = "\n\n" if prompt_compact else "\n\n---\n\n"
        text = block_sep.join(prefix_parts) + block_sep + text
    return text


def _section_user_intro(
    section_id: str,
    *,
    diarization_enabled: bool,
) -> str:
    if diarization_enabled:
        return _SECTION_USER_INTROS[section_id]
    return _SECTION_USER_INTROS_PLAIN.get(
        section_id,
        _SECTION_USER_INTROS[section_id],
    )


def _transcript_mode_user_intro(
    *,
    diarization_enabled: bool,
    postprocess_applied: bool,
) -> str:
    if diarization_enabled:
        if postprocess_applied:
            return (
                "A transcrição abaixo foi diarizada com rótulos Médico: / Paciente: "
                "após pós-processamento."
            )
        return (
            "A transcrição abaixo foi diarizada e pode usar rótulos Falante 1: / Falante 2:."
        )
    return (
        "A transcrição abaixo é um diálogo contínuo entre profissional e paciente, "
        "SEM rótulos Médico:/Paciente:. Leia do início ao fim antes de redigir; "
        "priorize motivo da consulta, HDA, exames discutidos e conduta sobre conversa de encerramento. "
        "Separe Subjetivo (relato do paciente) de Avaliação/Plano (fala do profissional) pelos sinais "
        "linguísticos das instruções."
    )


def load_soap_common(
    *,
    prompts_dir: Path | None = None,
    diarization_enabled: bool = False,
    postprocess_applied: bool = False,
    prompt_compact: bool = False,
) -> str:
    path = _resolve_prompts_dir(prompts_dir) / "soap-common.md"
    if not path.is_file():
        raise FileNotFoundError(f"SOAP common prompt not found: {path}")
    template = path.read_text(encoding="utf-8").strip()
    return _resolve_soap_prompt_template(
        template,
        prompts_dir=prompts_dir,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
        prompt_compact=prompt_compact,
    )


def _parse_ambulatory_soap_sections(master: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for match in _AMBULATORY_SOAP_HEADING_RE.finditer(master):
        section_id = _SOAP_KEY_TO_SECTION.get(match.group(1))
        if section_id:
            sections[section_id] = match.group(2).strip()
    return sections


def _extract_ambulatory_chart_block(master: str) -> str:
    match = _AMBULATORY_CHART_BLOCK_RE.search(master)
    return match.group(1).strip() if match else ""


def _extract_ambulatory_example(master: str, section: str) -> str:
    if section == "avaliacao":
        match = re.search(r"\*\*avaliacao\*\*:\s*`([^`]+)`", master, re.I)
        if match:
            return f"Exemplo: `{match.group(1).strip()}`"
        return ""
    match = re.search(
        rf"\*\*{section}\*\*[^`]*\n\n```\n(.*?)```",
        master,
        re.I | re.S,
    )
    if not match:
        return ""
    return f"Exemplo de referência:\n\n```\n{match.group(1).strip()}\n```"


def _build_section_ambulatory_style(section: str, master: str) -> str:
    parsed = _parse_ambulatory_soap_sections(master)
    parts: list[str] = [_SECTION_AMBULATORY_SCOPE[section]]
    if section == "subjetivo":
        chart = _extract_ambulatory_chart_block(master)
        if chart:
            parts.append(f"### DADOS DO PRONTUÁRIO\n\n{chart}")
    body = parsed.get(section, "")
    if body:
        parts.append(body)
    example = _extract_ambulatory_example(master, section)
    if example:
        parts.append(example)
    return "\n\n".join(part.strip() for part in parts if part.strip())


def load_soap_ambulatory_style(
    *,
    prompts_dir: Path | None = None,
    section: str | None = None,
    prompt_compact: bool = False,
) -> str:
    path = _resolve_prompts_dir(prompts_dir) / SOAP_STYLE_PROMPT_PATH.name
    if not path.is_file():
        return ""
    master = path.read_text(encoding="utf-8").strip()
    if section is None:
        style = master
    else:
        if section not in _AMBULATORY_SECTION_IDS:
            raise ValueError(f"Unknown SOAP ambulatory section: {section}")
        style = _build_section_ambulatory_style(section, master)
    if prompt_compact and style:
        style = compact_prompt_text(style)
    return style


def _inject_ambulatory_style(
    prompt: str,
    *,
    prompts_dir: Path | None = None,
    prompt_compact: bool = False,
    section: str | None = None,
) -> str:
    if section:
        style = load_soap_ambulatory_style(
            prompts_dir=prompts_dir,
            section=section,
            prompt_compact=prompt_compact,
        )
        if not style:
            return prompt.replace(SOAP_AMBULATORY_STYLE_SECTION_PLACEHOLDER, "").strip()
        if SOAP_AMBULATORY_STYLE_SECTION_PLACEHOLDER in prompt:
            return prompt.replace(SOAP_AMBULATORY_STYLE_SECTION_PLACEHOLDER, style)
        if "FORMATO DA RESPOSTA" in prompt:
            return prompt.replace("FORMATO DA RESPOSTA", f"{style}\n\nFORMATO DA RESPOSTA", 1)
        if "## JSON obrigatório" in prompt:
            return prompt.replace("## JSON obrigatório", f"{style}\n\n## JSON obrigatório", 1)
        return f"{prompt.strip()}\n\n{style}"

    style = load_soap_ambulatory_style(prompts_dir=prompts_dir)
    if prompt_compact and style:
        style = compact_prompt_text(style)
    if not style:
        return prompt.strip()
    if SOAP_AMBULATORY_STYLE_PLACEHOLDER in prompt:
        return prompt.replace(SOAP_AMBULATORY_STYLE_PLACEHOLDER, style)
    if style in prompt:
        return prompt.strip()
    return f"{prompt.strip()}\n\n{style}"


def resolve_patient_chart_context(config: Mapping[str, Any] | None = None) -> str:
    if not config:
        return ""
    direct = str(config.get("SOAP_PATIENT_CHART_CONTEXT") or "").strip()
    if direct:
        return direct
    file_raw = config.get("SOAP_PATIENT_CHART_FILE")
    if not file_raw:
        return ""
    path = Path(str(file_raw))
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _format_patient_chart_block(
    patient_chart_context: str,
    *,
    prompt_compact: bool = False,
) -> str:
    chart = patient_chart_context.strip()
    if not chart:
        return ""
    if prompt_compact:
        return f"DADOS DO PRONTUÁRIO:\n{chart}\n\n"
    return (
        "DADOS DO PRONTUÁRIO (use somente estes; não invente além):\n"
        f"<<<\n{chart}\n>>>\n\n"
    )


def load_soap_section_prompt(
    section: str,
    *,
    prompts_dir: Path | None = None,
    placeholders: Mapping[str, str] | None = None,
    omit_transcript: bool = False,
    diarization_enabled: bool = False,
    postprocess_applied: bool = False,
    prompt_compact: bool = False,
) -> str:
    spec = next((item for item in SOAP_SECTIONS if item.section_id == section), None)
    if spec is None:
        raise ValueError(f"Unknown SOAP section: {section}")
    path = _resolve_prompts_dir(prompts_dir) / spec.prompt_filename
    if not path.is_file():
        raise FileNotFoundError(f"SOAP section prompt not found: {path}")
    template = path.read_text(encoding="utf-8").strip()
    if prompt_compact:
        privacy = compact_prompt_text(load_soap_privacy(prompts_dir=prompts_dir))
        if privacy:
            template = f"{privacy}\n\n{template}"
    elif SOAP_COMMON_PLACEHOLDER in template:
        common = load_soap_common(
            prompts_dir=prompts_dir,
            diarization_enabled=diarization_enabled,
            postprocess_applied=postprocess_applied,
            prompt_compact=prompt_compact,
        )
        template = template.replace(SOAP_COMMON_PLACEHOLDER, common)
    else:
        template = _resolve_soap_prompt_template(
            template,
            prompts_dir=prompts_dir,
            diarization_enabled=diarization_enabled,
            postprocess_applied=postprocess_applied,
            prompt_compact=prompt_compact,
        )
    resolved_placeholders = dict(placeholders or {})
    if omit_transcript:
        for key in _TRANSCRIPT_PLACEHOLDER_KEYS:
            token = f"{{{{{key}}}}}"
            if token in template:
                template = template.replace(token, _TRANSCRIPT_IN_USER_STUB)
            resolved_placeholders.pop(key, None)
    for key, value in resolved_placeholders.items():
        token = f"{{{{{key}}}}}"
        if token in template:
            template = template.replace(token, value)
    if not prompt_compact:
        template = _inject_ambulatory_style(
            template,
            prompts_dir=prompts_dir,
            prompt_compact=prompt_compact,
            section=section,
        )
    return _finalize_soap_instructions(template, prompt_compact=prompt_compact)


def _partial_section_text(partial: dict[str, Any] | None, key: str) -> str:
    if not partial:
        return ""
    value = partial.get(key)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        if key == "subjetivo":
            parts: list[str] = []
            queixa = value.get("queixa_principal")
            if isinstance(queixa, str) and queixa.strip():
                parts.append(queixa.strip())
            historia = value.get("historia_da_doenca_atual")
            if isinstance(historia, str) and historia.strip():
                parts.append(historia.strip())
            timeline = value.get("linha_do_tempo_sintomas")
            if isinstance(timeline, list):
                for item in timeline:
                    if isinstance(item, str) and item.strip():
                        parts.append(item.strip())
                    elif isinstance(item, dict):
                        for field in ("evento", "descricao", "texto"):
                            text = item.get(field)
                            if isinstance(text, str) and text.strip():
                                parts.append(text.strip())
                                break
            return "\n\n".join(parts)
        if key == "avaliacao":
            for field in ("hipoteses", "problemas", "impressao", "texto"):
                text = value.get(field)
                if isinstance(text, str) and text.strip():
                    return text.strip()
                if isinstance(text, list):
                    lines = [str(item).strip() for item in text if str(item).strip()]
                    if lines:
                        return "\n".join(lines)
            return ""
    return ""


def _extract_conduta_transcript(segmented_transcript: str, *, tail_lines: int = 30) -> str:
    lines = [line for line in segmented_transcript.splitlines() if line.strip()]
    if not lines:
        return segmented_transcript.strip()

    hit_indices = [index for index, line in enumerate(lines) if _CONDUTA_LINE_RE.search(line)]
    if hit_indices:
        start = max(0, hit_indices[0] - 3)
        return "\n".join(lines[start:])

    return "\n".join(lines[-tail_lines:])


def _section_prompt_placeholders(
    spec: SoapSectionSpec,
    *,
    segmented_transcript: str,
    prior_partials: Mapping[str, dict[str, Any]],
    diarization_enabled: bool,
    postprocess_applied: bool,
) -> dict[str, str]:
    transcript_block = _format_transcript_for_prompt(
        segmented_transcript,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
    )
    if spec.section_id == "subjetivo":
        return {"TRANSCRICAO_SEGMENTADA": transcript_block}
    if spec.section_id == "objetivo":
        return {"TRANSCRICAO_E_DADOS_OBJETIVOS": transcript_block}
    if spec.section_id == "avaliacao":
        return {
            "SUBJETIVO": _partial_section_text(prior_partials.get("subjetivo"), "subjetivo"),
            "OBJETIVO": _partial_section_text(prior_partials.get("objetivo"), "objetivo"),
            "TRANSCRICAO_AVALIACAO": transcript_block,
        }
    if spec.section_id == "plano":
        conduta_transcript = _extract_conduta_transcript(segmented_transcript)
        return {
            "SUBJETIVO": _partial_section_text(prior_partials.get("subjetivo"), "subjetivo"),
            "OBJETIVO": _partial_section_text(prior_partials.get("objetivo"), "objetivo"),
            "AVALIACAO": _partial_section_text(prior_partials.get("avaliacao"), "avaliacao"),
            "TRANSCRICAO_CONDUTA": _format_transcript_for_prompt(
                conduta_transcript,
                diarization_enabled=diarization_enabled,
                postprocess_applied=postprocess_applied,
            ),
        }
    return {}


def _format_transcript_for_prompt(
    segmented_transcript: str,
    *,
    diarization_enabled: bool,
    postprocess_applied: bool,
) -> str:
    parts: list[str] = []
    if diarization_enabled:
        if postprocess_applied:
            parts.append(
                "Nota: transcrição diarizada com rótulos Médico: / Paciente:."
            )
        else:
            parts.append(
                "Nota: transcrição diarizada com rótulos Falante 1: / Falante 2:."
            )
        parts.append("")
    else:
        parts.append("Nota: diálogo contínuo sem rótulos de falante.")
        parts.append("")
    parts.append(segmented_transcript.strip())
    return "\n".join(parts)


def load_soap_prompt(
    *,
    prompt_path: Path | None = None,
    prompts_dir: Path | None = None,
    diarization_enabled: bool = False,
    postprocess_applied: bool = False,
    prompt_compact: bool = False,
) -> str:
    path = (prompt_path or DEFAULT_SOAP_PROMPT_PATH).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SOAP prompt not found: {path}")
    template = path.read_text(encoding="utf-8")
    template = _resolve_soap_prompt_template(
        template,
        prompts_dir=prompts_dir or path.parent,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
        prompt_compact=prompt_compact,
    )
    template = _inject_ambulatory_style(
        template,
        prompts_dir=prompts_dir or path.parent,
        prompt_compact=prompt_compact,
    )
    return _finalize_soap_instructions(template, prompt_compact=prompt_compact)


def skip_soap_pipeline_steps(
    tracker: PipelineTracker | None,
    *,
    reason: str,
    split_enabled: bool = True,
) -> None:
    if not tracker:
        return
    if split_enabled:
        for step_id in SOAP_LLM_STEP_IDS_SPLIT_WITH_MERGE:
            tracker.skip(step_id, reason=reason)
    else:
        tracker.skip(TRANSCRIBE_05_LLM_SOAP, reason=reason)


def _format_timestamp(ms: int) -> str:
    total_seconds, milliseconds = divmod(max(0, int(ms)), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def resolve_soap_input_transcript(
    text: str,
    *,
    segments: list[dict[str, Any]] | None = None,
    diarization_enabled: bool = False,
    postprocess_applied: bool = False,
) -> str:
    """Use postprocessed transcript text (Falante or Médico/Paciente labels, or plain ASR)."""
    return text.strip()


def format_segmented_transcript(
    text: str,
    *,
    segments: list[dict[str, Any]] | None = None,
) -> str:
    if not segments:
        return text.strip()

    lines: list[str] = []
    for segment in segments:
        segment_text = str(segment.get("text", "")).strip()
        if not segment_text:
            continue
        label = str(
            segment.get("speaker_label")
            or segment.get("speaker_id")
            or ""
        ).strip()
        start_ms = segment.get("start_ms")
        if start_ms is not None:
            timestamp = _format_timestamp(int(start_ms))
            prefix = f"[{timestamp}]"
            if label:
                prefix = f"{prefix} {label}:"
            lines.append(f"{prefix} {segment_text}")
        elif label:
            lines.append(f"{label}: {segment_text}")
        else:
            lines.append(segment_text)

    if lines:
        return "\n".join(lines)
    return text.strip()


def _build_user_message(
    *,
    segmented_transcript: str,
    diarization_enabled: bool = False,
    postprocess_applied: bool = False,
    section_intro: str | None = None,
    patient_chart_context: str = "",
    prompt_compact: bool = False,
) -> str:
    chart_block = _format_patient_chart_block(
        patient_chart_context,
        prompt_compact=prompt_compact,
    )
    transcript = segmented_transcript.strip()

    if prompt_compact:
        parts: list[str] = []
        if chart_block:
            parts.append(chart_block.rstrip())
        task = section_intro or (
            "Produza o SOAP conforme as instruções acima "
            "(estilo ambulatorial; use DADOS DO PRONTUÁRIO quando fornecidos)."
        )
        parts.append(task)
        if transcript:
            parts.append(transcript)
        return "\n\n".join(part for part in parts if part)

    parts = []
    if chart_block:
        parts.append(chart_block.rstrip())
        parts.append("")
    parts.append(
        _transcript_mode_user_intro(
            diarization_enabled=diarization_enabled,
            postprocess_applied=postprocess_applied,
        )
    )
    parts.append(
        "Não inclua nomes próprios de participantes da consulta no rascunho SOAP "
        "(paciente, profissional, familiares, legendas de áudio, etc.)."
    )
    parts.append("")

    section_intro_text = section_intro
    if section_intro_text:
        parts.append(section_intro_text)
    else:
        parts.append(
            "Analise a transcrição abaixo e produza o rascunho SOAP no estilo ambulatorial "
            "(cabeçalho com idade, # antecedentes e Em uso: em soap.subjetivo quando houver dados; "
            "Labs/ECG/Ecografia datados em soap.objetivo; avaliação telegráfica; plano uma conduta por linha). "
            "Use DADOS DO PRONTUÁRIO quando fornecidos. Obedeça integralmente às instruções acima."
        )
    parts.extend(
        [
            "",
            "TRANSCRIÇÃO:",
            "<<<",
            transcript,
            ">>>",
            "FIM DA TRANSCRIÇÃO.",
        ]
    )
    return "\n".join(parts)


def _parse_soap_json(
    raw: str,
    *,
    monolithic: bool = True,
    transcript: str = "",
) -> dict[str, Any] | None:
    cleaned = strip_markdown_fences(raw.strip())
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None

    parsed = normalize_llm_response_document(parsed)

    if monolithic:
        return normalize_monolithic_soap_document(parsed, transcript=transcript)
    return parsed


def _generate_soap_section(
    spec: SoapSectionSpec,
    *,
    segmented_transcript: str,
    diarization_enabled: bool,
    postprocess_applied: bool,
    prior_partials: Mapping[str, dict[str, Any]] | None = None,
    patient_chart_context: str = "",
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    prompts_dir: Path,
    tracker: PipelineTracker | None,
    timeout: int,
    max_retries: int,
    prompt_compact: bool = False,
) -> dict[str, Any]:
    placeholders = _section_prompt_placeholders(
        spec,
        segmented_transcript=segmented_transcript,
        prior_partials=prior_partials or {},
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
    )
    transcript_in_user = spec.section_id in _SECTIONS_TRANSCRIPT_IN_USER
    section_intro = _section_user_intro(
        spec.section_id,
        diarization_enabled=diarization_enabled,
    )
    instructions = load_soap_section_prompt(
        spec.section_id,
        prompts_dir=prompts_dir,
        placeholders=placeholders,
        omit_transcript=transcript_in_user,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
        prompt_compact=prompt_compact,
    )
    if spec.embed_context_in_system:
        if transcript_in_user:
            task_message = _build_user_message(
                segmented_transcript=segmented_transcript,
                diarization_enabled=diarization_enabled,
                postprocess_applied=postprocess_applied,
                section_intro=section_intro,
                patient_chart_context=patient_chart_context,
                prompt_compact=prompt_compact,
            )
        else:
            chart_block = _format_patient_chart_block(
                patient_chart_context,
                prompt_compact=prompt_compact,
            )
            task_message = f"{chart_block}{section_intro}" if chart_block else section_intro
    else:
        task_message = _build_user_message(
            segmented_transcript=segmented_transcript,
            diarization_enabled=diarization_enabled,
            postprocess_applied=postprocess_applied,
            section_intro=section_intro,
            patient_chart_context=patient_chart_context,
            prompt_compact=prompt_compact,
        )
    user_message = compose_soap_user_prompt(
        instructions,
        task_message,
        prompt_compact=prompt_compact,
    )
    llm_system_prompt = resolve_soap_system_prompt()
    prompt_path = (_resolve_prompts_dir(prompts_dir) / spec.prompt_filename).resolve()

    validation_errors: list[str] = []
    raw: str | None = None
    llm_raw: str | None = None
    partial: dict[str, Any] | None = None
    schema_coerced = False
    attempts = max(0, int(max_retries)) + 1

    for attempt in range(attempts):
        attempt_prompt = user_message
        if attempt > 0 and validation_errors:
            attempt_prompt = (
                f"{user_message}\n\n{soap_section_retry_appendix(
                    spec.section_id,
                    validation_errors,
                    transcript=segmented_transcript if spec.section_id == "subjetivo" else "",
                )}"
            )

        raw, llm_raw = medgemma_generate(
            prompt=attempt_prompt,
            system_prompt=llm_system_prompt,
            model=model,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            temperature=0,
            force_json=True,
            timeout=timeout,
            return_raw=True,
            tracker=tracker,
            tracker_step_id=spec.tracker_step_id,
            tracker_record_step=attempt == 0,
            tracker_request_meta={
                "prompt_path": str(prompt_path),
                "soap_section": spec.section_id,
                "diarization_enabled": diarization_enabled,
                "postprocess_applied": postprocess_applied,
                "prompt_compact": prompt_compact,
                "attempt": attempt + 1,
                "max_attempts": attempts,
            },
        )
        partial = _parse_soap_json(raw, monolithic=False)
        if partial is None:
            validation_errors = ["resposta não é JSON válido"]
            if tracker and attempt == attempts - 1:
                tracker.amend(
                    spec.tracker_step_id,
                    response={"raw": raw, "attempt": attempt + 1},
                    error="invalid_json_response",
                )
            continue

        partial = normalize_soap_section_partial(
            spec.section_id,
            partial,
            transcript=segmented_transcript if spec.section_id == "subjetivo" else "",
        )
        schema_coerced = bool(partial.get("_schema_coerced"))

        ok, validation_errors = validate_soap_section(
            spec.section_id,
            partial,
            transcript=segmented_transcript if spec.section_id == "subjetivo" else "",
        )
        partial = strip_coercion_metadata(partial)
        partial = canonicalize_section_partial(spec.section_id, partial)
        if ok:
            if tracker:
                amend_response: dict[str, Any] = {
                    "partial": partial,
                    "attempt": attempt + 1,
                }
                if raw is not None:
                    amend_response["raw"] = raw
                    amend_response["text"] = strip_markdown_fences(str(raw).strip())
                tracker.amend(
                    spec.tracker_step_id,
                    response=amend_response,
                    error=None,
                )
            break

        if tracker:
            tracker.amend(
                spec.tracker_step_id,
                response={"partial": partial, "attempt": attempt + 1},
                error="; ".join(validation_errors),
            )

    return {
        "section_id": spec.section_id,
        "prompt_path": str(prompt_path),
        "raw": raw,
        "llm_raw": llm_raw,
        "partial": partial,
        "schema_coerced": schema_coerced if partial is not None else False,
        "validation_errors": validation_errors if partial is None or validation_errors else None,
    }


def _generate_soap_split(
    *,
    segmented_transcript: str,
    diarization_enabled: bool,
    postprocess_applied: bool,
    patient_chart_context: str = "",
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    prompts_dir: Path,
    tracker: PipelineTracker | None,
    timeout: int,
    max_retries: int,
    prompt_compact: bool = False,
) -> dict[str, Any]:
    section_results: dict[str, dict[str, Any]] = {}
    partials: dict[str, dict[str, Any]] = {}
    coerced_sections: set[str] = set()

    for spec in SOAP_SECTIONS:
        section_result = _generate_soap_section(
            spec,
            segmented_transcript=segmented_transcript,
            diarization_enabled=diarization_enabled,
            postprocess_applied=postprocess_applied,
            prior_partials=partials,
            patient_chart_context=patient_chart_context,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            prompts_dir=prompts_dir,
            tracker=tracker,
            timeout=timeout,
            max_retries=max_retries,
            prompt_compact=prompt_compact,
        )
        section_results[spec.section_id] = section_result
        partial = section_result.get("partial")
        if partial is None:
            if tracker:
                tracker.skip(
                    TRANSCRIBE_05E_MERGE_SOAP,
                    reason=f"failed_at_{spec.section_id}",
                )
            return {
                "document": None,
                "raw": section_result.get("raw"),
                "llm_raw": section_result.get("llm_raw"),
                "validation_errors": section_result.get("validation_errors") or ["invalid_json_response"],
                "sections": section_results,
                "failed_section": spec.section_id,
            }
        if section_result.get("validation_errors"):
            if tracker:
                tracker.skip(
                    TRANSCRIBE_05E_MERGE_SOAP,
                    reason=f"failed_at_{spec.section_id}",
                )
            return {
                "document": None,
                "raw": section_result.get("raw"),
                "llm_raw": section_result.get("llm_raw"),
                "validation_errors": section_result["validation_errors"],
                "sections": section_results,
                "failed_section": spec.section_id,
            }
        if section_result.get("schema_coerced"):
            coerced_sections.add(spec.section_id)
        partials[spec.section_id] = partial

    document = merge_soap_sections(
        subjetivo=partials["subjetivo"],
        objetivo=partials["objetivo"],
        avaliacao=partials["avaliacao"],
        plano=partials["plano"],
    )
    ok, validation_errors = validate_soap_document(
        document,
        transcript=segmented_transcript,
        relaxed_sections=frozenset(coerced_sections),
    )
    if tracker:
        tracker.record(
            TRANSCRIBE_05E_MERGE_SOAP,
            request={"merged_from": list(partials.keys())},
            response={"document": document, "validation_ok": ok},
            error="; ".join(validation_errors) if not ok else None,
        )
    if not ok:
        return {
            "document": document,
            "raw": section_results["plano"].get("raw"),
            "llm_raw": section_results["plano"].get("llm_raw"),
            "validation_errors": validation_errors,
            "sections": section_results,
            "failed_section": "merged",
        }

    return {
        "document": document,
        "raw": section_results["plano"].get("raw"),
        "llm_raw": section_results["plano"].get("llm_raw"),
        "validation_errors": None,
        "sections": section_results,
        "failed_section": None,
    }


def _generate_soap_monolithic(
    *,
    segmented_transcript: str,
    diarization_enabled: bool,
    postprocess_applied: bool,
    patient_chart_context: str = "",
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    prompt_path: Path,
    system_prompt: str | None,
    tracker: PipelineTracker | None,
    timeout: int,
    max_retries: int,
    prompt_compact: bool = False,
) -> dict[str, Any]:
    resolved_prompt_path = prompt_path.resolve()
    instructions = system_prompt or load_soap_prompt(
        prompt_path=prompt_path,
        prompts_dir=prompt_path.parent,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
        prompt_compact=prompt_compact,
    )
    task_message = _build_user_message(
        segmented_transcript=segmented_transcript,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
        patient_chart_context=patient_chart_context,
        prompt_compact=prompt_compact,
    )
    user_message = compose_soap_user_prompt(
        instructions,
        task_message,
        prompt_compact=prompt_compact,
    )
    llm_system_prompt = resolve_soap_system_prompt()
    validation_errors: list[str] = []
    raw: str | None = None
    llm_raw: str | None = None
    document: dict[str, Any] | None = None
    attempts = max(0, int(max_retries)) + 1

    for attempt in range(attempts):
        attempt_prompt = user_message
        if attempt > 0 and validation_errors:
            attempt_prompt = f"{user_message}\n\n{soap_retry_user_appendix(validation_errors)}"

        raw, llm_raw = medgemma_generate(
            prompt=attempt_prompt,
            system_prompt=llm_system_prompt,
            model=model,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            temperature=0,
            force_json=True,
            timeout=timeout,
            return_raw=True,
            tracker=tracker,
            tracker_step_id=TRANSCRIBE_05_LLM_SOAP,
            tracker_record_step=attempt == 0,
            tracker_request_meta={
                "prompt_path": str(resolved_prompt_path),
                "diarization_enabled": diarization_enabled,
                "postprocess_applied": postprocess_applied,
                "prompt_compact": prompt_compact,
                "attempt": attempt + 1,
                "max_attempts": attempts,
            },
        )
        document = _parse_soap_json(raw, transcript=segmented_transcript)
        if document is None:
            validation_errors = ["resposta não é JSON válido"]
            if tracker and attempt == attempts - 1:
                tracker.amend(
                    TRANSCRIBE_05_LLM_SOAP,
                    response={"raw": raw, "attempt": attempt + 1},
                    error="invalid_json_response",
                )
            continue

        coerced_sections = frozenset(
            section
            for section in ("subjetivo", "objetivo", "avaliacao", "plano")
            if document.get("soap", {}).get(section)
            in {
                EMPTY_SUBJETIVO_TEXT,
                EMPTY_OBJETIVO_TEXT,
                EMPTY_AVALIACAO_TEXT,
                EMPTY_PLANO_TEXT,
            }
        )
        ok, validation_errors = validate_soap_document(
            document,
            transcript=segmented_transcript,
            relaxed_sections=coerced_sections,
        )
        if ok:
            if tracker:
                tracker.amend(
                    TRANSCRIBE_05_LLM_SOAP,
                    response={"document": document, "attempt": attempt + 1},
                )
            break

        if tracker:
            tracker.amend(
                TRANSCRIBE_05_LLM_SOAP,
                response={"document": document, "attempt": attempt + 1},
                error="; ".join(validation_errors),
            )

    return {
        "document": document,
        "raw": raw,
        "llm_raw": llm_raw,
        "validation_errors": validation_errors if document is None or validation_errors else None,
        "sections": None,
        "failed_section": None if document and not validation_errors else "monolithic",
    }


def generate_soap_draft(
    text: str,
    *,
    enabled: bool = False,
    provider: str = "phihc",
    model: str = "gemma3:12b-it-qat",
    base_url: str,
    api_key: str = "local",
    system_prompt: str | None = None,
    prompt_path: Path | None = None,
    prompts_dir: Path | None = None,
    split_enabled: bool = True,
    segments: list[dict[str, Any]] | None = None,
    diarization_enabled: bool = False,
    postprocess_applied: bool = False,
    patient_chart_context: str = "",
    tracker: PipelineTracker | None = None,
    timeout: int = 600,
    max_retries: int = 0,
    prompt_compact: bool = False,
) -> dict[str, Any]:
    segmented_transcript = resolve_soap_input_transcript(
        text,
        segments=segments,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
    )
    resolved_prompts_dir = _resolve_prompts_dir(prompts_dir)
    resolved_prompt_path = (prompt_path or DEFAULT_SOAP_PROMPT_PATH).resolve()
    prompt_paths = (
        [str((resolved_prompts_dir / spec.prompt_filename).resolve()) for spec in SOAP_SECTIONS]
        if split_enabled
        else [str(resolved_prompt_path)]
    )

    result: dict[str, Any] = {
        "text": segmented_transcript,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "prompt_path": prompt_paths[0],
        "prompt_paths": prompt_paths,
        "split_enabled": split_enabled,
        "prompt_compact": prompt_compact,
        "skipped": True,
        "error": None,
        "raw": None,
        "document": None,
        "diarization_enabled": diarization_enabled,
        "postprocess_applied": postprocess_applied,
        "validation_errors": None,
        "sections": None,
        "failed_section": None,
        "split_fallback": False,
    }

    if not enabled:
        result["error"] = "postprocess_disabled"
        skip_soap_pipeline_steps(tracker, reason="postprocess_disabled", split_enabled=split_enabled)
        return result

    if not segmented_transcript.strip():
        result["error"] = "empty_transcript"
        skip_soap_pipeline_steps(tracker, reason="empty_transcript", split_enabled=split_enabled)
        return result

    if not base_url.strip():
        result["error"] = "missing_llm_base_url"
        skip_soap_pipeline_steps(tracker, reason="missing_llm_base_url", split_enabled=split_enabled)
        return result

    try:
        if split_enabled:
            if tracker:
                tracker.skip(TRANSCRIBE_05_LLM_SOAP, reason="soap_split_enabled")
            generation = _generate_soap_split(
                segmented_transcript=segmented_transcript,
                diarization_enabled=diarization_enabled,
                postprocess_applied=postprocess_applied,
                patient_chart_context=patient_chart_context,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                prompts_dir=resolved_prompts_dir,
                tracker=tracker,
                timeout=timeout,
                max_retries=max_retries,
                prompt_compact=prompt_compact,
            )
        else:
            if tracker:
                for step_id in SOAP_LLM_STEP_IDS_SPLIT_WITH_MERGE:
                    tracker.skip(step_id, reason="soap_monolithic")
            generation = _generate_soap_monolithic(
                segmented_transcript=segmented_transcript,
                diarization_enabled=diarization_enabled,
                postprocess_applied=postprocess_applied,
                patient_chart_context=patient_chart_context,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                prompt_path=resolved_prompt_path,
                system_prompt=system_prompt,
                tracker=tracker,
                timeout=timeout,
                max_retries=max_retries,
                prompt_compact=prompt_compact,
            )
            document = generation.get("document")
            if isinstance(document, dict) and monolithic_document_degraded(document):
                if tracker:
                    tracker.amend(
                        TRANSCRIBE_05_LLM_SOAP,
                        error="monolithic_degraded_fallback_to_split",
                    )
                generation = _generate_soap_split(
                    segmented_transcript=segmented_transcript,
                    diarization_enabled=diarization_enabled,
                    postprocess_applied=postprocess_applied,
                    patient_chart_context=patient_chart_context,
                    provider=provider,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    prompts_dir=resolved_prompts_dir,
                    tracker=tracker,
                    timeout=timeout,
                    max_retries=max_retries,
                    prompt_compact=prompt_compact,
                )
                result["split_fallback"] = True
    except Exception as exc:
        result["error"] = str(exc)
        return result

    result["raw"] = generation.get("raw")
    result["llm_raw"] = generation.get("llm_raw")
    result["document"] = generation.get("document")
    result["sections"] = generation.get("sections")
    result["failed_section"] = generation.get("failed_section")
    validation_errors = generation.get("validation_errors")

    if result["document"] is None:
        result["error"] = "invalid_json_response"
        result["validation_errors"] = validation_errors
        return result

    if validation_errors:
        result["error"] = "invalid_soap_schema: " + "; ".join(validation_errors)
        result["validation_errors"] = validation_errors
        return result

    result["skipped"] = False
    return result


def _config_path(config: Mapping[str, Any], key: str, default: str) -> Path:
    raw = config.get(key)
    path = Path(raw) if raw else Path(default)
    if not path.is_absolute():
        path = ROOT / path
    return path


def generate_soap_draft_from_config(
    text: str,
    config: Mapping[str, Any],
    *,
    segments: list[dict[str, Any]] | None = None,
    diarization_enabled: bool | None = None,
    postprocess_applied: bool = False,
    tracker: PipelineTracker | None = None,
) -> dict[str, Any]:
    split_enabled = str(config.get("SOAP_SPLIT_ENABLED", "true")).lower() in {"true", "1", "yes"}
    prompt_compact = prompt_compact_for_config(config)
    prompts_dir = _config_path(config, "SOAP_PROMPTS_DIR", "benchmarks/prompts")
    prompt_path = _config_path(config, "SOAP_DRAFT_PROMPT_PATH", "benchmarks/prompts/soap-draft.md")

    if diarization_enabled is None:
        diarization_enabled = bool(config.get("DIARIZATION_ENABLED"))

    llm = resolve_llm_settings(config)
    patient_chart_context = resolve_patient_chart_context(config)
    result = generate_soap_draft(
        text,
        enabled=bool(config.get("TRANSCRIPT_POSTPROCESS_ENABLED")) and soap_enabled_for_config(config),
        provider=llm["provider"],
        model=llm["model"],
        base_url=llm["base_url"],
        api_key=llm["api_key"],
        prompt_path=prompt_path,
        prompts_dir=prompts_dir,
        split_enabled=split_enabled,
        segments=segments,
        diarization_enabled=diarization_enabled,
        postprocess_applied=postprocess_applied,
        patient_chart_context=patient_chart_context,
        tracker=tracker,
        timeout=int(llm["timeout"]),
        max_retries=int(llm["soap_max_retries"]),
        prompt_compact=prompt_compact,
    )
    document = result.get("document")
    if isinstance(document, dict):
        result["plain_text"] = format_soap_plain_text(document)
    else:
        result["plain_text"] = None
    return result
