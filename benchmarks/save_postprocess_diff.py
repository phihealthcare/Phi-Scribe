#!/usr/bin/env python3
"""Build a .postprocess.diff.txt report from an existing benchmark/API JSON (no LLM call)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.transcript_postprocess import save_postprocess_diff_file, summarize_text_diff


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Save LLM before/after diff report from an existing transcript JSON."
    )
    parser.add_argument("--input", required=True, help="Stack or API transcript JSON")
    parser.add_argument(
        "--output",
        help="Output .txt path (default: <input>.postprocess.diff.txt)",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    transcription = payload.get("transcription", {})
    if not isinstance(transcription, dict):
        print("No transcription object in JSON", file=sys.stderr)
        return 1

    raw_text = str(transcription.get("raw_text", "")).strip()
    corrected = str(transcription.get("text", "")).strip()
    if not raw_text:
        print("No transcription.raw_text — postprocess may not have run", file=sys.stderr)
        return 1

    postprocess = payload.get("postprocess", {})
    diff = postprocess.get("diff") if isinstance(postprocess, dict) else None
    if not diff:
        diff = summarize_text_diff(raw_text, corrected)

    output_path = Path(args.output) if args.output else input_path.with_suffix(".postprocess.diff.txt")
    label = payload.get("stack_id") or payload.get("label") or input_path.stem
    meta = {
        "source_json": str(input_path),
        "stack_id": label,
    }
    if isinstance(postprocess, dict):
        if postprocess.get("model"):
            meta["model"] = postprocess["model"]
        if postprocess.get("provider"):
            meta["provider"] = postprocess["provider"]

    written = save_postprocess_diff_file(
        output_path,
        raw_text=raw_text,
        corrected_text=corrected,
        diff=diff,
        meta=meta,
        label=str(label),
    )
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
