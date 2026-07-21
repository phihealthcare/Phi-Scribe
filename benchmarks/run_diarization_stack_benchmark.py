#!/usr/bin/env python3
"""Benchmark Sortformer chunk_s/overlap_s stacks against a manually diarized
reference, scored on TURN-BOUNDARY agreement (not speaker labels) plus WER/CER.

Whisper transcription is only run ONCE (word_timestamps=True) and cached —
every stack only differs in the diarization step, so re-running Whisper per
stack would be wasted GPU time. See turn_boundary_score.py for the metric and
app/services/diarization_sortformer.py for diarize_wav_sortformer_chunked.

Usage:
    python benchmarks/run_diarization_stack_benchmark.py \
        --config benchmarks/diarization_stacks.yaml \
        --only chunk_240_20 chunk_90_20   # optional subset
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS_DIR = Path(__file__).resolve().parent
for path in (ROOT, BENCHMARKS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import yaml  # noqa: E402

from app.services import transcribe  # noqa: E402
from app.services.diarization_sortformer import diarize_wav_sortformer_chunked  # noqa: E402
from app.services.transcribe_diarized import (  # noqa: E402
    _collect_words,
    _segments_from_aligned_words,
    format_speaker_transcript,
    speaker_label_map,
)
from benchmarks.score import load_reference_text, score_transcript  # noqa: E402
from benchmarks.score_diarization import parse_labeled_lines  # noqa: E402
from benchmarks.turn_boundary_score import turn_boundary_score  # noqa: E402


def _load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _run_whisper_once(wav_path: Path, whisper_opts: dict[str, Any]) -> dict[str, Any]:
    options = dict(whisper_opts)
    options["word_timestamps"] = True
    options["force_sequential"] = True
    print(f"[whisper] transcribing {wav_path.name} (word_timestamps=True, cached for all stacks)...")
    t0 = time.perf_counter()
    result = transcribe.transcribe_wav(wav_path, **options)
    print(f"[whisper] done in {time.perf_counter() - t0:.1f}s, {len(_collect_words(result))} words")
    return result


def _run_stack(
    wav_path: Path,
    *,
    stack_id: str,
    stack_params: dict[str, Any],
    sortformer_fixed: dict[str, Any],
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    t0 = time.perf_counter()
    diarization_result = diarize_wav_sortformer_chunked(
        wav_path,
        chunk_s=float(stack_params["chunk_s"]),
        overlap_s=float(stack_params["overlap_s"]),
        model_id=sortformer_fixed.get("model_id", "nvidia/diar_sortformer_4spk-v1"),
        max_duration_s=float(sortformer_fixed.get("max_duration_s", 300.0)),
        device=sortformer_fixed.get("device", "cuda"),
        min_turn_ms=int(sortformer_fixed.get("min_turn_ms", 400)),
    )
    diarization_s = time.perf_counter() - t0

    alignment_turns = diarization_result.get("alignment_turns") or diarization_result["turns"]
    speaker_label_mapping = speaker_label_map(diarization_result.get("speakers", []))
    segments = _segments_from_aligned_words(
        words,
        alignment_turns=alignment_turns,
        speaker_label_mapping=speaker_label_mapping,
    )
    labeled_text = format_speaker_transcript(segments)

    return {
        "stack_id": stack_id,
        "params": stack_params,
        "diarization_s": round(diarization_s, 2),
        "turn_count": diarization_result.get("turn_count"),
        "speakers": diarization_result.get("speakers"),
        "sortformer_timing": diarization_result.get("sortformer_timing"),
        "labeled_text": labeled_text,
        "segment_count": len(segments),
    }


def _score_stack(stack_result: dict[str, Any], *, reference_text: str, reference_turns: list[tuple[str, str]]) -> dict[str, Any]:
    labeled_text = stack_result["labeled_text"]
    hypothesis_turns = parse_labeled_lines(labeled_text)
    plain_text = " ".join(text for _role, text in hypothesis_turns)

    wer_cer = score_transcript(reference_text, plain_text)
    boundary = turn_boundary_score(reference_turns, hypothesis_turns, tolerance_words=2)

    return {**stack_result, "scores": {**wer_cer, **boundary}}


def _write_summary_markdown(path: Path, ranked: list[dict[str, Any]], *, meta: dict[str, Any]) -> None:
    lines = [
        "# Diarization stack benchmark — turn-boundary agreement",
        "",
        f"- Audio: `{meta['audio']}`",
        f"- Reference: `{meta['reference']}` ({meta['reference_turn_count']} turns)",
        f"- Whisper model: `{meta['whisper_model']}`",
        f"- Sortformer fixed params: `{meta['sortformer_fixed']}`",
        "",
        "Ranked by boundary F1 (primary), WER (secondary). Labels (Falante N) are "
        "ignored entirely by boundary_f1 — it only measures whether turn changes "
        "happen in the same place as the reference.",
        "",
        "| Rank | Stack | chunk_s | overlap_s | Turns (ref=" + str(meta["reference_turn_count"]) + ") | Boundary F1 | Precision | Recall | WER % | CER % | Diarization time (s) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rank, row in enumerate(ranked, start=1):
        scores = row["scores"]
        params = row["params"]
        lines.append(
            f"| {rank} | {row['stack_id']} | {params['chunk_s']} | {params['overlap_s']} | "
            f"{row['turn_count']} | {scores['boundary_f1']} | {scores['boundary_precision']} | "
            f"{scores['boundary_recall']} | {scores['wer_percent']} | {scores['cer_percent']} | "
            f"{row['diarization_s']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=BENCHMARKS_DIR / "diarization_stacks.yaml")
    parser.add_argument("--only", nargs="*", default=None, help="Subset of stack_ids to run")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "benchmarks" / "results" / "diarization-stack-benchmark-2a01499f",
    )
    args = parser.parse_args()

    config = _load_config(args.config)
    wav_path = ROOT / config["audio"]
    reference_path = ROOT / config["reference"]
    whisper_opts = config["whisper"]
    sortformer_fixed = config["sortformer_fixed"]
    all_stacks = config["stacks"]
    selected_ids = args.only if args.only else list(all_stacks.keys())

    reference_text = load_reference_text(reference_path)
    reference_turns = parse_labeled_lines(reference_path.read_text(encoding="utf-8"))
    print(f"Reference: {len(reference_turns)} turns, {len(reference_text.split())} words")

    full_result = _run_whisper_once(wav_path, whisper_opts)
    words = _collect_words(full_result)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for stack_id in selected_ids:
        stack_params = all_stacks[stack_id]
        print(f"\n[{stack_id}] chunk_s={stack_params['chunk_s']} overlap_s={stack_params['overlap_s']}")
        stack_result = _run_stack(
            wav_path,
            stack_id=stack_id,
            stack_params=stack_params,
            sortformer_fixed=sortformer_fixed,
            words=words,
        )
        scored = _score_stack(stack_result, reference_text=reference_text, reference_turns=reference_turns)
        print(
            f"[{stack_id}] turns={scored['turn_count']} boundary_f1={scored['scores']['boundary_f1']} "
            f"wer={scored['scores']['wer_percent']}% diarization_s={scored['diarization_s']}"
        )
        (args.output_dir / f"{stack_id}.json").write_text(
            json.dumps(scored, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results.append(scored)

    ranked = sorted(results, key=lambda row: (-row["scores"]["boundary_f1"], row["scores"]["wer"]))
    meta = {
        "audio": config["audio"],
        "reference": config["reference"],
        "reference_turn_count": len(reference_turns),
        "whisper_model": whisper_opts.get("model_size", whisper_opts.get("model_id", "")),
        "sortformer_fixed": sortformer_fixed,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps({"meta": meta, "results": ranked}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_summary_markdown(args.output_dir / "summary.md", ranked, meta=meta)

    print(f"\nWrote results to {args.output_dir}")
    print(f"Best stack by boundary_f1: {ranked[0]['stack_id']} (F1={ranked[0]['scores']['boundary_f1']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
