from __future__ import annotations

from typing import Any, Mapping

UPLOAD_01_INPUT = "upload_01_input"
UPLOAD_02_NORMALIZE = "upload_02_normalize"
UPLOAD_03_FILTER_ENHANCE = "upload_03_filter_enhance"
UPLOAD_04_OUTPUT = "upload_04_output"
TRANSCRIBE_01_DIARIZATION = "transcribe_01_diarization"
TRANSCRIBE_02_WHISPER = "transcribe_02_whisper"
TRANSCRIBE_03_FORMAT_SPEAKERS = "transcribe_03_format_speakers"
TRANSCRIBE_04_LLM_ASR_FIX = "transcribe_04_llm_asr_fix"
TRANSCRIBE_04B_LLM_DIARIZATION_LABELS = "transcribe_04b_llm_diarization_labels"
TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION = "transcribe_04c_llm_manual_diarization"
TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO = "transcribe_05a_llm_soap_subjetivo"
TRANSCRIBE_05B_LLM_SOAP_OBJETIVO = "transcribe_05b_llm_soap_objetivo"
TRANSCRIBE_05C_LLM_SOAP_AVALIACAO = "transcribe_05c_llm_soap_avaliacao"
TRANSCRIBE_05D_LLM_SOAP_PLANO = "transcribe_05d_llm_soap_plano"
TRANSCRIBE_05E_MERGE_SOAP = "transcribe_05e_merge_soap"
TRANSCRIBE_05_LLM_SOAP = "transcribe_05_llm_soap"

SOAP_LLM_STEP_IDS_SPLIT = (
    TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO,
    TRANSCRIBE_05B_LLM_SOAP_OBJETIVO,
    TRANSCRIBE_05C_LLM_SOAP_AVALIACAO,
    TRANSCRIBE_05D_LLM_SOAP_PLANO,
)

SOAP_LLM_STEP_IDS_SPLIT_WITH_MERGE = SOAP_LLM_STEP_IDS_SPLIT + (TRANSCRIBE_05E_MERGE_SOAP,)

DIARIZATION_PIPELINE_STEP_IDS = frozenset(
    {
        TRANSCRIBE_01_DIARIZATION,
        TRANSCRIBE_03_FORMAT_SPEAKERS,
        TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
    }
)

MANUAL_DIARIZATION_PIPELINE_STEP_IDS = frozenset({TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION})

# Backward-compatible alias (removed combined step)
TRANSCRIBE_04_LLM_IMPROVE_DIARIZATION = TRANSCRIBE_04_LLM_ASR_FIX

