#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.report import (
    build_summary_rows,
    extract_hypothesis_text,
    label_from_filename,
    write_summary_json,
    write_summary_markdown,
)
from benchmarks.score import load_reference_text, score_transcript


def _collect_hypothesis_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        path = Path(pattern)
        if path.is_absolute():
            matches = sorted(path.parent.glob(path.name))
        else:
            matches = sorted(ROOT.glob(pattern))
        files.extend(match for match in matches if match.is_file())
    return sorted(set(files))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score existing phi-scribe transcript JSON files against a reference."
    )
    parser.add_argument("--reference", required=True, help="Ground-truth text file")
    parser.add_argument(
        "--hypothesis",
        nargs="+",
        required=True,
        help="One or more JSON paths/globs (e.g. uploads/processed/*.json or benchmarks/manual/TEST*.json)",
    )
    parser.add_argument("--output", default="benchmarks/results/manual")
    parser.add_argument("--remove-fillers", action="store_true")
    args = parser.parse_args()

    reference_path = (ROOT / args.reference).resolve() if not Path(args.reference).is_absolute() else Path(args.reference)
    output_dir = (ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_text = load_reference_text(reference_path)
    hypothesis_files = _collect_hypothesis_files(args.hypothesis)
    if not hypothesis_files:
        print("No hypothesis JSON files found.", file=sys.stderr)
        return 1

    results = []
    for hypothesis_path in hypothesis_files:
        payload = json.loads(hypothesis_path.read_text(encoding="utf-8"))
        hypothesis_text = extract_hypothesis_text(payload)
        label = label_from_filename(hypothesis_path)
        scores = score_transcript(
            reference_text,
            hypothesis_text,
            remove_fillers=args.remove_fillers,
        )
        stages = payload.get("stages", [])
        if not stages and isinstance(payload.get("preprocess_metadata"), dict):
            stages = payload["preprocess_metadata"].get("stages", [])

        result = {
            "label": label,
            "source_file": str(hypothesis_path.relative_to(ROOT)) if hypothesis_path.is_relative_to(ROOT) else str(hypothesis_path),
            "stages": stages,
            "scores": scores,
            "transcription_text_preview": hypothesis_text[:240],
        }
        results.append(result)
        scored_path = output_dir / f"{label}.scored.json"
        scored_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{label}: WER={scores['wer_percent']}% CER={scores['cer_percent']}%")

    ranked = build_summary_rows(results)
    meta = {
        "reference": str(reference_path.relative_to(ROOT)) if reference_path.is_relative_to(ROOT) else str(reference_path),
        "mode": "manual",
    }
    write_summary_json(output_dir / "summary.json", ranked, meta=meta)
    write_summary_markdown(output_dir / "summary.md", ranked, meta=meta)
    print(f"\nWrote comparison to {output_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
