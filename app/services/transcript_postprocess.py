from __future__ import annotations

import difflib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from app.services.llm_client import medgemma_generate, resolve_llm_settings
from app.services.pipeline_steps import (
    TRANSCRIBE_04_LLM_ASR_FIX,
    TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
    TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION,
    prompt_compact_for_config,
)
from app.services.prompt_format import compact_prompt_text

if TYPE_CHECKING:
    from app.services.pipeline_tracker import PipelineTracker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT_PATH = ROOT / "benchmarks" / "prompts" / "medical-transcript-editor.md"
DEFAULT_COMPACT_PROMPT_PATH = ROOT / "benchmarks" / "prompts" / "medical-transcript-editor-compact.md"
DEFAULT_DIARIZATION_LABEL_PROMPT_PATH = (
    ROOT / "benchmarks" / "prompts" / "medical-transcript-diarization-labels.md"
)
DEFAULT_MANUAL_DIARIZATION_PROMPT_PATH = (
    ROOT / "benchmarks" / "prompts" / "medical-transcript-manual-diarization.md"
)
DEFAULT_ASR_SYSTEM_PROMPT = (
    "Você é um editor de transcrições médicas em português brasileiro. "
    "Siga as instruções detalhadas na mensagem do usuário."
)
DEFAULT_DIARIZATION_LABEL_SYSTEM_PROMPT = (
    "Você é um formatador de diálogo médico em português brasileiro. "
    "Siga as instruções detalhadas na mensagem do usuário."
)
DEFAULT_MANUAL_DIARIZATION_SYSTEM_PROMPT = (
    "Você é um formatador de diálogo médico em português brasileiro. "
    "Siga as instruções detalhadas na mensagem do usuário."
)
DEFAULT_MANUAL_DIARIZATION_MIN_WORD_RATIO = 0.90
ASR_USER_INSTRUCTIONS_SEPARATOR = "\n\n---\n\n"
ASR_FIX_DISABLED_ERROR = "asr_fix_disabled"

DEFAULT_ASR_FIX_MIN_WORD_RATIO = 0.90
DEFAULT_ASR_FIX_MIN_SPEAKER_LINE_RATIO = 0.90
DEFAULT_ASR_FIX_CHUNK_MAX_WORDS = 450
DEFAULT_ASR_FIX_CHUNK_MAX_WORKERS = 2
_EDITOR_ROLE_PREAMBLE_RE = re.compile(
    r"^Você é um editor de transcrições médicas.*?"
    r"Você corrige erros de transcrição; não é clínico e não inventa fatos clínicos\.\s*",
    re.I | re.S,
)
_SPEAKER_LINE_RE = re.compile(r"^(?:Falante\s+\d+|SPEAKER_\d+)\s*:", re.IGNORECASE)
_FALANTE_1_RE = re.compile(r"^Falante\s+1\s*:", re.IGNORECASE)
_FALANTE_2_RE = re.compile(r"^Falante\s+2\s*:", re.IGNORECASE)

DEFAULT_DIARIZATION_LABEL_SAMPLE_RATIO = 0.15
DIARIZATION_LABEL_SAMPLE_RATIO_CAP = 0.30
DIARIZATION_LABEL_SAMPLE_MIN_LINES = 20
DIARIZATION_LABEL_VALID_ROLES = {"Médico", "Paciente"}


def _editor_prompt_source_path(
    *,
    prompt_path: Path | None,
    prompt_compact: bool,
) -> Path:
    """Resolve which editor rules file to load (compact file when enabled)."""
    resolved = (prompt_path or DEFAULT_PROMPT_PATH).resolve()
    if prompt_compact and resolved == DEFAULT_PROMPT_PATH.resolve():
        compact_path = DEFAULT_COMPACT_PROMPT_PATH.resolve()
        if compact_path.is_file():
            return compact_path
    return resolved


