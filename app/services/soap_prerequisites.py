from __future__ import annotations

from typing import Any, Mapping

from app.services.llm_client import resolve_llm_settings
from app.services.transcript_postprocess import ASR_FIX_DISABLED_ERROR


def can_generate_soap(
    postprocess_result: Mapping[str, Any],
    *,
    diarization_enabled: bool,
) -> tuple[bool, str]:
    """SOAP requires successful ASR fix (or ASR fix disabled) and label pass when diarized."""
    if postprocess_result.get("skipped"):
        return False, str(postprocess_result.get("error") or "postprocess_skipped")

    asr_fix = postprocess_result.get("asr_fix") or {}
    if asr_fix.get("skipped"):
        asr_error = str(asr_fix.get("error") or "asr_fix_skipped")
        if asr_error != ASR_FIX_DISABLED_ERROR:
            return False, asr_error

    if diarization_enabled:
        labels = postprocess_result.get("diarization_labels") or {}
        if labels.get("skipped"):
            error = str(labels.get("error") or "diarization_labels_skipped")
            if error not in {"diarization_disabled", "diarization_labels_disabled"}:
                return False, error

    return True, ""


def soap_draft_skipped_result(
    *,
    config: Mapping[str, Any],
    segmented_transcript: str = "",
    diarization_enabled: bool = False,
    postprocess_applied: bool = False,
    error: str,
) -> dict[str, Any]:
    llm = resolve_llm_settings(config)
    prompt_path_raw = config.get("SOAP_DRAFT_PROMPT_PATH")
    from pathlib import Path

    from app.services.soap_draft import DEFAULT_SOAP_PROMPTS_DIR, ROOT, SOAP_SECTIONS

    split_enabled = str(config.get("SOAP_SPLIT_ENABLED", "true")).lower() in {"true", "1", "yes"}
    if split_enabled:
        prompts_dir_raw = config.get("SOAP_PROMPTS_DIR", "benchmarks/prompts")
        prompts_dir = Path(prompts_dir_raw)
        if not prompts_dir.is_absolute():
            prompts_dir = ROOT / prompts_dir
        prompt_path = (prompts_dir / SOAP_SECTIONS[0].prompt_filename).resolve()
    else:
        prompt_path = Path(prompt_path_raw) if prompt_path_raw else DEFAULT_SOAP_PROMPTS_DIR / "soap-draft.md"
        if not prompt_path.is_absolute():
            prompt_path = ROOT / prompt_path

    return {
        "text": segmented_transcript,
        "provider": llm["provider"],
        "model": llm["model"],
        "base_url": llm["base_url"],
        "prompt_path": str(prompt_path.resolve()),
        "skipped": True,
        "error": error,
        "raw": None,
        "document": None,
        "diarization_enabled": diarization_enabled,
        "postprocess_applied": postprocess_applied,
        "validation_errors": None,
    }
