from __future__ import annotations

import re
import unicodedata

_PT_FILLERS = {
    "ah",
    "aham",
    "eh",
    "em",
    "hm",
    "hmm",
    "hum",
    "ne",
    "né",
    "tipo",
    "ta",
    "tá",
    "uh",
}

def normalize_text(text: str, *, remove_fillers: bool = False) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    words = text.split()
    if remove_fillers:
        words = [word for word in words if word not in _PT_FILLERS]
    return " ".join(words)


def _levenshtein_distance(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for i, left_item in enumerate(left, start=1):
        current = [i]
        for j, right_item in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_item != right_item)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str, *, remove_fillers: bool = False) -> float:
    reference_words = normalize_text(reference, remove_fillers=remove_fillers).split()
    hypothesis_words = normalize_text(hypothesis, remove_fillers=remove_fillers).split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    return _levenshtein_distance(reference_words, hypothesis_words) / len(reference_words)


def char_error_rate(reference: str, hypothesis: str, *, remove_fillers: bool = False) -> float:
    reference_chars = list(normalize_text(reference, remove_fillers=remove_fillers).replace(" ", ""))
    hypothesis_chars = list(normalize_text(hypothesis, remove_fillers=remove_fillers).replace(" ", ""))
    if not reference_chars:
        return 0.0 if not hypothesis_chars else 1.0
    return _levenshtein_distance(reference_chars, hypothesis_chars) / len(reference_chars)


def score_transcript(
    reference: str,
    hypothesis: str,
    *,
    remove_fillers: bool = False,
) -> dict[str, float | int]:
    reference_words = normalize_text(reference, remove_fillers=remove_fillers).split()
    hypothesis_words = normalize_text(hypothesis, remove_fillers=remove_fillers).split()
    wer = word_error_rate(reference, hypothesis, remove_fillers=remove_fillers)
    cer = char_error_rate(reference, hypothesis, remove_fillers=remove_fillers)
    return {
        "wer": round(wer, 4),
        "cer": round(cer, 4),
        "wer_percent": round(wer * 100, 2),
        "cer_percent": round(cer * 100, 2),
        "word_count_reference": len(reference_words),
        "word_count_hypothesis": len(hypothesis_words),
    }


def load_reference_text(path) -> str:
    lines = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append(stripped)
    return " ".join(lines)