def load_editor_prompt(*, prompt_path: Path | None = None, prompt_compact: bool = False) -> str:
    path = _editor_prompt_source_path(prompt_path=prompt_path, prompt_compact=prompt_compact)
    if not path.is_file():
        raise FileNotFoundError(f"Editor prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _strip_editor_role_preamble(text: str) -> str:
    """Drop role intro duplicated in the short LLM system_prompt."""
    stripped = _EDITOR_ROLE_PREAMBLE_RE.sub("", text.strip(), count=1).strip()
    return stripped or text.strip()


def resolve_asr_system_prompt(override: str | None = None) -> str:
    """Short system role sent to the LLM; detailed editor rules go in the user prompt."""
    if override and str(override).strip():
        return str(override).strip()
    return DEFAULT_ASR_SYSTEM_PROMPT


def resolve_diarization_label_system_prompt(override: str | None = None) -> str:
    if override and str(override).strip():
        return str(override).strip()
    return DEFAULT_DIARIZATION_LABEL_SYSTEM_PROMPT


def resolve_manual_diarization_system_prompt(override: str | None = None) -> str:
    if override and str(override).strip():
        return str(override).strip()
    return DEFAULT_MANUAL_DIARIZATION_SYSTEM_PROMPT


def compose_asr_user_prompt(
    instructions: str,
    user_message: str,
    *,
    prompt_compact: bool = False,
) -> str:
    """Prepend editor / label instructions before transcript and task text."""
    instructions_text = instructions.strip()
    user_text = user_message.strip()
    if not instructions_text:
        return user_text
    if not user_text:
        return instructions_text
    separator = "\n\n" if prompt_compact else ASR_USER_INSTRUCTIONS_SEPARATOR
    return f"{instructions_text}{separator}{user_text}"


def _finalize_postprocess_instructions(text: str, *, prompt_compact: bool) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    if prompt_compact:
        return compact_prompt_text(_strip_editor_role_preamble(normalized))
    return _strip_editor_role_preamble(normalized)


def _config_bool(raw: Any, *, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in {"true", "1", "yes"}


def resolve_asr_fix_chunk_settings(
    config: Mapping[str, Any] | None = None,
) -> dict[str, int | bool]:
    if not config:
        return {
            "chunk_max_words": DEFAULT_ASR_FIX_CHUNK_MAX_WORDS,
            "chunk_parallel": True,
            "chunk_max_workers": DEFAULT_ASR_FIX_CHUNK_MAX_WORKERS,
        }
    raw = config.get("ASR_FIX_CHUNK_MAX_WORDS")
    if raw is None:
        chunk_max_words = DEFAULT_ASR_FIX_CHUNK_MAX_WORDS
    else:
        try:
            chunk_max_words = max(0, int(raw))
        except (TypeError, ValueError):
            chunk_max_words = DEFAULT_ASR_FIX_CHUNK_MAX_WORDS

    raw_workers = config.get("ASR_FIX_CHUNK_MAX_WORKERS")
    if raw_workers is None:
        chunk_max_workers = DEFAULT_ASR_FIX_CHUNK_MAX_WORKERS
    else:
        try:
            chunk_max_workers = max(1, int(raw_workers))
        except (TypeError, ValueError):
            chunk_max_workers = DEFAULT_ASR_FIX_CHUNK_MAX_WORKERS

    return {
        "chunk_max_words": chunk_max_words,
        "chunk_parallel": _config_bool(config.get("ASR_FIX_CHUNK_PARALLEL"), default=True),
        "chunk_max_workers": chunk_max_workers,
    }


def _split_transcript_for_asr_fix(text: str, *, max_words: int) -> list[str]:
    stripped = text.strip()
    if max_words <= 0 or len(stripped.split()) <= max_words:
        return [stripped]

    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", stripped):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for part in re.split(r"(?<=[.!?])\s+", paragraph):
            part = part.strip()
            if part:
                units.append(part)

    if not units:
        units = [stripped]

    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for unit in units:
        unit_words = len(unit.split())
        if unit_words > max_words:
            if current:
                chunks.append(" ".join(current))
                current = []
                count = 0
            words = unit.split()
            for index in range(0, len(words), max_words):
                chunks.append(" ".join(words[index : index + max_words]))
            continue
        if count + unit_words > max_words and current:
            chunks.append(" ".join(current))
            current = [unit]
            count = unit_words
        else:
            current.append(unit)
            count += unit_words
    if current:
        chunks.append(" ".join(current))
    return chunks or [stripped]


def asr_fix_enabled_for_config(config: Mapping[str, Any]) -> bool:
    raw = config.get("ASR_FIX_ENABLED")
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in {"true", "1", "yes"}


def diarization_labels_enabled(config: Mapping[str, Any]) -> bool:
    raw = config.get("TRANSCRIPT_DIARIZATION_LABELS_ENABLED")
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in {"true", "1", "yes"}


def diarization_labels_applied(postprocess_result: Mapping[str, Any]) -> bool:
    """True when step 04b ran and produced Médico:/Paciente: text."""
    labels = postprocess_result.get("diarization_labels") or {}
    if labels.get("skipped"):
        return False
    return not labels.get("error")


def load_diarization_label_prompt(*, prompt_path: Path | None = None) -> str:
    path = (prompt_path or DEFAULT_DIARIZATION_LABEL_PROMPT_PATH).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Diarization label prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def manual_diarization_enabled(config: Mapping[str, Any]) -> bool:
    """LLM-only diarization (no acoustic diarization model): split plain text into Doutor:/Paciente: turns."""
    raw = config.get("MANUAL_DIARIZATION_ENABLED")
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in {"true", "1", "yes"}


def manual_diarization_applied(postprocess_result: Mapping[str, Any]) -> bool:
    """True when the manual diarization step ran and produced Doutor:/Paciente: text."""
    manual = postprocess_result.get("manual_diarization") or {}
    if manual.get("skipped"):
        return False
    return not manual.get("error")


def load_manual_diarization_prompt(*, prompt_path: Path | None = None) -> str:
    path = (prompt_path or DEFAULT_MANUAL_DIARIZATION_PROMPT_PATH).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Manual diarization prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _resolve_prompt_path(raw: str | None, *, default: Path) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def count_speaker_lines(text: str) -> int:
    return sum(
        1
        for line in text.splitlines()
        if _SPEAKER_LINE_RE.match(line.strip())
    )


def resolve_asr_fix_guardrail_settings(
    config: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    if not config:
        return {
            "min_word_ratio": DEFAULT_ASR_FIX_MIN_WORD_RATIO,
            "min_speaker_line_ratio": DEFAULT_ASR_FIX_MIN_SPEAKER_LINE_RATIO,
        }

    def _ratio(key: str, default: float) -> float:
        raw = config.get(key)
        if raw is None:
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        return min(1.0, max(0.0, value))

    return {
        "min_word_ratio": _ratio("ASR_FIX_MIN_WORD_RATIO", DEFAULT_ASR_FIX_MIN_WORD_RATIO),
        "min_speaker_line_ratio": _ratio(
            "ASR_FIX_MIN_SPEAKER_LINE_RATIO",
            DEFAULT_ASR_FIX_MIN_SPEAKER_LINE_RATIO,
        ),
    }


def asr_fix_output_passes_guardrail(
    before: str,
    after: str,
    *,
    min_word_ratio: float = DEFAULT_ASR_FIX_MIN_WORD_RATIO,
    min_speaker_line_ratio: float = DEFAULT_ASR_FIX_MIN_SPEAKER_LINE_RATIO,
) -> tuple[bool, str | None]:
    before_stripped = before.strip()
    after_stripped = after.strip()
    if before_stripped == after_stripped:
        return True, None
    if not after_stripped:
        return False, "empty_llm_output"

    before_words = len(before_stripped.split())
    after_words = len(after_stripped.split())
    if before_words > 0:
        word_ratio = after_words / before_words
        if word_ratio < min_word_ratio:
            return False, (
                f"word_count_ratio_below_threshold:{word_ratio:.3f}<{min_word_ratio:.3f}"
            )

    before_speaker_lines = count_speaker_lines(before_stripped)
    if before_speaker_lines >= 10:
        after_speaker_lines = count_speaker_lines(after_stripped)
        line_ratio = after_speaker_lines / before_speaker_lines
        if line_ratio < min_speaker_line_ratio:
            return False, (
                "speaker_line_ratio_below_threshold:"
                f"{line_ratio:.3f}<{min_speaker_line_ratio:.3f}"
            )

    return True, None


def _build_asr_user_message(
    text: str,
    *,
    preprocessing_stages: list[str] | None = None,
    preserve_speaker_labels: bool = False,
    prompt_compact: bool = False,
) -> str:
    parts: list[str] = []
    if preprocessing_stages:
        stages_label = ", ".join(preprocessing_stages)
        parts.append(
            "Audio preprocessing stages applied before ASR (context only, do not edit): "
            f"{stages_label}"
        )
        parts.append("")
    if preserve_speaker_labels:
        parts.append(
            "The transcript uses generic diarization labels (Falante 1: / Falante 2:). "
            "Fix ASR word errors only. Keep every Falante 1:/Falante 2: line prefix unchanged. "
            "Do not rename speakers or split lines — that happens in a later step."
        )
        parts.append("")
    parts.append(
        "Post-edit the following ASR transcript per your rules. "
        "Change only clear word-level ASR errors (spelling, accents, hyphens inside words). "
        "Never add or remove punctuation (. , ? ! ; :) or change capitalization."
    )
    parts.append("")
    if prompt_compact:
        parts.append(text.strip())
    else:
        parts.append(f"<<<\n{text.strip()}\n>>>")
    return "\n".join(parts)


def _sample_for_diarization_labels(
    text: str,
    *,
    ratio: float = DEFAULT_DIARIZATION_LABEL_SAMPLE_RATIO,
    ratio_cap: float = DIARIZATION_LABEL_SAMPLE_RATIO_CAP,
    min_lines: int = DIARIZATION_LABEL_SAMPLE_MIN_LINES,
) -> str:
    """First ~ratio of the transcript (by line count) — enough for the LLM to see both
    speakers and classify roles, without sending the whole transcript. Extends up to
    ratio_cap if the initial slice doesn't contain both Falante 1: and Falante 2: lines
    (e.g. one speaker doesn't talk until later). Transcripts at or under min_lines are
    returned whole — too short for percentage-based sampling to matter."""
    lines = text.splitlines()
    total = len(lines)
    if total <= min_lines:
        return text

    def _has_both(count: int) -> bool:
        subset = lines[:count]
        has_1 = any(_FALANTE_1_RE.match(line.strip()) for line in subset)
        has_2 = any(_FALANTE_2_RE.match(line.strip()) for line in subset)
        return has_1 and has_2

    cap = max(min_lines, round(total * ratio_cap))
    step = max(1, round(total * 0.05))
    n = max(min_lines, round(total * ratio))

    while n < cap and not _has_both(n):
        n += step

    return "\n".join(lines[: min(n, cap, total)])


def _parse_diarization_label_mapping(raw: str) -> dict[str, str] | None:
    try:
        data = json.loads(raw.strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    falante_1 = str(data.get("falante_1", "")).strip()
    falante_2 = str(data.get("falante_2", "")).strip()
    if falante_1 not in DIARIZATION_LABEL_VALID_ROLES:
        return None
    if falante_2 not in DIARIZATION_LABEL_VALID_ROLES:
        return None
    if falante_1 == falante_2:
        return None

    return {"Falante 1": falante_1, "Falante 2": falante_2}


def _apply_diarization_label_mapping(text: str, mapping: dict[str, str]) -> str:
    out_lines: list[str] = []
    for line in text.splitlines():
        if _FALANTE_1_RE.match(line):
            rest = _FALANTE_1_RE.sub("", line, count=1).lstrip()
            out_lines.append(f"{mapping['Falante 1']}: {rest}")
        elif _FALANTE_2_RE.match(line):
            rest = _FALANTE_2_RE.sub("", line, count=1).lstrip()
            out_lines.append(f"{mapping['Falante 2']}: {rest}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def apply_diarization_label_mapping_to_segments(
    segments: list[dict[str, Any]], mapping: dict[str, str]
) -> list[dict[str, Any]]:
    """Rewrite each segment's speaker_label with the same Falante→role mapping applied to
    the flat transcript text (label_diarized_transcript), so the per-segment view (frontend
    transcript panel) and the merged text (SOAP) never disagree on who's who."""
    return [
        {**segment, "speaker_label": mapping.get(segment.get("speaker_label"), segment.get("speaker_label"))}
        for segment in segments
    ]


def _build_diarization_label_user_message(sample_text: str, *, prompt_compact: bool = False) -> str:
    if prompt_compact:
        return "\n".join(
            [
                "Identify which Falante is Médico and which is Paciente. Reply with the JSON only.",
                sample_text.strip(),
            ]
        )
    parts = [
        "The excerpt below is a SAMPLE from the start of a diarized transcript — not the whole "
        "consultation, just enough to tell who is who. Lines still use Falante 1: / Falante 2: labels.",
        "Decide which Falante is Médico and which is Paciente per your rules.",
        "",
        "TRECHO:",
        "<<<",
        sample_text.strip(),
        ">>>",
        "FIM DO TRECHO.",
    ]
    return "\n".join(parts)


def _build_manual_diarization_user_message(
    text: str,
    *,
    prompt_compact: bool = False,
    previous_tail: str | None = None,
) -> str:
    continuation_note = None
    if previous_tail:
        continuation_note = (
            "Isto é a continuação da MESMA consulta — não é um texto novo. "
            "As últimas falas já processadas do trecho anterior foram:\n"
            f"{previous_tail}\n"
            "Mantenha a MESMA pessoa como Doutor e a MESMA como Paciente que já foi "
            "estabelecida acima. NÃO repita essas linhas na sua saída — comece a "
            "rotular a partir do texto novo abaixo."
        )
    if prompt_compact:
        parts = ["Split into Doutor:/Paciente: turns per your rules. No existing speaker labels."]
        if continuation_note:
            parts.append(continuation_note)
        parts.append(text.strip())
        return "\n".join(parts)
    parts = [
        "The transcript below was ASR-corrected and has NO speaker labels at all.",
        "Split it into Doutor: / Paciente: turns per your rules.",
        "Do not change wording — only cut into lines and label them.",
    ]
    if continuation_note:
        parts.append("")
        parts.append(continuation_note)
    parts += [
        "",
        "TRANSCRIÇÃO:",
        "<<<",
        text.strip(),
        ">>>",
        "FIM DA TRANSCRIÇÃO.",
    ]
    return "\n".join(parts)


def summarize_text_diff(before: str, after: str, *, max_changes: int = 100) -> dict[str, Any]:
    before_stripped = before.strip()
    after_stripped = after.strip()
    before_words = before_stripped.split()
    after_words = after_stripped.split()
    matcher = difflib.SequenceMatcher(None, before_words, after_words)

    changes: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append(
            {
                "op": tag,
                "before": " ".join(before_words[i1:i2]),
                "after": " ".join(after_words[j1:j2]),
            }
        )

    return {
        "changed": before_stripped != after_stripped,
        "word_count_before": len(before_words),
        "word_count_after": len(after_words),
        "change_count": len(changes),
        "changes": changes[:max_changes],
    }


def format_diff_log(diff: dict[str, Any], *, stack_id: str | None = None) -> str:
    prefix = f"[postprocess:{stack_id}] " if stack_id else "[postprocess] "
    lines = [
        f"{prefix}before={diff['word_count_before']} words "
        f"after={diff['word_count_after']} words "
        f"changes={diff['change_count']}",
    ]
    if not diff.get("changed"):
        lines.append(f"{prefix}(no text changes)")
        return "\n".join(lines)

    for index, change in enumerate(diff.get("changes", []), start=1):
        op = change["op"]
        before = change.get("before") or "(empty)"
        after = change.get("after") or "(empty)"
        if op == "replace":
            lines.append(f"{prefix}{index}. replace: {before!r} -> {after!r}")
        elif op == "delete":
            lines.append(f"{prefix}{index}. delete: {before!r}")
        elif op == "insert":
            lines.append(f"{prefix}{index}. insert: {after!r}")
        else:
            lines.append(f"{prefix}{index}. {op}: {before!r} -> {after!r}")

    if diff["change_count"] > len(diff.get("changes", [])):
        remaining = diff["change_count"] - len(diff["changes"])
        lines.append(f"{prefix}... {remaining} more change(s) not shown")
    return "\n".join(lines)


def save_postprocess_diff_file(
    path: Path,
    *,
    raw_text: str,
    corrected_text: str,
    diff: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    label: str | None = None,
) -> Path:
    """Write a human-readable before/after report for LLM post-edit changes."""
    diff_report = diff or summarize_text_diff(raw_text, corrected_text)
    lines: list[str] = ["LLM postprocess diff report", ""]

    if meta:
        for key, value in meta.items():
            lines.append(f"{key}: {value}")
        lines.append("")

    lines.append(format_diff_log(diff_report, stack_id=label))
    lines.extend(
        [
            "",
            "=" * 72,
            "BEFORE (Whisper raw)",
            "=" * 72,
            raw_text.strip(),
            "",
            "=" * 72,
            "AFTER (LLM corrected)",
            "=" * 72,
            corrected_text.strip(),
            "",
        ]
    )
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _llm_stage_result(
    *,
    text: str,
    provider: str,
    model: str,
    base_url: str,
    preprocessing_stages: list[str] | None,
    diarization_enabled: bool,
) -> dict[str, Any]:
    return {
        "text": text,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "skipped": True,
        "error": None,
        "preprocessing_stages": preprocessing_stages or [],
        "diarization_enabled": diarization_enabled,
    }


def edit_transcript(
    text: str,
    *,
    enabled: bool = False,
    provider: str = "phihc",
    model: str = "gemma3:12b-it-qat",
    base_url: str,
    api_key: str = "",
    system_prompt: str | None = None,
    prompt_path: Path | None = None,
    preprocessing_stages: list[str] | None = None,
    preserve_speaker_labels: bool = False,
    temperature: float = 0,
    tracker: PipelineTracker | None = None,
    tracker_step_id: str = TRANSCRIBE_04_LLM_ASR_FIX,
    timeout: int = 600,
    min_word_ratio: float = DEFAULT_ASR_FIX_MIN_WORD_RATIO,
    min_speaker_line_ratio: float = DEFAULT_ASR_FIX_MIN_SPEAKER_LINE_RATIO,
    prompt_compact: bool = False,
    chunk_max_words: int = 0,
    chunk_parallel: bool = True,
    chunk_max_workers: int = DEFAULT_ASR_FIX_CHUNK_MAX_WORKERS,
    max_retries: int = 2,
) -> dict[str, Any]:
    result = _llm_stage_result(
        text=text,
        provider=provider,
        model=model,
        base_url=base_url,
        preprocessing_stages=preprocessing_stages,
        diarization_enabled=preserve_speaker_labels,
    )

    if not enabled:
        result["error"] = "postprocess_disabled"
        if tracker:
            tracker.skip(tracker_step_id, reason="postprocess_disabled")
        return result

    if not text.strip():
        result["error"] = "empty_transcript"
        if tracker:
            tracker.skip(tracker_step_id, reason="empty_transcript")
        return result

    if not base_url.strip():
        result["error"] = "missing_llm_base_url"
        if tracker:
            tracker.skip(tracker_step_id, reason="missing_llm_base_url")
        return result

    if not str(api_key or "").strip():
        result["error"] = "missing_llm_api_key"
        if tracker:
            tracker.skip(tracker_step_id, reason="missing_llm_api_key")
        return result

    chunks = _split_transcript_for_asr_fix(text, max_words=chunk_max_words)
    if len(chunks) > 1:
        return _edit_transcript_chunked(
            chunks,
            original_text=text.strip(),
            result=result,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=system_prompt,
            prompt_path=prompt_path,
            preprocessing_stages=preprocessing_stages,
            preserve_speaker_labels=preserve_speaker_labels,
            temperature=temperature,
            tracker=tracker,
            tracker_step_id=tracker_step_id,
            timeout=timeout,
            min_word_ratio=min_word_ratio,
            min_speaker_line_ratio=min_speaker_line_ratio,
            prompt_compact=prompt_compact,
            chunk_parallel=chunk_parallel,
            chunk_max_workers=chunk_max_workers,
            max_retries=max_retries,
        )

    return _edit_transcript_single(
        text,
        result=result,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prompt=system_prompt,
        prompt_path=prompt_path,
        preprocessing_stages=preprocessing_stages,
        preserve_speaker_labels=preserve_speaker_labels,
        temperature=temperature,
        tracker=tracker,
        tracker_step_id=tracker_step_id,
        timeout=timeout,
        min_word_ratio=min_word_ratio,
        min_speaker_line_ratio=min_speaker_line_ratio,
        prompt_compact=prompt_compact,
        tracker_record_step=True,
        chunk_index=None,
        chunk_count=None,
        max_retries=max_retries,
    )


def _resolve_editor_prompt_path(
    *,
    prompt_path: Path | None,
    prompt_compact: bool,
) -> Path:
    return _editor_prompt_source_path(prompt_path=prompt_path, prompt_compact=prompt_compact)


def _edit_transcript_single(
    text: str,
    *,
    result: dict[str, Any],
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str | None,
    prompt_path: Path | None,
    preprocessing_stages: list[str] | None,
    preserve_speaker_labels: bool,
    temperature: float,
    tracker: PipelineTracker | None,
    tracker_step_id: str,
    timeout: int,
    min_word_ratio: float,
    min_speaker_line_ratio: float,
    prompt_compact: bool,
    tracker_record_step: bool,
    chunk_index: int | None,
    chunk_count: int | None,
    max_retries: int = 2,
) -> dict[str, Any]:
    resolved_prompt_path = _resolve_editor_prompt_path(
        prompt_path=prompt_path,
        prompt_compact=prompt_compact,
    )
    try:
        instructions = _finalize_postprocess_instructions(
            system_prompt or load_editor_prompt(
                prompt_path=prompt_path,
                prompt_compact=prompt_compact,
            ),
            prompt_compact=prompt_compact,
        )
        task_message = _build_asr_user_message(
            text,
            preprocessing_stages=preprocessing_stages,
            preserve_speaker_labels=preserve_speaker_labels,
            prompt_compact=prompt_compact,
        )
        user_prompt = compose_asr_user_prompt(
            instructions,
            task_message,
            prompt_compact=prompt_compact,
        )
        llm_system_prompt = resolve_asr_system_prompt()
        request_meta: dict[str, Any] = {
            "prompt_path": str(resolved_prompt_path),
            "preserve_speaker_labels": preserve_speaker_labels,
            "preprocessing_stages": preprocessing_stages or [],
            "prompt_compact": prompt_compact,
            "prompt_chars": len(user_prompt),
            "transcript_words": len(text.split()),
        }
        if chunk_index is not None:
            request_meta["chunk_index"] = chunk_index
            request_meta["chunk_count"] = chunk_count
        corrected, llm_raw = medgemma_generate(
            prompt=user_prompt,
            system_prompt=llm_system_prompt,
            model=model,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            temperature=temperature,
            force_json=False,
            timeout=timeout,
            max_retries=max_retries,
            return_raw=True,
            tracker=tracker,
            tracker_step_id=tracker_step_id,
            tracker_record_step=tracker_record_step,
            tracker_request_meta=request_meta,
        )
    except Exception as exc:
        result["error"] = str(exc)
        return result

    original_text = text.strip()
    corrected_stripped = corrected.strip()
    passes, guardrail_reason = asr_fix_output_passes_guardrail(
        original_text,
        corrected_stripped,
        min_word_ratio=min_word_ratio,
        min_speaker_line_ratio=min_speaker_line_ratio,
    )

    guardrail: dict[str, Any] = {"rejected": False}
    if passes:
        final_text = corrected_stripped
    else:
        guardrail = {
            "rejected": True,
            "reason": guardrail_reason,
            "input_word_count": len(original_text.split()),
            "llm_word_count": len(corrected_stripped.split()),
            "input_speaker_lines": count_speaker_lines(original_text),
            "llm_speaker_lines": count_speaker_lines(corrected_stripped),
            "min_word_ratio": min_word_ratio,
            "min_speaker_line_ratio": min_speaker_line_ratio,
        }
        final_text = original_text

    result["text"] = final_text
    result["llm_raw"] = llm_raw
    result["guardrail"] = guardrail
    result["skipped"] = False
    result["diff"] = summarize_text_diff(original_text, final_text)
    if guardrail.get("rejected"):
        result["diff"]["guardrail_rejected"] = True
        result["diff"]["guardrail_reason"] = guardrail_reason
        result["diff"]["llm_word_count"] = guardrail["llm_word_count"]
    if tracker and tracker_step_id and guardrail.get("rejected"):
        tracker.amend(
            tracker_step_id,
            response={
                "guardrail": guardrail,
                "text": final_text,
                "diff": result["diff"],
            },
            error=None,
        )
    return result


def _edit_transcript_chunked(
    chunks: list[str],
    *,
    original_text: str,
    result: dict[str, Any],
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str | None,
    prompt_path: Path | None,
    preprocessing_stages: list[str] | None,
    preserve_speaker_labels: bool,
    temperature: float,
    tracker: PipelineTracker | None,
    tracker_step_id: str,
    timeout: int,
    min_word_ratio: float,
    min_speaker_line_ratio: float,
    prompt_compact: bool,
    chunk_parallel: bool = True,
    chunk_max_workers: int = DEFAULT_ASR_FIX_CHUNK_MAX_WORKERS,
    max_retries: int = 2,
) -> dict[str, Any]:
    chunk_count = len(chunks)
    use_parallel = chunk_parallel and chunk_count > 1
    started = time.perf_counter()

    def run_chunk(index: int, chunk: str) -> tuple[int, dict[str, Any]]:
        chunk_result = _edit_transcript_single(
            chunk,
            result=dict(result),
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=system_prompt,
            prompt_path=prompt_path,
            preprocessing_stages=preprocessing_stages if index == 1 else None,
            preserve_speaker_labels=preserve_speaker_labels,
            temperature=temperature,
            tracker=tracker,
            tracker_step_id=tracker_step_id,
            timeout=timeout,
            min_word_ratio=min_word_ratio,
            min_speaker_line_ratio=min_speaker_line_ratio,
            prompt_compact=prompt_compact,
            tracker_record_step=False,
            chunk_index=index,
            chunk_count=chunk_count,
            max_retries=max_retries,
        )
        return index, chunk_result

    results_by_index: dict[int, dict[str, Any]] = {}

    if use_parallel:
        workers = min(chunk_count, max(1, chunk_max_workers))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(run_chunk, index, chunk)
                for index, chunk in enumerate(chunks, start=1)
            ]
            for future in as_completed(futures):
                index, chunk_result = future.result()
                if chunk_result.get("error"):
                    chunk_result["chunking"] = {
                        "enabled": True,
                        "parallel": True,
                        "chunk_count": chunk_count,
                        "failed_chunk": index,
                    }
                    return chunk_result
                results_by_index[index] = chunk_result
    else:
        for index, chunk in enumerate(chunks, start=1):
            index, chunk_result = run_chunk(index, chunk)
            if chunk_result.get("error"):
                chunk_result["chunking"] = {
                    "enabled": True,
                    "parallel": False,
                    "chunk_count": chunk_count,
                    "failed_chunk": index,
                }
                return chunk_result
            results_by_index[index] = chunk_result

    corrected_parts = [str(results_by_index[i]["text"]) for i in range(1, chunk_count + 1)]
    raw_parts = [str(results_by_index[i].get("llm_raw") or "") for i in range(1, chunk_count + 1)]

    merged_text = " ".join(part.strip() for part in corrected_parts if part.strip())
    passes, guardrail_reason = asr_fix_output_passes_guardrail(
        original_text,
        merged_text,
        min_word_ratio=min_word_ratio,
        min_speaker_line_ratio=min_speaker_line_ratio,
    )

    guardrail: dict[str, Any] = {"rejected": False}
    if passes:
        final_text = merged_text
    else:
        guardrail = {
            "rejected": True,
            "reason": guardrail_reason,
            "input_word_count": len(original_text.split()),
            "llm_word_count": len(merged_text.split()),
            "input_speaker_lines": count_speaker_lines(original_text),
            "llm_speaker_lines": count_speaker_lines(merged_text),
            "min_word_ratio": min_word_ratio,
            "min_speaker_line_ratio": min_speaker_line_ratio,
        }
        final_text = original_text

    result["text"] = final_text
    result["llm_raw"] = "\n---\n".join(raw_parts)
    result["guardrail"] = guardrail
    result["skipped"] = False
    result["chunking"] = {
        "enabled": True,
        "parallel": use_parallel,
        "chunk_count": chunk_count,
        "chunk_max_words": max(len(chunk.split()) for chunk in chunks),
    }
    result["diff"] = summarize_text_diff(original_text, final_text)
    if guardrail.get("rejected"):
        result["diff"]["guardrail_rejected"] = True
        result["diff"]["guardrail_reason"] = guardrail_reason
        result["diff"]["llm_word_count"] = guardrail["llm_word_count"]
    if tracker and tracker_step_id:
        tracker.record(
            tracker_step_id,
            request={"chunking": result["chunking"]},
            response={
                "chunking": result["chunking"],
                "guardrail": guardrail,
                "text": final_text,
                "diff": result["diff"],
            },
            duration_ms=(time.perf_counter() - started) * 1000,
            error=None,
        )
    return result


def label_diarized_transcript(
    text: str,
    *,
    enabled: bool = False,
    provider: str = "phihc",
    model: str = "gemma3:12b-it-qat",
    base_url: str,
    api_key: str = "",
    system_prompt: str | None = None,
    prompt_path: Path | None = None,
    temperature: float = 0,
    timeout: int = 600,
    tracker: PipelineTracker | None = None,
    prompt_compact: bool = False,
) -> dict[str, Any]:
    result = _llm_stage_result(
        text=text,
        provider=provider,
        model=model,
        base_url=base_url,
        preprocessing_stages=None,
        diarization_enabled=True,
    )

    if not enabled:
        result["error"] = "postprocess_disabled"
        if tracker:
            tracker.skip(TRANSCRIBE_04B_LLM_DIARIZATION_LABELS, reason="postprocess_disabled")
        return result

    if not text.strip():
        result["error"] = "empty_transcript"
        if tracker:
            tracker.skip(TRANSCRIBE_04B_LLM_DIARIZATION_LABELS, reason="empty_transcript")
        return result

    if not base_url.strip():
        result["error"] = "missing_llm_base_url"
        if tracker:
            tracker.skip(TRANSCRIBE_04B_LLM_DIARIZATION_LABELS, reason="missing_llm_base_url")
        return result

    if not str(api_key or "").strip():
        result["error"] = "missing_llm_api_key"
        if tracker:
            tracker.skip(TRANSCRIBE_04B_LLM_DIARIZATION_LABELS, reason="missing_llm_api_key")
        return result

    resolved_prompt_path = (prompt_path or DEFAULT_DIARIZATION_LABEL_PROMPT_PATH).resolve()
    sample = _sample_for_diarization_labels(text)
    try:
        instructions = _finalize_postprocess_instructions(
            system_prompt or load_diarization_label_prompt(prompt_path=prompt_path),
            prompt_compact=prompt_compact,
        )
        task_message = _build_diarization_label_user_message(sample, prompt_compact=prompt_compact)
        user_prompt = compose_asr_user_prompt(
            instructions,
            task_message,
            prompt_compact=prompt_compact,
        )
        llm_system_prompt = resolve_diarization_label_system_prompt()
        mapping_raw, llm_raw = medgemma_generate(
            prompt=user_prompt,
            system_prompt=llm_system_prompt,
            model=model,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            temperature=temperature,
            force_json=True,
            timeout=timeout,
            return_raw=True,
            tracker=tracker,
            tracker_step_id=TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
            tracker_request_meta={
                "prompt_path": str(resolved_prompt_path),
                "prompt_compact": prompt_compact,
                "sample_chars": len(sample),
                "full_text_chars": len(text),
            },
        )
    except Exception as exc:
        result["error"] = str(exc)
        return result

    mapping = _parse_diarization_label_mapping(mapping_raw)
    if mapping is None:
        result["error"] = "invalid_llm_mapping_response"
        result["llm_raw"] = llm_raw
        return result

    labeled = _apply_diarization_label_mapping(text, mapping)

    result["text"] = labeled
    result["llm_raw"] = llm_raw
    result["mapping"] = mapping
    result["skipped"] = False
    result["diff"] = summarize_text_diff(text, labeled)
    return result


def _manual_diarize_one_chunk(
    text: str,
    *,
    previous_tail: str | None,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str | None,
    prompt_path: Path | None,
    temperature: float,
    timeout: int,
    tracker: PipelineTracker | None,
    prompt_compact: bool,
    chunk_index: int | None,
    chunk_count: int | None,
) -> tuple[str, str]:
    """Run one chunk through the LLM. Returns (diarized_text, llm_raw). Tracker
    recording for multi-chunk runs is done by the caller (via tracker_record_step)
    so each chunk doesn't overwrite the same step log file."""
    resolved_prompt_path = (prompt_path or DEFAULT_MANUAL_DIARIZATION_PROMPT_PATH).resolve()
    instructions = _finalize_postprocess_instructions(
        system_prompt or load_manual_diarization_prompt(prompt_path=prompt_path),
        prompt_compact=prompt_compact,
    )
    task_message = _build_manual_diarization_user_message(
        text,
        prompt_compact=prompt_compact,
        previous_tail=previous_tail,
    )
    user_prompt = compose_asr_user_prompt(instructions, task_message, prompt_compact=prompt_compact)
    llm_system_prompt = resolve_manual_diarization_system_prompt()
    request_meta: dict[str, Any] = {
        "prompt_path": str(resolved_prompt_path),
        "prompt_compact": prompt_compact,
        "transcript_words": len(text.split()),
    }
    if chunk_index is not None:
        request_meta["chunk_index"] = chunk_index
        request_meta["chunk_count"] = chunk_count
    diarized, llm_raw = medgemma_generate(
        prompt=user_prompt,
        system_prompt=llm_system_prompt,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        temperature=temperature,
        force_json=False,
        timeout=timeout,
        return_raw=True,
        tracker=tracker,
        tracker_step_id=TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION,
        tracker_record_step=chunk_count is None or chunk_count == 1,
        tracker_request_meta=request_meta,
    )
    return diarized.strip(), llm_raw


def _tail_for_continuity(diarized_text: str, *, max_lines: int = 3) -> str:
    lines = [line for line in diarized_text.splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])


def manual_diarize_transcript(
    text: str,
    *,
    enabled: bool = False,
    provider: str = "phihc",
    model: str = "gemma3:12b-it-qat",
    base_url: str,
    api_key: str = "",
    system_prompt: str | None = None,
    prompt_path: Path | None = None,
    temperature: float = 0,
    timeout: int = 600,
    tracker: PipelineTracker | None = None,
    prompt_compact: bool = False,
    min_word_ratio: float = DEFAULT_MANUAL_DIARIZATION_MIN_WORD_RATIO,
    chunk_max_words: int = 0,
) -> dict[str, Any]:
    """LLM-only diarization: split plain (non-diarized) text into Doutor:/Paciente:
    turns. No acoustic diarization model involved. Guarded the same way as the
    ASR-fix step (asr_fix_output_passes_guardrail) — if the model summarizes
    instead of just splitting/labeling, fall back to the plain, unlabeled input
    instead of silently accepting a shortened transcript.

    Long transcripts (~1000+ words) reliably lose whole dense/technical spans
    (lab reports, exam-history review) when diarized in one LLM call — chunking
    keeps each call short enough to stay complete, at the cost of needing the
    previous chunk's tail as context so Doutor/Paciente roles stay consistent
    across chunks (there's no acoustic speaker id to anchor to here, unlike the
    Sortformer-based diarization path)."""
    result = _llm_stage_result(
        text=text,
        provider=provider,
        model=model,
        base_url=base_url,
        preprocessing_stages=None,
        diarization_enabled=True,
    )

    if not enabled:
        result["error"] = "postprocess_disabled"
        if tracker:
            tracker.skip(TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION, reason="postprocess_disabled")
        return result

    if not text.strip():
        result["error"] = "empty_transcript"
        if tracker:
            tracker.skip(TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION, reason="empty_transcript")
        return result

    if not base_url.strip():
        result["error"] = "missing_llm_base_url"
        if tracker:
            tracker.skip(TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION, reason="missing_llm_base_url")
        return result

    if not str(api_key or "").strip():
        result["error"] = "missing_llm_api_key"
        if tracker:
            tracker.skip(TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION, reason="missing_llm_api_key")
        return result

    original_text = text.strip()
    chunks = _split_transcript_for_asr_fix(original_text, max_words=chunk_max_words)
    chunk_count = len(chunks)
    started = time.perf_counter()

    diarized_parts: list[str] = []
    raw_parts: list[str] = []
    try:
        previous_tail: str | None = None
        for index, chunk in enumerate(chunks, start=1):
            diarized_chunk, llm_raw = _manual_diarize_one_chunk(
                chunk,
                previous_tail=previous_tail,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                system_prompt=system_prompt,
                prompt_path=prompt_path,
                temperature=temperature,
                timeout=timeout,
                tracker=tracker,
                prompt_compact=prompt_compact,
                chunk_index=index if chunk_count > 1 else None,
                chunk_count=chunk_count if chunk_count > 1 else None,
            )
            diarized_parts.append(diarized_chunk)
            raw_parts.append(llm_raw)
            previous_tail = _tail_for_continuity(diarized_chunk)
    except Exception as exc:
        result["error"] = str(exc)
        return result

    diarized_stripped = "\n".join(part for part in diarized_parts if part)
    llm_raw_combined = "\n---\n".join(raw_parts)

    if chunk_count > 1 and tracker:
        tracker.record(
            TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION,
            request={"chunking": {"enabled": True, "chunk_count": chunk_count}},
            response={"text": diarized_stripped},
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    passes, guardrail_reason = asr_fix_output_passes_guardrail(
        original_text,
        diarized_stripped,
        min_word_ratio=min_word_ratio,
        min_speaker_line_ratio=0.0,
    )

    guardrail: dict[str, Any] = {"rejected": False}
    if passes:
        final_text = diarized_stripped
    else:
        guardrail = {
            "rejected": True,
            "reason": guardrail_reason,
            "input_word_count": len(original_text.split()),
            "llm_word_count": len(diarized_stripped.split()),
            "min_word_ratio": min_word_ratio,
        }
        final_text = original_text
        if tracker:
            tracker.amend(
                TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION,
                response={"guardrail": guardrail},
            )

    result["text"] = final_text
    result["llm_raw"] = llm_raw_combined
    result["guardrail"] = guardrail
    result["skipped"] = False
    result["error"] = guardrail_reason if guardrail["rejected"] else None
    result["diff"] = summarize_text_diff(original_text, final_text)
    result["chunking"] = {"enabled": chunk_count > 1, "chunk_count": chunk_count}
    return result


def edit_transcript_from_config(
    text: str,
    config: Mapping[str, Any],
    *,
    preprocessing_stages: list[str] | None = None,
    diarization_enabled: bool | None = None,
    tracker: PipelineTracker | None = None,
) -> dict[str, Any]:
    asr_prompt_path = _resolve_prompt_path(
        config.get("TRANSCRIPT_POSTPROCESS_PROMPT_PATH"),
        default=DEFAULT_PROMPT_PATH,
    )
    label_prompt_path = _resolve_prompt_path(
        config.get("TRANSCRIPT_DIARIZATION_LABEL_PROMPT_PATH"),
        default=DEFAULT_DIARIZATION_LABEL_PROMPT_PATH,
    )
    manual_diarization_prompt_path = _resolve_prompt_path(
        config.get("MANUAL_DIARIZATION_PROMPT_PATH"),
        default=DEFAULT_MANUAL_DIARIZATION_PROMPT_PATH,
    )

    if diarization_enabled is None:
        diarization_enabled = bool(config.get("DIARIZATION_ENABLED"))

    llm = resolve_llm_settings(config)
    guardrail = resolve_asr_fix_guardrail_settings(config)
    chunk_settings = resolve_asr_fix_chunk_settings(config)
    prompt_compact = prompt_compact_for_config(config)
    postprocess_enabled = bool(config.get("TRANSCRIPT_POSTPROCESS_ENABLED"))
    asr_fix_enabled = asr_fix_enabled_for_config(config)
    labels_enabled = diarization_labels_enabled(config)
    manual_diarization_wanted = manual_diarization_enabled(config)
    manual_diarization_min_word_ratio = float(
        config.get("MANUAL_DIARIZATION_MIN_WORD_RATIO", DEFAULT_MANUAL_DIARIZATION_MIN_WORD_RATIO)
    )

    if not postprocess_enabled:
        if tracker:
            tracker.skip(TRANSCRIBE_04_LLM_ASR_FIX, reason="postprocess_disabled")
            tracker.skip(TRANSCRIBE_04B_LLM_DIARIZATION_LABELS, reason="postprocess_disabled")
            tracker.skip(TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION, reason="postprocess_disabled")
        return {
            "text": text,
            "provider": llm["provider"],
            "model": llm["model"],
            "base_url": llm["base_url"],
            "skipped": True,
            "error": "postprocess_disabled",
            "preprocessing_stages": preprocessing_stages or [],
            "diarization_enabled": diarization_enabled,
            "asr_fix": {"skipped": True, "error": "postprocess_disabled"},
            "diarization_labels": {"skipped": True, "error": "postprocess_disabled"},
            "manual_diarization": {"skipped": True, "error": "postprocess_disabled"},
        }

    if asr_fix_enabled:
        asr_result = edit_transcript(
            text,
            enabled=True,
            provider=llm["provider"],
            model=llm["model"],
            base_url=llm["base_url"],
            api_key=llm["api_key"],
            prompt_path=asr_prompt_path,
            preprocessing_stages=preprocessing_stages,
            preserve_speaker_labels=diarization_enabled,
            tracker=tracker,
            tracker_step_id=TRANSCRIBE_04_LLM_ASR_FIX,
            timeout=int(llm["asr_fix_timeout"]),
            min_word_ratio=guardrail["min_word_ratio"],
            min_speaker_line_ratio=guardrail["min_speaker_line_ratio"],
            prompt_compact=prompt_compact,
            chunk_max_words=chunk_settings["chunk_max_words"],
            chunk_parallel=bool(chunk_settings["chunk_parallel"]),
            chunk_max_workers=int(chunk_settings["chunk_max_workers"]),
            max_retries=int(llm["asr_fix_max_retries"]),
        )
    else:
        if tracker:
            tracker.skip(TRANSCRIBE_04_LLM_ASR_FIX, reason=ASR_FIX_DISABLED_ERROR)
        asr_result = _llm_stage_result(
            text=text,
            provider=llm["provider"],
            model=llm["model"],
            base_url=llm["base_url"],
            preprocessing_stages=preprocessing_stages,
            diarization_enabled=diarization_enabled,
        )
        asr_result["error"] = ASR_FIX_DISABLED_ERROR
        asr_result["diff"] = summarize_text_diff(text, text)

    final_text = asr_result["text"]
    label_result: dict[str, Any]

    if diarization_enabled:
        asr_failed = asr_result["skipped"] and asr_result.get("error") != ASR_FIX_DISABLED_ERROR
        if asr_failed:
            label_result = {
                "text": final_text,
                "provider": llm["provider"],
                "model": llm["model"],
                "base_url": llm["base_url"],
                "skipped": True,
                "error": "asr_fix_skipped",
            }
            if tracker:
                tracker.skip(
                    TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
                    reason="asr_fix_skipped",
                )
        else:
            if labels_enabled:
                label_result = label_diarized_transcript(
                    asr_result["text"],
                    enabled=True,
                    provider=llm["provider"],
                    model=llm["model"],
                    base_url=llm["base_url"],
                    api_key=llm["api_key"],
                    prompt_path=label_prompt_path,
                    tracker=tracker,
                    timeout=int(llm["timeout"]),
                    prompt_compact=prompt_compact,
                )
                if not label_result["skipped"]:
                    final_text = label_result["text"]
            else:
                label_result = {
                    "text": final_text,
                    "provider": llm["provider"],
                    "model": llm["model"],
                    "base_url": llm["base_url"],
                    "skipped": True,
                    "error": "diarization_labels_disabled",
                }
                if tracker:
                    tracker.skip(
                        TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
                        reason="diarization_labels_disabled",
                    )
    else:
        label_result = {
            "text": final_text,
            "provider": llm["provider"],
            "model": llm["model"],
            "base_url": llm["base_url"],
            "skipped": True,
            "error": "diarization_disabled",
        }
        if tracker:
            tracker.skip(
                TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
                reason="diarization_disabled",
            )

    asr_ok_for_manual_diarization = (
        not asr_result["skipped"] or asr_result.get("error") == ASR_FIX_DISABLED_ERROR
    )
    if manual_diarization_wanted and asr_ok_for_manual_diarization:
        manual_result = manual_diarize_transcript(
            final_text,
            enabled=True,
            provider=llm["provider"],
            model=llm["model"],
            base_url=llm["base_url"],
            api_key=llm["api_key"],
            prompt_path=manual_diarization_prompt_path,
            tracker=tracker,
            timeout=int(llm["timeout"]),
            prompt_compact=prompt_compact,
            min_word_ratio=manual_diarization_min_word_ratio,
            chunk_max_words=chunk_settings["chunk_max_words"],
        )
        if not manual_result["skipped"]:
            final_text = manual_result["text"]
    else:
        manual_result = {
            "text": final_text,
            "provider": llm["provider"],
            "model": llm["model"],
            "base_url": llm["base_url"],
            "skipped": True,
            "error": "asr_fix_skipped" if manual_diarization_wanted else "manual_diarization_disabled",
        }
        if tracker:
            tracker.skip(
                TRANSCRIBE_04C_LLM_MANUAL_DIARIZATION,
                reason=manual_result["error"],
            )

    if asr_result.get("error") == ASR_FIX_DISABLED_ERROR:
        skipped = False
        error = None
    else:
        skipped = asr_result["skipped"]
        error = asr_result.get("error")
    asr_ok_for_downstream = not asr_result["skipped"] or asr_result.get("error") == ASR_FIX_DISABLED_ERROR
    if diarization_enabled and asr_ok_for_downstream and label_result.get("skipped"):
        if label_result.get("error") not in {
            None,
            "diarization_disabled",
            "diarization_labels_disabled",
        }:
            error = label_result.get("error")
    if manual_result.get("error") not in {None, "manual_diarization_disabled", "asr_fix_skipped"}:
        error = manual_result.get("error")

    return {
        "text": final_text,
        "provider": llm["provider"],
        "model": llm["model"],
        "base_url": llm["base_url"],
        "skipped": skipped,
        "error": error,
        "preprocessing_stages": preprocessing_stages or [],
        "diarization_enabled": diarization_enabled,
        "asr_fix": asr_result,
        "diarization_labels": label_result,
        "manual_diarization": manual_result,
        "diff": summarize_text_diff(text, final_text),
    }
