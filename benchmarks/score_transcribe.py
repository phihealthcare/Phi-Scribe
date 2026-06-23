from __future__ import annotations

from benchmarks.score import normalize_text
from benchmarks.stack_config import merge_stack_env

EXCLUDED_FLAGS = ("ENHANCE_VOICE_ENABLED", "ENHANCE_DEEP_ENABLED")


def count_words(text: str) -> int:
    return len(normalize_text(text).split())


def count_chars(text: str) -> int:
    return len(normalize_text(text).replace(" ", ""))


def score_transcribe_output(
    text: str,
    *,
    reference_word_count: int,
    duration_ms: int | None = None,
) -> dict[str, int | float]:
    word_count = count_words(text)
    char_count = count_chars(text)
    scores: dict[str, int | float] = {
        "word_count": word_count,
        "char_count": char_count,
        "delta_vs_reference": word_count - reference_word_count,
    }
    if duration_ms and duration_ms > 0:
        scores["words_per_minute"] = round(word_count / (duration_ms / 60_000), 2)
    return scores


def is_allowed_stack(stack_env: dict) -> bool:
    merged = merge_stack_env(stack_env)
    return not any(merged.get(flag) for flag in EXCLUDED_FLAGS)