PIPELINE_STEPS: dict[str, dict[str, Any]] = {
    UPLOAD_01_INPUT: {
        "order": 1,
        "endpoint": "/upload",
        "label": "Entrada de dados (MP3, WAV)",
    },
    UPLOAD_02_NORMALIZE: {
        "order": 2,
        "endpoint": "/upload",
        "label": "Normalização (Mono, Resampling 16Khz)",
    },
    UPLOAD_03_FILTER_ENHANCE: {
        "order": 3,
        "endpoint": "/upload",
        "label": "Filter/Enhance Audio (eq, pf, hpf, denoise...)",
    },
    UPLOAD_04_OUTPUT: {
        "order": 4,
        "endpoint": "/upload",
        "label": "Output Audio Filtered",
    },
    TRANSCRIBE_01_DIARIZATION: {
        "order": 5,
        "endpoint": "/transcribe",
        "label": "Diarization using nvidia/diar_sortformer_4spk-v1 (NeMo Sortformer)",
    },
    TRANSCRIBE_02_WHISPER: {
        "order": 6,
        "endpoint": "/transcribe",
        "label": "Whisper Inference with prompt",
    },
    TRANSCRIBE_03_FORMAT_SPEAKERS: {
        "order": 7,
        "endpoint": "/transcribe",
        "label": "Diarization process to format Speaker 1 and Speaker 2 in text",
    },
    TRANSCRIBE_04_LLM_ASR_FIX: {
        "order": 8,
        "endpoint": "/transcribe",
        "label": "LLM Process Prompt Improve text (ASR fix)",
    },
    TRANSCRIBE_04B_LLM_DIARIZATION_LABELS: {
        "order": 9,
        "endpoint": "/transcribe",
        "label": "LLM change label Speaker 1 and 2 to Médico/Paciente",
    },
    TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION: {
        "order": 10,
        "endpoint": "/transcribe",
        "label": "LLM manual diarization (no acoustic diarization model) — split into Doutor/Paciente turns",
    },
    TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO: {
        "order": 11,
        "endpoint": "/transcribe",
        "label": "LLM SOAP — Subjetivo (S)",
    },
    TRANSCRIBE_05B_LLM_SOAP_OBJETIVO: {
        "order": 12,
        "endpoint": "/transcribe",
        "label": "LLM SOAP — Objetivo (O)",
    },
    TRANSCRIBE_05C_LLM_SOAP_AVALIACAO: {
        "order": 13,
        "endpoint": "/transcribe",
        "label": "LLM SOAP — Avaliação (A)",
    },
    TRANSCRIBE_05D_LLM_SOAP_PLANO: {
        "order": 14,
        "endpoint": "/transcribe",
        "label": "LLM SOAP — Plano (P)",
    },
    TRANSCRIBE_05E_MERGE_SOAP: {
        "order": 15,
        "endpoint": "/transcribe",
        "label": "Merge SOAP sections (S+O+A+P)",
    },
    TRANSCRIBE_05_LLM_SOAP: {
        "order": 16,
        "endpoint": "/transcribe",
        "label": "LLM SOAP (monolithic, legacy)",
    },
}


def step_meta(step_id: str) -> dict[str, Any]:
    if step_id not in PIPELINE_STEPS:
        raise KeyError(f"Unknown pipeline step: {step_id}")
    return {"step_id": step_id, **PIPELINE_STEPS[step_id]}


def step_filename(step_id: str) -> str:
    order = PIPELINE_STEPS[step_id]["order"]
    return f"{order:02d}_{step_id}.json"


def _config_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).lower() in {"true", "1", "yes"}


def omitted_pipeline_steps_for_config(config: Mapping[str, Any]) -> frozenset[str]:
    """Steps excluded from pipeline debug logs when a feature is disabled."""
    omitted: set[str] = set()
    if not _config_bool(config.get("DIARIZATION_ENABLED"), default=False):
        omitted.update(DIARIZATION_PIPELINE_STEP_IDS)
    if not _config_bool(config.get("MANUAL_DIARIZATION_ENABLED"), default=False):
        omitted.update(MANUAL_DIARIZATION_PIPELINE_STEP_IDS)
    if not soap_enabled_for_config(config):
        omitted.update(SOAP_LLM_STEP_IDS_SPLIT_WITH_MERGE)
        omitted.add(TRANSCRIBE_05_LLM_SOAP)
    elif soap_split_enabled_for_config(config):
        omitted.add(TRANSCRIBE_05_LLM_SOAP)
    else:
        omitted.update(SOAP_LLM_STEP_IDS_SPLIT_WITH_MERGE)
    return frozenset(omitted)


def soap_enabled_for_config(config: Mapping[str, Any]) -> bool:
    return _config_bool(config.get("SOAP_ENABLED"), default=True)


def soap_split_enabled_for_config(config: Mapping[str, Any]) -> bool:
    return _config_bool(config.get("SOAP_SPLIT_ENABLED"), default=True)


def prompt_compact_for_config(config: Mapping[str, Any]) -> bool:
    if "PROMPT_COMPACT" in config:
        return _config_bool(config.get("PROMPT_COMPACT"), default=False)
    return _config_bool(config.get("SOAP_PROMPT_COMPACT"), default=False)


def soap_prompt_compact_for_config(config: Mapping[str, Any]) -> bool:
    return prompt_compact_for_config(config)
