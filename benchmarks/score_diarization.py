"""Score a speaker-labeled transcript ("Médico: ..." / "Paciente: ..." per line)
against a manually diarized reference: text WER/CER plus speaker-role accuracy.

Usage:
    python benchmarks/score_diarization.py \
        --reference benchmarks/references/consulta-real-1-diarized.txt \
        --hypothesis uploads/processed/<file_id>.json

`--hypothesis` accepts either a plain "Label: text" file, or a saved pipeline
response JSON (reads `transcription.text`, which is where the diarization
label relabel step writes its "Médico:"/"Paciente:" output).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from score import normalize_text, score_transcript

ROLE_CANON = {
    "doutor": "MEDICO",
    "doutora": "MEDICO",
    "médico": "MEDICO",
    "medico": "MEDICO",
    "médica": "MEDICO",
    "medica": "MEDICO",
    "paciente": "PACIENTE",
}

_LINE_RE = re.compile(r"^\s*([^:]+):\s*(.*)$")


def parse_labeled_lines(text: str) -> list[tuple[str, str]]:
    turns = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        label, content = match.group(1).strip(), match.group(2).strip()
        if not content:
            continue
        role = ROLE_CANON.get(label.lower(), label.upper())
        turns.append((role, content))
    return turns


def load_turns(path: Path) -> list[tuple[str, str]]:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        text = data.get("transcription", {}).get("text", "")
        return parse_labeled_lines(text)
    return parse_labeled_lines(path.read_text(encoding="utf-8"))


def _turns_to_word_roles(turns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out = []
    for role, text in turns:
        for word in normalize_text(text).split():
            out.append((role, word))
    return out


def _align(ref: list[tuple[str, str]], hyp: list[tuple[str, str]]) -> list[tuple[str, int | None, int | None]]:
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        ref_word = ref[i - 1][1]
        for j in range(1, m + 1):
            sub_cost = dp[i - 1][j - 1] + (0 if ref_word == hyp[j - 1][1] else 1)
            del_cost = dp[i - 1][j] + 1
            ins_cost = dp[i][j - 1] + 1
            dp[i][j] = min(sub_cost, del_cost, ins_cost)

    ops: list[tuple[str, int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (0 if ref[i - 1][1] == hyp[j - 1][1] else 1):
            op = "match" if ref[i - 1][1] == hyp[j - 1][1] else "sub"
            ops.append((op, i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(("del", i - 1, None))
            i -= 1
        else:
            ops.append(("ins", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def score_diarization(
    reference_turns: list[tuple[str, str]],
    hypothesis_turns: list[tuple[str, str]],
) -> dict[str, float | int]:
    ref_word_roles = _turns_to_word_roles(reference_turns)
    hyp_word_roles = _turns_to_word_roles(hypothesis_turns)

    ref_text = " ".join(word for _, word in ref_word_roles)
    hyp_text = " ".join(word for _, word in hyp_word_roles)
    text_score = score_transcript(ref_text, hyp_text)

    ops = _align(ref_word_roles, hyp_word_roles)
    aligned = [(i, j) for op, i, j in ops if op in ("match", "sub")]
    role_matches = sum(1 for i, j in aligned if ref_word_roles[i][0] == hyp_word_roles[j][0])
    role_accuracy = (role_matches / len(aligned)) if aligned else 0.0

    return {
        **text_score,
        "role_accuracy": round(role_accuracy, 4),
        "role_accuracy_percent": round(role_accuracy * 100, 2),
        "aligned_word_pairs": len(aligned),
        "reference_turns": len(reference_turns),
        "hypothesis_turns": len(hypothesis_turns),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--hypothesis", required=True, type=Path)
    args = parser.parse_args()

    reference_turns = load_turns(args.reference)
    hypothesis_turns = load_turns(args.hypothesis)

    if not reference_turns:
        raise SystemExit(f"No labeled turns parsed from reference: {args.reference}")
    if not hypothesis_turns:
        raise SystemExit(
            f"No labeled turns parsed from hypothesis: {args.hypothesis} "
            "(expected 'Médico: ...' / 'Paciente: ...' lines in transcription.text)"
        )

    result = score_diarization(reference_turns, hypothesis_turns)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
