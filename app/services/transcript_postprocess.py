from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT_PATH = ROOT / "benchmarks" / "prompts" / "medical-transcript-editor.md"


def load_editor_prompt(*, prompt_path: Path | None = None) -> str:
    path = (prompt_path or DEFAULT_PROMPT_PATH).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Editor prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _build_user_message(text: str, *, preprocessing_stages: list[str] | None = None) -> str:
    parts: list[str] = []
    if preprocessing_stages:
        stages_label = ", ".join(preprocessing_stages)
        parts.append(
            "Audio preprocessing stages applied before ASR (context only, do not edit): "
            f"{stages_label}"
        )
        parts.append("")
    parts.append(
        "Post-edit the following ASR transcript per your rules. "
        "Change only clear word-level ASR errors (spelling, accents, hyphens inside words). "
        "Never add or remove punctuation (. , ? ! ; :) or change capitalization."
    )
    parts.append("")
    parts.append(f"<<<\n{text.strip()}\n>>>")
    return "\n".join(parts)


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:\w+)?\s*\n?(.*?)\n?```\s*$", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def _estimate_max_tokens(text: str) -> int:
    word_count = len(text.split())
    return max(1024, word_count * 3)


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


def _call_openai(
    *,
    text: str,
    system_prompt: str,
    model: str,
    api_key: str,
    preprocessing_stages: list[str] | None = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=_estimate_max_tokens(text),
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": _build_user_message(text, preprocessing_stages=preprocessing_stages),
            },
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("LLM returned empty content")
    return _strip_markdown_fences(content)


def edit_transcript(
    text: str,
    *,
    enabled: bool = False,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    api_key: str | None = None,
    system_prompt: str | None = None,
    prompt_path: Path | None = None,
    preprocessing_stages: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "text": text,
        "provider": provider,
        "model": model,
        "skipped": True,
        "error": None,
        "preprocessing_stages": preprocessing_stages or [],
    }

    if not enabled:
        result["error"] = "postprocess_disabled"
        return result

    if not text.strip():
        result["error"] = "empty_transcript"
        return result

    if not api_key:
        result["error"] = "missing_api_key"
        return result

    if provider != "openai":
        result["error"] = f"unsupported_provider:{provider}"
        return result

    try:
        prompt = system_prompt or load_editor_prompt(prompt_path=prompt_path)
        corrected = _call_openai(
            text=text,
            system_prompt=prompt,
            model=model,
            api_key=api_key,
            preprocessing_stages=preprocessing_stages,
        )
    except Exception as exc:
        result["error"] = str(exc)
        return result

    result["text"] = corrected
    result["skipped"] = False
    result["diff"] = summarize_text_diff(text, corrected)
    return result


def edit_transcript_from_config(
    text: str,
    config: Mapping[str, Any],
    *,
    preprocessing_stages: list[str] | None = None,
) -> dict[str, Any]:
    prompt_path_raw = config.get("TRANSCRIPT_POSTPROCESS_PROMPT_PATH")
    prompt_path = Path(prompt_path_raw) if prompt_path_raw else None
    if prompt_path and not prompt_path.is_absolute():
        prompt_path = ROOT / prompt_path

    return edit_transcript(
        text,
        enabled=bool(config.get("TRANSCRIPT_POSTPROCESS_ENABLED")),
        provider=str(config.get("TRANSCRIPT_POSTPROCESS_PROVIDER", "openai")),
        model=str(config.get("TRANSCRIPT_POSTPROCESS_MODEL", "gpt-4o-mini")),
        api_key=config.get("OPENAI_API_KEY") or None,
        prompt_path=prompt_path,
        preprocessing_stages=preprocessing_stages,
    )
