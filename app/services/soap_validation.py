from __future__ import annotations

import json
import re
from typing import Any, Mapping

EXPECTED_SOAP_STATUS = "RASCUNHO_PENDENTE_DE_REVISAO_MEDICA"
REQUIRED_SOAP_SECTIONS = ("subjetivo", "objetivo", "avaliacao", "plano")
LEGACY_SOAP_KEYS = frozenset({"SOAP", "S", "O", "A", "P"})

_TEMPORAL_MARKER_PATTERNS = (
    re.compile(r"\bhá\s+(?:\d+|duas?|três|tres|quatro|cinco|seis|sete|oito|nove|dez)\s+(?:horas?|dias?|semanas?|meses?|anos?)\b", re.I),
    re.compile(r"\b(?:uns?|cerca de)\s+\d+\s+minutos?\b", re.I),
    re.compile(r"\b\d+\s+anos?\s+atrás\b", re.I),
    re.compile(r"\bhá\s+(?:dois|duas)\s+anos\b", re.I),
)


_COERCION_METADATA_KEYS = frozenset({"_schema_coerced", "_llm_response_text"})

_OBJETIVO_LIST_KEYS = (
    "imaging_results",
    "lab_results",
    "labs_and_imaging",
    "investigations",
    "observations",
    "exam_results",
    "findings",
    "physical_exam",
    "exame_fisico",
    "exames",
    "laudos",
)

_EMR_MONOLITHIC_KEYS = frozenset(
    {
        "patient_id",
        "patient_name",
        "chief_complaint",
        "history_of_present_illness",
        "hpi",
        "physical_exam",
        "investigations",
        "assessment",
        "plan",
        "medications",
        "additional_notes",
        "relevant_medical_history",
        "labs_and_imaging",
    }
)

_OBJETIVO_TEXT_ALIASES = (
    "objetivo",
    "objective",
    "summary",
    "narrative",
    "narrativa",
    "texto",
    "text",
    "content",
)

_PLANO_CONDUTA_ALIASES: tuple[str, ...] = ()


def strip_coercion_metadata(document: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key not in _COERCION_METADATA_KEYS}


def _mark_schema_coerced(doc: dict[str, Any]) -> None:
    doc["_schema_coerced"] = True


def _normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    doc = dict(document)

    response = doc.get("response")
    if isinstance(response, str):
        try:
            inner = json.loads(response)
            if isinstance(inner, dict):
                doc = inner
        except json.JSONDecodeError:
            pass
    elif isinstance(response, dict):
        text = response.get("text")
        if isinstance(text, str) and text.strip():
            doc.pop("response", None)
            doc.setdefault("_llm_response_text", text.strip())
        else:
            merged = dict(response)
            for key, value in doc.items():
                if key != "response" and key not in merged:
                    merged[key] = value
            doc = merged

    return doc


def count_temporal_markers(transcript: str) -> int:
    found: set[str] = set()
    for pattern in _TEMPORAL_MARKER_PATTERNS:
        for match in pattern.finditer(transcript):
            found.add(match.group(0).lower())
    return len(found)


