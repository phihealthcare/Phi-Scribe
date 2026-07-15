#!/usr/bin/env python3
"""Turn/line-boundary agreement metric — how well a diarized hypothesis'
turn segmentation (where one speaker's line ends and the next begins)
matches a reference transcript's segmentation, ignoring speaker labels
entirely (Doutor/Paciente vs Falante 1/Falante 2 doesn't matter here).

Complements score_diarization.py, which scores WER/CER + label/role
accuracy. Use this one when the label mapping isn't meaningful (e.g.
comparing different Sortformer chunk_s/overlap_s configs, where the
speaker_G0/G1/G2 identities aren't stable across runs) and only the turn
structure itself is being evaluated.

Usage:
    python benchmarks/turn_boundary_score.py \
        --reference benchmarks/references/consulta-real-1-diarized.txt \
        --hypothesis path/to/hypothesis.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).resolve().parent
if str(BENCHMARKS_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS_DIR))

from score import normalize_text  # noqa: E402
from score_diarization import _align, parse_labeled_lines  # noqa: E402


def _turns_to_words_with_turn_idx(turns: list[tuple[str, str]]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for turn_idx, (_role, text) in enumerate(turns):
        for word in normalize_text(text).split():
            out.append((turn_idx, word))
    return out


def _boundary_positions(turn_indices: list[int]) -> set[int]:
    """Word index i such that a new turn starts at i (turn_indices[i] != turn_indices[i-1])."""
    return {i for i in range(1, len(turn_indices)) if turn_indices[i] != turn_indices[i - 1]}


def _position_maps(
    ops: list[tuple[str, int | None, int | None]], ref_len: int, hyp_len: int
) -> tuple[list[int | None], list[int | None]]:
    """From alignment ops, build ref_idx->hyp_idx and hyp_idx->ref_idx bridges.
    Only match/sub ops create a direct bridge; del/ins leave gaps that
    _nearest_mapped fills in by walking outward."""
    ref_to_hyp: list[int | None] = [None] * ref_len
    hyp_to_ref: list[int | None] = [None] * hyp_len
    for op, i, j in ops:
        if op in ("match", "sub") and i is not None and j is not None:
            ref_to_hyp[i] = j
            hyp_to_ref[j] = i
    return ref_to_hyp, hyp_to_ref


def _nearest_mapped(mapping: list[int | None], index: int) -> int | None:
    n = len(mapping)
    if not n:
        return None
    for offset in range(n):
        for candidate in (index - offset, index + offset):
            if 0 <= candidate < n and mapping[candidate] is not None:
                return mapping[candidate]
    return None


def turn_boundary_score(
    reference_turns: list[tuple[str, str]],
    hypothesis_turns: list[tuple[str, str]],
    *,
    tolerance_words: int = 2,
) -> dict[str, float | int]:
    ref_word_turns = _turns_to_words_with_turn_idx(reference_turns)
    hyp_word_turns = _turns_to_words_with_turn_idx(hypothesis_turns)

    # _align only ever compares the second tuple element (the word) for cost —
    # passing the turn index in the first slot is a harmless way to reuse it.
    ops = _align(ref_word_turns, hyp_word_turns)
    ref_to_hyp, hyp_to_ref = _position_maps(ops, len(ref_word_turns), len(hyp_word_turns))

    ref_turn_idx = [t for t, _ in ref_word_turns]
    hyp_turn_idx = [t for t, _ in hyp_word_turns]
    ref_boundaries = _boundary_positions(ref_turn_idx)
    hyp_boundaries = _boundary_positions(hyp_turn_idx)

    def _hyp_boundary_near(hyp_pos: int) -> bool:
        return any((hyp_pos + delta) in hyp_boundaries for delta in range(-tolerance_words, tolerance_words + 1))

    def _ref_boundary_near(ref_pos: int) -> bool:
        return any((ref_pos + delta) in ref_boundaries for delta in range(-tolerance_words, tolerance_words + 1))

    recall_hits = 0
    for ref_pos in ref_boundaries:
        hyp_pos = ref_to_hyp[ref_pos]
        if hyp_pos is None:
            hyp_pos = _nearest_mapped(ref_to_hyp, ref_pos)
        if hyp_pos is not None and _hyp_boundary_near(hyp_pos):
            recall_hits += 1

    precision_hits = 0
    for hyp_pos in hyp_boundaries:
        ref_pos = hyp_to_ref[hyp_pos]
        if ref_pos is None:
            ref_pos = _nearest_mapped(hyp_to_ref, hyp_pos)
        if ref_pos is not None and _ref_boundary_near(ref_pos):
            precision_hits += 1

    precision = (precision_hits / len(hyp_boundaries)) if hyp_boundaries else (1.0 if not ref_boundaries else 0.0)
    recall = (recall_hits / len(ref_boundaries)) if ref_boundaries else (1.0 if not hyp_boundaries else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "boundary_precision": round(precision, 4),
        "boundary_recall": round(recall, 4),
        "boundary_f1": round(f1, 4),
        "ref_turn_count": len(reference_turns),
        "hyp_turn_count": len(hypothesis_turns),
        "ref_boundary_count": len(ref_boundaries),
        "hyp_boundary_count": len(hyp_boundaries),
        "tolerance_words": tolerance_words,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--hypothesis", required=True, type=Path)
    parser.add_argument("--tolerance-words", type=int, default=2)
    args = parser.parse_args()

    reference_turns = parse_labeled_lines(args.reference.read_text(encoding="utf-8"))
    hypothesis_turns = parse_labeled_lines(args.hypothesis.read_text(encoding="utf-8"))

    if not reference_turns:
        raise SystemExit(f"No labeled turns parsed from reference: {args.reference}")
    if not hypothesis_turns:
        raise SystemExit(f"No labeled turns parsed from hypothesis: {args.hypothesis}")

    result = turn_boundary_score(reference_turns, hypothesis_turns, tolerance_words=args.tolerance_words)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