def _normalize_for_temporal_match(text: str) -> str:
    normalized = text.lower()
    normalized = re.sub(r"\b(?:cerca de|aproximadamente|mais ou menos)\s+", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def extract_temporal_markers(transcript: str) -> list[str]:
    markers: list[str] = []
    seen: set[str] = set()
    for pattern in _TEMPORAL_MARKER_PATTERNS:
        for match in pattern.finditer(transcript):
            marker = match.group(0).lower()
            if marker not in seen:
                seen.add(marker)
                markers.append(marker)
    return markers


def temporal_markers_preserved_in_text(text: str, transcript: str) -> int:
    """How many distinct temporal markers from the transcript appear in text."""
    preserved: set[str] = set()
    lower_text = _normalize_for_temporal_match(text)
    for pattern in _TEMPORAL_MARKER_PATTERNS:
        for match in pattern.finditer(transcript):
            marker = _normalize_for_temporal_match(match.group(0))
            if marker in lower_text:
                preserved.add(marker)
    return len(preserved)


_FIDELITY_ANCHOR_TERMS = (
    "peito",
    "pressão",
    "pressao",
    "tórax",
    "torax",
    "náusea",
    "nausea",
    "nauseada",
)

_HALLUCINATION_TERMS = (
    "lombar",
    "coluna vertebral",
    "cefaleia",
    "cabeça",
    "cabeca",
    "perna esquerda",
    "irradi",
)


SUBJETIVO_TEXT_ALIASES = (
    "subjetivo",
    "summary",
    "narrativa",
    "narrative",
    "texto",
    "text",
    "content",
    "relato",
)

SUBJETIVO_STRUCTURAL_WRONG_KEYS = frozenset(
    {
        "key_concerns",
        "medical_history",
        "lifestyle",
        "lifestyle_factors",
        "social_history",
        "ordered_tests",
        "next_steps",
        "recommendations",
        "patient_description",
        "family_history",
    }
)

_SUBJETIVO_EMR_WRONG_KEYS = frozenset(
    {
        "patient_id",
        "chief_complaint",
        "history_of_present_illness",
        "hpi",
        "physical_exam",
        "investigations",
        "assessment",
        "relevant_medical_history",
        "medications",
    }
)

_SUBJETIVO_EMR_TEXT_KEYS = (
    "history_of_present_illness",
    "hpi",
    "chief_complaint",
    "subjective",
    "subjective_note",
    "patient_description",
)

SUBJETIVO_WRONG_SCHEMA_KEYS = SUBJETIVO_STRUCTURAL_WRONG_KEYS | frozenset({"summary"})

NARRATIVE_SOAP_SECTIONS = frozenset({"subjetivo", "objetivo", "avaliacao", "plano"})
PLANO_RESPONSE_KEY = "plano_conduta"
PLANO_LEGACY_KEYS = ("plano_de_conduta", "plano", "plan_conduta", "plan")
_PLANO_CONDUTA_ALIASES = (
    PLANO_RESPONSE_KEY,
    "plan_conduta",
    "plano_de_conduta",
    "plano",
    "plan",
    "conduta",
)
EMPTY_OBJETIVO_TEXT = "Sem dados objetivos suficientes na transcrição."
EMPTY_AVALIACAO_TEXT = "Avaliação não explicitada de forma suficiente na consulta."
EMPTY_PLANO_TEXT = "Conduta não explicitada de forma suficiente na consulta."
EMPTY_SUBJETIVO_TEXT = "Relato não explicitado de forma suficiente na transcrição."

_META_ECHO_RE = re.compile(
    r"^gerar um json de\s+\w+",
    re.I,
)
_META_ECHO_PATTERNS = (
    _META_ECHO_RE,
    re.compile(r"identificar e corrigir erros", re.I),
    re.compile(r"timestamps,\s*trechos originais e motivos", re.I),
    re.compile(r"transcri(?:ç|c)ão completa e coerente", re.I),
    re.compile(r"capturando a din[aâ]mica da consulta", re.I),
    re.compile(r"linguagem utilizada reflete a conversa natural", re.I),
)
_AVALIACAO_RUBRIC_KEYS = frozenset(
    {"pontuacao", "justificativa", "aspectos_positivos", "aspectos_negativos", "recomendações", "recomendacoes"}
)


def _is_narrative_section(value: Any) -> bool:
    return isinstance(value, str)


def _is_narrative_subjetivo(value: Any) -> bool:
    return _is_narrative_section(value)


def _is_meta_echo_text(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in _META_ECHO_PATTERNS)


def _is_avaliacao_rubric_dict(value: dict[str, Any]) -> bool:
    keys = set(value.keys())
    return bool(keys) and keys.issubset(_AVALIACAO_RUBRIC_KEYS)


def _plano_lines_from_mapping(value: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    etapas = value.get("etapas")
    if isinstance(etapas, list):
        for item in etapas:
            if isinstance(item, str) and item.strip():
                lines.append(item.strip())
            elif isinstance(item, dict):
                for field in ("descricao", "acao", "passo", "conduta"):
                    text = item.get(field)
                    if isinstance(text, str) and text.strip():
                        lines.append(text.strip())
                        break
    for key in sorted(value.keys()):
        if key in {"etapas", "objetivo_principal"}:
            continue
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            lines.append(item.strip())
    return lines


def _coerce_plano_conduta_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        lines = [str(item).strip() for item in value if str(item).strip()]
        portuguese_lines = [line for line in lines if not _looks_english(line)]
        if portuguese_lines:
            return "\n".join(portuguese_lines)
        return "\n".join(lines) if lines else ""
    if isinstance(value, dict):
        return "\n".join(_plano_lines_from_mapping(value))
    return ""


def _hint_to_alerta(hint: str) -> dict[str, str]:
    if ": " in hint:
        _, detail = hint.split(": ", 1)
        motivo = hint
        trecho = detail
    else:
        motivo = hint
        trecho = hint
    return {"timestamp": "", "trecho_original": trecho, "motivo": motivo}


def _normalize_alertas_items(alertas: Any) -> list[dict[str, str]]:
    if not isinstance(alertas, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in alertas:
        if isinstance(item, dict):
            normalized.append(
                {
                    "timestamp": str(item.get("timestamp") or ""),
                    "trecho_original": str(item.get("trecho_original") or ""),
                    "motivo": str(item.get("motivo") or ""),
                }
            )
        elif isinstance(item, str) and item.strip():
            normalized.append(_hint_to_alerta(item.strip()))
    return normalized


def _first_narrative_alias(
    doc: Mapping[str, Any],
    aliases: tuple[str, ...],
    *,
    exclude: tuple[str, ...] = (),
) -> str:
    for key in aliases:
        if key in exclude:
            continue
        value = doc.get(key)
        if _is_narrative_section(value) and value.strip():
            return value.strip()
    return ""


def _lines_from_list_values(doc: Mapping[str, Any], keys: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    for key in keys:
        value = doc.get(key)
        if isinstance(value, list):
            for item in value:
                text = str(item).strip()
                if text:
                    lines.append(text)
        elif isinstance(value, str) and value.strip():
            lines.append(value.strip())
    return lines


def _avaliacao_from_topic_dict(doc: Mapping[str, Any]) -> str:
    reserved = frozenset(
        {
            "alertas_revisao",
            "avaliacao",
            "_schema_coerced",
            "_llm_response_text",
            "response",
        }
    )
    lines: list[str] = []
    for key, value in doc.items():
        if key in reserved:
            continue
        if isinstance(value, str) and value.strip():
            lines.append(f"{key}: {value.strip()}")
        elif isinstance(value, (int, float, bool)):
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def normalize_llm_response_document(document: dict[str, Any]) -> dict[str, Any]:
    """Unwrap common MedGemma / LLM response envelopes before section parsing."""
    return _normalize_document(document)


def _has_valid_subjetivo_text(doc: Mapping[str, Any]) -> bool:
    subjetivo = doc.get("subjetivo")
    return _is_narrative_subjetivo(subjetivo) and bool(str(subjetivo).strip())


def _subjetivo_from_emr_fields(doc: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in _SUBJETIVO_EMR_TEXT_KEYS:
        value = doc.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n\n".join(parts)


def _coerce_subjetivo_partial(partial: dict[str, Any]) -> dict[str, Any]:
    doc = dict(_normalize_document(partial))
    coerced = False

    if not _has_valid_subjetivo_text(doc):
        llm_text = doc.get("_llm_response_text")
        if _is_narrative_section(llm_text) and llm_text.strip():
            doc["subjetivo"] = llm_text.strip()
            doc.pop("_llm_response_text", None)
            coerced = True

    if not _has_valid_subjetivo_text(doc):
        alias_text = _first_narrative_alias(doc, SUBJETIVO_TEXT_ALIASES, exclude=("subjetivo",))
        if alias_text:
            doc["subjetivo"] = alias_text
            coerced = True

    if not _has_valid_subjetivo_text(doc):
        emr_text = _subjetivo_from_emr_fields(doc)
        if emr_text:
            doc["subjetivo"] = emr_text
            coerced = True

    if not _has_valid_subjetivo_text(doc):
        wrong_keys = (
            SUBJETIVO_STRUCTURAL_WRONG_KEYS
            | _SUBJETIVO_EMR_WRONG_KEYS
            | SUBJETIVO_WRONG_SCHEMA_KEYS
        )
        if wrong_keys.intersection(doc.keys()):
            doc["subjetivo"] = EMPTY_SUBJETIVO_TEXT
            coerced = True

    if not _has_valid_subjetivo_text(doc):
        doc["subjetivo"] = EMPTY_SUBJETIVO_TEXT
        coerced = True

    if _ensure_portuguese_narrative(doc, "subjetivo", EMPTY_SUBJETIVO_TEXT):
        coerced = True

    if coerced:
        _mark_schema_coerced(doc)

    if not isinstance(doc.get("alertas_revisao"), list):
        doc["alertas_revisao"] = []
    return doc


def _has_valid_narrative_key(doc: Mapping[str, Any], key: str) -> bool:
    value = doc.get(key)
    return _is_narrative_section(value) and bool(str(value).strip())


def _coerce_narrative_from_llm_response_text(
    doc: dict[str, Any],
    key: str,
) -> bool:
    if _has_valid_narrative_key(doc, key):
        return False
    llm_text = doc.get("_llm_response_text")
    if _is_narrative_section(llm_text) and llm_text.strip():
        doc[key] = llm_text.strip()
        doc.pop("_llm_response_text", None)
        return True
    return False


def _coerce_objetivo_partial(partial: dict[str, Any]) -> dict[str, Any]:
    doc = dict(_normalize_document(partial))
    coerced = False

    if _coerce_narrative_from_llm_response_text(doc, "objetivo"):
        coerced = True

    if not _has_valid_narrative_key(doc, "objetivo"):
        alias_text = _first_narrative_alias(doc, _OBJETIVO_TEXT_ALIASES, exclude=("objetivo",))
        if alias_text:
            doc["objetivo"] = alias_text
            coerced = True

    if not _has_valid_narrative_key(doc, "objetivo"):
        lines = _lines_from_list_values(doc, _OBJETIVO_LIST_KEYS)
        portuguese_lines = [line for line in lines if not _looks_english(line)]
        if portuguese_lines:
            doc["objetivo"] = "\n".join(portuguese_lines)
            coerced = True
        elif lines:
            doc["objetivo"] = EMPTY_OBJETIVO_TEXT
            coerced = True

    if not _has_valid_narrative_key(doc, "objetivo"):
        structural_wrong = SUBJETIVO_STRUCTURAL_WRONG_KEYS.intersection(doc.keys())
        emr_keys = {
            "patient_name",
            "patient_id",
            "medications",
            "plan",
            "patient_description",
            "medical_history",
            "assessment",
            "labs_and_imaging",
        }
        if structural_wrong or emr_keys.intersection(doc.keys()):
            doc["objetivo"] = EMPTY_OBJETIVO_TEXT
            coerced = True

    if not _has_valid_narrative_key(doc, "objetivo"):
        doc["objetivo"] = EMPTY_OBJETIVO_TEXT
        coerced = True

    if _ensure_portuguese_narrative(doc, "objetivo", EMPTY_OBJETIVO_TEXT):
        coerced = True

    if coerced:
        _mark_schema_coerced(doc)

    if not isinstance(doc.get("alertas_revisao"), list):
        doc["alertas_revisao"] = []
    return doc


def _coerce_avaliacao_partial(partial: dict[str, Any]) -> dict[str, Any]:
    doc = dict(_normalize_document(partial))
    coerced = False

    if _coerce_narrative_from_llm_response_text(doc, "avaliacao"):
        coerced = True

    if not _has_valid_narrative_key(doc, "avaliacao"):
        for list_key in ("assessment", "potential_diagnoses", "impressao_clinica"):
            value = doc.get(list_key)
            if isinstance(value, list):
                lines = [
                    str(item).strip()
                    for item in value
                    if str(item).strip() and not _looks_english(str(item))
                ]
                if lines:
                    doc["avaliacao"] = "\n".join(lines)
                    coerced = True
                    break

    if not _has_valid_narrative_key(doc, "avaliacao"):
        alias_text = _first_narrative_alias(doc, SUBJETIVO_TEXT_ALIASES, exclude=("avaliacao",))
        if alias_text:
            doc["avaliacao"] = alias_text
            coerced = True

    if not _has_valid_narrative_key(doc, "avaliacao"):
        topic_text = _avaliacao_from_topic_dict(doc)
        if topic_text:
            doc["avaliacao"] = topic_text
            coerced = True

    if not _has_valid_narrative_key(doc, "avaliacao"):
        structural_wrong = SUBJETIVO_STRUCTURAL_WRONG_KEYS.intersection(doc.keys())
        if structural_wrong:
            doc["avaliacao"] = EMPTY_AVALIACAO_TEXT
            coerced = True

    if not _has_valid_narrative_key(doc, "avaliacao"):
        doc["avaliacao"] = EMPTY_AVALIACAO_TEXT
        coerced = True

    if _ensure_portuguese_narrative(doc, "avaliacao", EMPTY_AVALIACAO_TEXT):
        coerced = True

    if coerced:
        _mark_schema_coerced(doc)

    if not isinstance(doc.get("alertas_revisao"), list):
        doc["alertas_revisao"] = []
    return doc


def supplement_alertas_from_hints(partial: dict[str, Any], transcript: str) -> dict[str, Any]:
    hints = transcript_review_hints(transcript)
    if not hints:
        return partial

    alertas = partial.get("alertas_revisao")
    if isinstance(alertas, list) and len(alertas) > 0:
        return partial

    doc = dict(partial)
    doc["alertas_revisao"] = [_hint_to_alerta(hint) for hint in hints]
    return doc


def subjetivo_matches_transcript(subjetivo: str, transcript: str) -> bool:
    if not subjetivo.strip() or not transcript.strip():
        return True

    subj_lower = subjetivo.lower()
    trans_lower = transcript.lower()

    for term in _HALLUCINATION_TERMS:
        if term in subj_lower and term not in trans_lower:
            return False

    anchors_in_transcript = [term for term in _FIDELITY_ANCHOR_TERMS if term in trans_lower]
    if len(anchors_in_transcript) >= 2:
        matches = sum(1 for term in anchors_in_transcript if term in subj_lower)
        if matches < 1:
            return False

    return True


def normalize_soap_section_partial(
    section: str,
    partial: dict[str, Any],
    *,
    transcript: str = "",
) -> dict[str, Any]:
    """Coerce common LLM schema drift before validation."""
    doc = _normalize_document(partial)

    if section == "subjetivo":
        doc = _coerce_subjetivo_partial(doc)
        if transcript:
            doc = supplement_alertas_from_hints(doc, transcript)
    elif section == "objetivo":
        doc = _coerce_objetivo_partial(doc)
    elif section == "avaliacao":
        doc = _coerce_avaliacao_partial(doc)

    if section == "plano":
        coerced = False
        if _coerce_narrative_from_llm_response_text(doc, PLANO_RESPONSE_KEY):
            coerced = True

        if not _plano_partial_text(doc):
            for alias in _PLANO_CONDUTA_ALIASES:
                if alias == PLANO_RESPONSE_KEY:
                    continue
                value = doc.get(alias)
                if value not in (None, ""):
                    doc[PLANO_RESPONSE_KEY] = value
                    if alias != PLANO_RESPONSE_KEY:
                        doc.pop(alias, None)
                    coerced = True
                    break

        for legacy_key in PLANO_LEGACY_KEYS:
            if legacy_key in doc and not _plano_partial_text(doc):
                doc[PLANO_RESPONSE_KEY] = doc.pop(legacy_key)
                coerced = True
            elif legacy_key in doc and doc.get(PLANO_RESPONSE_KEY) in (None, ""):
                doc[PLANO_RESPONSE_KEY] = doc.pop(legacy_key)
                coerced = True

        plano_text = _coerce_plano_conduta_text(doc.get(PLANO_RESPONSE_KEY))
        if plano_text:
            doc[PLANO_RESPONSE_KEY] = plano_text
        elif PLANO_RESPONSE_KEY in doc and not isinstance(doc[PLANO_RESPONSE_KEY], str):
            doc.pop(PLANO_RESPONSE_KEY, None)

        if not _plano_partial_text(doc):
            doc[PLANO_RESPONSE_KEY] = EMPTY_PLANO_TEXT
            coerced = True

        if _ensure_portuguese_narrative(doc, PLANO_RESPONSE_KEY, EMPTY_PLANO_TEXT):
            coerced = True

        if coerced:
            _mark_schema_coerced(doc)

    doc["alertas_revisao"] = _normalize_alertas_items(doc.get("alertas_revisao"))
    return doc


def _validate_alertas_items(alertas: Any, errors: list[str]) -> None:
    if alertas is None:
        return
    if not isinstance(alertas, list):
        errors.append("alertas_revisao deve ser uma lista")
        return
    for item in alertas:
        if not isinstance(item, dict):
            errors.append(
                "alertas_revisao deve conter objetos com timestamp, trecho_original e motivo"
            )
            break


_ENGLISH_TEXT_MARKERS = (
    " the ",
    " patient ",
    " experiencing ",
    " especially ",
    " with ",
    " history ",
    " ordered ",
    " chest pain",
    " heart disease",
    " family history",
    " possible cardiac",
    " brother has",
    " father had",
    " had heart attack",
    " kidney",
    " kidneys",
    " normal in size",
    " patient reports",
    " patient has",
    " without dilation",
    " are elevated",
    " are present",
    " blood in urine",
    " taking ",
    " levels are",
    " without evidence",
    " are normal",
    " are patent",
)

_ENGLISH_TEXT_PHRASES = (
    "chest pain",
    "heart disease",
    "family history",
    "especially with exertion",
    "possible cardiac",
    "kidneys are",
    "patient reports",
    "patient has a history",
    "patient is",
    "patient was",
    "without evidence of",
    "normal in size",
    "creatinine levels",
    "urine analysis shows",
    "physical exam",
    "no acute concerns",
    "stable condition",
    "kidney function",
    "blood in urine",
    "follow-up for",
    "follow up for",
    "not explicitly mentioned",
    "provided text",
    "order blood tests",
    "acute kidney injury",
    "chronic kidney disease",
    "benign finding",
    "controlled hypertension",
    "instruct patient",
    "reinforce the importance",
    "healthcare professionals",
    "acute kidney",
    "chronic kidney",
    "rule out",
    "order repeat",
    "blood tests",
    "to be ordered",
    "urinalysis",
    "hematuria",
    "complete blood count",
    "kidney ultrasound",
    "cysts cortical",
    "cystic cortical",
    "previous episode",
)


def _looks_english(text: str) -> bool:
    lower = f" {text.lower()} "
    if any(phrase in lower for phrase in _ENGLISH_TEXT_PHRASES):
        return True
    return sum(1 for marker in _ENGLISH_TEXT_MARKERS if marker in lower) >= 2


def _ensure_portuguese_narrative(
    doc: dict[str, Any],
    key: str,
    empty_text: str,
) -> bool:
    value = doc.get(key)
    if not _is_narrative_section(value) or not str(value).strip():
        return False
    text = str(value)
    if _looks_english(text):
        doc[key] = empty_text
        return True
    for line in text.split("\n"):
        if line.strip() and _looks_english(line.strip()):
            doc[key] = empty_text
            return True
    return False


def monolithic_document_degraded(document: Mapping[str, Any]) -> bool:
    """True when monolithic LLM output was coerced to placeholders or still has English."""
    soap = document.get("soap")
    if not isinstance(soap, dict):
        return True

    placeholders = {
        EMPTY_SUBJETIVO_TEXT,
        EMPTY_OBJETIVO_TEXT,
        EMPTY_AVALIACAO_TEXT,
        EMPTY_PLANO_TEXT,
    }
    placeholder_count = sum(
        1 for section in REQUIRED_SOAP_SECTIONS if soap.get(section) in placeholders
    )
    if placeholder_count >= 2:
        return True

    for section in NARRATIVE_SOAP_SECTIONS:
        value = soap.get(section)
        if not isinstance(value, str) or not value.strip():
            continue
        if _looks_english(value):
            return True
        for line in value.split("\n"):
            if line.strip() and _looks_english(line.strip()):
                return True
    return False


def _require_portuguese(
    text: str,
    field: str,
    errors: list[str],
) -> None:
    if _looks_english(text):
        errors.append(f"{field} deve estar em português brasileiro, não em inglês")


def _subjetivo_uses_conflicting_patient_name(subjetivo: str, transcript: str) -> bool:
    hints = transcript_review_hints(transcript)
    if not any("identificacao_conflitante" in hint for hint in hints):
        return False
    lower = subjetivo.lower()
    return bool(re.search(r"\b(dona\s+)?yasmin\b", lower))


def _validate_subjetivo_value(
    subjetivo: Any,
    *,
    transcript: str,
    errors: list[str],
    alertas: Any,
    relaxed: bool = False,
) -> None:
    if _is_narrative_subjetivo(subjetivo):
        if not subjetivo.strip():
            errors.append("subjetivo não pode estar vazio")
        else:
            _require_portuguese(subjetivo, "subjetivo", errors)
            if transcript and not relaxed:
                if not subjetivo_matches_transcript(subjetivo, transcript):
                    errors.append(
                        "subjetivo não corresponde ao conteúdo da transcrição (possível alucinação)"
                    )
                if _subjetivo_uses_conflicting_patient_name(subjetivo, transcript):
                    errors.append(
                        "subjetivo não deve usar Yasmin como nome da paciente; "
                        "use Patrícia (Yasmin é erro de transcrição do médico)"
                    )
                marker_count = count_temporal_markers(transcript)
                preserved = temporal_markers_preserved_in_text(subjetivo, transcript)
                if marker_count >= 2 and preserved < 2:
                    errors.append(
                        f"subjetivo deve preservar pelo menos 2 marcadores temporais distintos "
                        f"(transcrição tem ~{marker_count}; texto preserva ~{preserved})"
                    )
    elif isinstance(subjetivo, dict):
        timeline = subjetivo.get("linha_do_tempo_sintomas")
        if timeline is not None and not isinstance(timeline, list):
            errors.append("soap.subjetivo.linha_do_tempo_sintomas deve ser uma lista")
        if transcript:
            marker_count = count_temporal_markers(transcript)
            timeline_len = len(timeline) if isinstance(timeline, list) else 0
            if marker_count >= 2 and timeline_len < 2:
                errors.append(
                    f"linha_do_tempo_sintomas deve ter pelo menos 2 eventos "
                    f"(transcrição tem ~{marker_count} marcadores temporais distintos)"
                )
    else:
        errors.append("subjetivo ausente ou inválido (esperado texto ou objeto)")


def _validate_objetivo_value(
    objetivo: Any,
    *,
    errors: list[str],
    alertas: Any,
) -> None:
    if _is_narrative_section(objetivo):
        if not objetivo.strip():
            errors.append("objetivo não pode estar vazio")
        elif _is_meta_echo_text(objetivo):
            errors.append("objetivo não pode repetir a instrução do prompt")
        else:
            _require_portuguese(objetivo, "objetivo", errors)
    elif isinstance(objetivo, dict):
        errors.append("objetivo deve ser texto narrativo, não objeto")
    else:
        errors.append("objetivo ausente ou inválido (esperado texto)")

    _validate_alertas_items(alertas, errors)


def _validate_avaliacao_value(
    avaliacao: Any,
    *,
    errors: list[str],
    alertas: Any,
) -> None:
    if _is_narrative_section(avaliacao):
        if not avaliacao.strip():
            errors.append("avaliacao não pode estar vazia")
        elif _is_meta_echo_text(avaliacao):
            errors.append("avaliacao não pode repetir a instrução do prompt")
        else:
            _require_portuguese(avaliacao, "avaliacao", errors)
    elif isinstance(avaliacao, dict):
        if _is_avaliacao_rubric_dict(avaliacao):
            errors.append("avaliacao deve ser texto clínico, não objeto de pontuação")
        else:
            errors.append("avaliacao deve ser texto narrativo, não objeto")
    else:
        errors.append("avaliacao ausente ou inválida (esperado texto)")

    _validate_alertas_items(alertas, errors)


def _plano_partial_text(partial: dict[str, Any]) -> str:
    value = partial.get(PLANO_RESPONSE_KEY)
    if isinstance(value, str):
        return value.strip()
    legacy = partial.get("plano")
    if isinstance(legacy, str):
        return legacy.strip()
    return ""


def _merged_plano_value(plano_partial: dict[str, Any]) -> Any:
    text = _plano_partial_text(plano_partial)
    if text:
        return text
    legacy = plano_partial.get("plano")
    if isinstance(legacy, dict):
        return legacy
    return ""


def _validate_plano_partial(
    partial: dict[str, Any],
    *,
    errors: list[str],
    alertas: Any,
) -> None:
    raw_value = partial.get(PLANO_RESPONSE_KEY)
    if isinstance(raw_value, dict):
        errors.append("plano_conduta deve ser texto (string), não objeto")

    text = _plano_partial_text(partial)
    if text:
        if not text.strip():
            errors.append("plano_conduta não pode estar vazio")
        elif _is_meta_echo_text(text):
            errors.append("plano_conduta não pode repetir a instrução do prompt")
        else:
            _require_portuguese(text, "plano_conduta", errors)
    else:
        errors.append("plano_conduta ausente ou inválido (esperado texto)")

    _validate_alertas_items(alertas, errors)


def _validate_plano_merged_value(plano: Any, *, errors: list[str]) -> None:
    if _is_narrative_section(plano):
        if not plano.strip():
            errors.append("plano não pode estar vazio")
        else:
            _require_portuguese(plano, "plano", errors)
    elif isinstance(plano, dict):
        pass
    else:
        errors.append("plano ausente ou inválido (esperado texto ou objeto)")


def _merge_alertas(*partials: dict[str, Any]) -> list[Any]:
    alertas: list[Any] = []
    for partial in partials:
        items = partial.get("alertas_revisao")
        if isinstance(items, list):
            alertas.extend(_normalize_alertas_items(items))
    return alertas


def _validate_alertas_for_transcript(
    alertas: Any,
    transcript: str,
    errors: list[str],
) -> None:
    if alertas is not None and not isinstance(alertas, list):
        errors.append("alertas_revisao deve ser uma lista")
        return
    if not transcript:
        return
    hints = transcript_review_hints(transcript)
    alertas_len = len(alertas) if isinstance(alertas, list) else 0
    if hints and alertas_len < 1:
        errors.append(
            "alertas_revisao não pode estar vazio quando a transcrição contém "
            f"termos incertos ({'; '.join(hints[:3])})"
        )


def _soap_section_value(partial: dict[str, Any], key: str) -> Any:
    if key == "plano":
        return _merged_plano_value(partial)
    value = partial.get(key)
    if value is not None:
        return value
    return "" if key in NARRATIVE_SOAP_SECTIONS else {}


def transcript_review_hints(transcript: str) -> list[str]:
    hints: list[str] = []
    lower = transcript.lower()

    has_patricia = "patrícia" in lower or "patricia" in lower
    if has_patricia and "yasmin" in lower:
        hints.append("identificacao_conflitante: Patrícia vs Yasmin na transcrição")

    if "tortura" in lower:
        hints.append("termo_clinico_inseguro: tortura (possível erro de ASR para tontura)")

    if re.search(r"cirurgia.{0,40}parede|parede.{0,40}cirurgia", lower):
        hints.append("termo_clinico_inseguro: cirurgia de parede (possível varizes)")

    if re.search(r"clóster|pele na vez", lower):
        hints.append("termo_clinico_inseguro: possível erro de ASR para vesícula")

    return hints


def _monolithic_source_document(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten nested soap.* or EMR keys into one dict for section coercion."""
    soap = doc.get("soap")
    if isinstance(soap, dict):
        source = dict(soap)
        alertas = doc.get("alertas_revisao")
        if isinstance(alertas, list):
            source["alertas_revisao"] = alertas
        return source
    return dict(doc)


def _needs_monolithic_section_coercion(doc: Mapping[str, Any]) -> bool:
    if isinstance(doc.get("soap"), dict):
        return True
    if any(section in doc for section in REQUIRED_SOAP_SECTIONS):
        return True
    return bool(_EMR_MONOLITHIC_KEYS.intersection(doc.keys()))


def normalize_monolithic_soap_document(
    document: dict[str, Any],
    *,
    transcript: str = "",
) -> dict[str, Any]:
    """Wrap flat LLM keys into nested soap.* and coerce EMR schema drift to pt-BR."""
    doc = _normalize_document(document)
    if not _needs_monolithic_section_coercion(doc):
        return doc

    source = _monolithic_source_document(doc)
    subjetivo_partial = normalize_soap_section_partial(
        "subjetivo",
        source,
        transcript=transcript,
    )
    objetivo_partial = normalize_soap_section_partial("objetivo", source)
    avaliacao_partial = normalize_soap_section_partial("avaliacao", source)
    plano_partial = normalize_soap_section_partial("plano", source)

    normalized = merge_soap_sections(
        subjetivo=subjetivo_partial,
        objetivo=objetivo_partial,
        avaliacao=avaliacao_partial,
        plano=plano_partial,
    )

    evidencias = doc.get("evidencias_chave")
    if isinstance(evidencias, list):
        normalized["evidencias_chave"] = evidencias

    return normalized


def validate_soap_document(
    document: dict[str, Any],
    *,
    transcript: str = "",
    relaxed_sections: frozenset[str] | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    doc = _normalize_document(document)
    relaxed = relaxed_sections or frozenset()

    legacy_keys = LEGACY_SOAP_KEYS.intersection(doc.keys())
    if legacy_keys:
        errors.append(
            f"formato legado rejeitado ({', '.join(sorted(legacy_keys))}); "
            "use status e soap.subjetivo/objetivo/avaliacao/plano"
        )
        return False, errors

    status = doc.get("status")
    if status != EXPECTED_SOAP_STATUS:
        errors.append(
            f'status deve ser "{EXPECTED_SOAP_STATUS}"'
            + (f', recebido: {status!r}' if status is not None else ", ausente")
        )

    soap = doc.get("soap")
    if not isinstance(soap, dict):
        errors.append("campo soap ausente ou inválido")
        return False, errors

    for section in REQUIRED_SOAP_SECTIONS:
        value = soap.get(section)
        if section in NARRATIVE_SOAP_SECTIONS:
            if not _is_narrative_section(value) and not isinstance(value, dict):
                errors.append(f"soap.{section} ausente ou inválido")
        elif not isinstance(value, dict):
            errors.append(f"soap.{section} ausente ou inválido")

    subjetivo = soap.get("subjetivo")
    objetivo = soap.get("objetivo")
    alertas = doc.get("alertas_revisao")
    if isinstance(soap, dict):
        _validate_subjetivo_value(
            subjetivo,
            transcript=transcript,
            errors=errors,
            alertas=alertas,
            relaxed="subjetivo" in relaxed,
        )
        _validate_objetivo_value(objetivo, errors=errors, alertas=alertas)
        avaliacao = soap.get("avaliacao")
        _validate_avaliacao_value(avaliacao, errors=errors, alertas=alertas)
        _validate_plano_merged_value(soap.get("plano"), errors=errors)
    _validate_alertas_items(alertas, errors)
    if "subjetivo" not in relaxed:
        _validate_alertas_for_transcript(alertas, transcript, errors)

    return len(errors) == 0, errors


SOAP_SECTION_KEYS = {
    "subjetivo": ("subjetivo", "alertas_revisao"),
    "objetivo": ("objetivo", "alertas_revisao"),
    "avaliacao": ("avaliacao", "alertas_revisao"),
    "plano": (PLANO_RESPONSE_KEY, "alertas_revisao"),
}


def canonicalize_section_partial(section: str, partial: Mapping[str, Any]) -> dict[str, Any]:
    keys = SOAP_SECTION_KEYS.get(section, ())
    return {key: partial[key] for key in keys if key in partial}


def validate_soap_section(
    section: str,
    partial: dict[str, Any],
    *,
    transcript: str = "",
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    doc = normalize_soap_section_partial(
        section,
        _normalize_document(partial),
        transcript=transcript,
    )
    relaxed = bool(doc.get("_schema_coerced"))

    legacy_keys = LEGACY_SOAP_KEYS.intersection(doc.keys())
    if legacy_keys:
        errors.append(
            f"formato legado rejeitado ({', '.join(sorted(legacy_keys))}); "
            "use apenas as chaves do schema desta seção"
        )
        return False, errors

    if section == "subjetivo":
        subjetivo = doc.get("subjetivo")
        alertas = doc.get("alertas_revisao")
        _validate_subjetivo_value(
            subjetivo,
            transcript=transcript,
            errors=errors,
            alertas=alertas,
            relaxed=relaxed,
        )
        _validate_alertas_items(alertas, errors)
        if not relaxed:
            _validate_alertas_for_transcript(alertas, transcript, errors)

    elif section == "objetivo":
        objetivo = doc.get("objetivo")
        alertas = doc.get("alertas_revisao")
        _validate_objetivo_value(objetivo, errors=errors, alertas=alertas)

    elif section == "avaliacao":
        avaliacao = doc.get("avaliacao")
        alertas = doc.get("alertas_revisao")
        _validate_avaliacao_value(avaliacao, errors=errors, alertas=alertas)

    elif section == "plano":
        alertas = doc.get("alertas_revisao")
        _validate_plano_partial(doc, errors=errors, alertas=alertas)

    else:
        errors.append(f"seção SOAP desconhecida: {section}")

    return len(errors) == 0, errors


def merge_soap_sections(
    *,
    subjetivo: dict[str, Any],
    objetivo: dict[str, Any],
    avaliacao: dict[str, Any],
    plano: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": EXPECTED_SOAP_STATUS,
        "soap": {
            "subjetivo": _soap_section_value(subjetivo, "subjetivo"),
            "objetivo": _soap_section_value(objetivo, "objetivo"),
            "avaliacao": _soap_section_value(avaliacao, "avaliacao"),
            "plano": _merged_plano_value(plano),
        },
        "alertas_revisao": _merge_alertas(subjetivo, objetivo, avaliacao, plano),
    }


def soap_section_retry_appendix(
    section: str,
    validation_errors: list[str],
    *,
    transcript: str = "",
) -> str:
    error_text = "; ".join(validation_errors)
    keys = ", ".join(SOAP_SECTION_KEYS.get(section, ()))
    extra = ""
    if section == "subjetivo":
        extra = (
            "\nPreserve todos os marcadores temporais distintos no texto narrativo "
            "(ex.: há duas semanas vs há duas horas)."
            "\nUse SOMENTE informações presentes na transcrição fornecida; não invente outro quadro clínico."
            "\nTexto do subjetivo deve estar em português brasileiro."
        )
        if any(
            token in err
            for err in validation_errors
            for token in ("subjetivo ausente", "schema inválido")
        ):
            extra += (
                '\nNÃO use chaves como summary, key_concerns, medical_history, ordered_tests ou next_steps.'
                '\nUse EXATAMENTE: {"subjetivo": "<texto narrativo em português>", "alertas_revisao": [...]}.'
            )
        if any("Yasmin" in err for err in validation_errors):
            extra += (
                "\nA paciente se identifica como Patrícia; Yasmin é lapso do médico na transcrição."
            )
        if transcript:
            markers = extract_temporal_markers(transcript)
            if markers:
                extra += (
                    "\nMarcadores temporais da transcrição que devem constar no subjetivo: "
                    + "; ".join(markers[:8])
                    + "."
                )
            hints = transcript_review_hints(transcript)
            if hints:
                extra += (
                    "\nInclua alertas_revisao para: " + "; ".join(hints[:5]) + "."
                )
    elif section == "avaliacao":
        extra = (
            "\nTexto da avaliacao deve estar em português brasileiro."
            '\nNÃO use summary, key_concerns, recommendations, medical_history ou family_history.'
            '\nUse EXATAMENTE: {"avaliacao": "<problema por linha em português>", "alertas_revisao": [...]}.'
        )
        if any("schema inválido" in err or "português" in err for err in validation_errors):
            extra += (
                "\nFormule em português apenas hipóteses ou problemas verbalizados pelo médico "
                "(ex.: investigar origem cardiovascular da dor referida)."
            )
    elif section == "objetivo":
        extra = (
            "\nTexto do objetivo deve estar em português brasileiro."
            '\nUse EXATAMENTE: {"objetivo": "<texto narrativo em português>", "alertas_revisao": [...]}.'
            "\nNÃO use chaves EMR em inglês (patient_name, lab_results, imaging_results, patient reports)."
        )
    elif section == "plano":
        extra = (
            '\nUse EXATAMENTE a chave "plano_conduta" com valor STRING '
            "(uma conduta por linha, separadas por \\n). "
            "NÃO use plano_de_conduta, NÃO use objeto com etapas."
            "\nTexto do plano_conduta deve estar em português brasileiro."
        )
    return (
        "CORREÇÃO OBRIGATÓRIA — a resposta anterior foi rejeitada.\n"
        f"Erros: {error_text}\n"
        f"Responda novamente com JSON válido contendo somente: {keys}.\n"
        "NÃO use chaves SOAP, S, O, A ou P no nível raiz."
        f"{extra}"
    )


def soap_retry_user_appendix(validation_errors: list[str]) -> str:
    error_text = "; ".join(validation_errors)
    return (
        "CORREÇÃO OBRIGATÓRIA — a resposta anterior foi rejeitada.\n"
        f"Erros: {error_text}\n"
        "Responda novamente com JSON válido usando EXATAMENTE o schema das instruções: "
        f'status="{EXPECTED_SOAP_STATUS}", objeto "soap" com subjetivo/objetivo/avaliacao/plano '
        "como STRINGS narrativas, alertas_revisao, evidencias_chave.\n"
        "NÃO use chaves SOAP, S, O, A ou P no nível raiz.\n"
        "NÃO coloque subjetivo, objetivo, avaliacao ou plano fora de soap.\n"
        "NÃO use linha_do_tempo_sintomas; integre a temporalidade no texto de soap.subjetivo."
    )
