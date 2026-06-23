#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from benchmarks.report import extract_hypothesis_text
from benchmarks.score import load_reference_text, score_transcript
from app.services.transcript_postprocess import edit_transcript, format_diff_log, load_editor_prompt

load_dotenv()


def _load_stages(payload: dict) -> list[str]:
    stages = payload.get("stages")
    if isinstance(stages, list):
        return [str(stage) for stage in stages]
    postprocess = payload.get("postprocess")
    if isinstance(postprocess, dict):
        logged = postprocess.get("preprocessing_stages")
        if isinstance(logged, list):
            return [str(stage) for stage in logged]
    return []


def _load_raw_text(payload: dict) -> str:
    transcription = payload.get("transcription")
    if isinstance(transcription, dict):
        raw = transcription.get("raw_text")
        if raw:
            return str(raw).strip()
        return str(transcription.get("text", "")).strip()
    return extract_hypothesis_text(payload)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run LLM transcript post-edit on a benchmark JSON and score WER/CER before vs after."
    )
    parser.add_argument("--input", required=True, help="Transcript JSON from run_stack_benchmark or API")
    parser.add_argument("--reference", required=True, help="Ground-truth reference text file")
    parser.add_argument(
        "--prompt",
        default=None,
        help="Editor prompt path (default: benchmarks/prompts/medical-transcript-editor.md)",
    )
    parser.add_argument("--model", default=os.environ.get("TRANSCRIPT_POSTPROCESS_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--provider",
        default=os.environ.get("TRANSCRIPT_POSTPROCESS_PROVIDER", "openai"),
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    reference_path = Path(args.reference)
    if not reference_path.is_file():
        print(f"Reference not found: {reference_path}", file=sys.stderr)
        return 1

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    raw_text = _load_raw_text(payload)
    if not raw_text:
        print("No transcript text found in input JSON", file=sys.stderr)
        return 1

    stages = _load_stages(payload)
    reference = load_reference_text(reference_path)
    before_scores = score_transcript(reference, raw_text)

    prompt_path = Path(args.prompt) if args.prompt else None
    system_prompt = load_editor_prompt(prompt_path=prompt_path) if prompt_path else None
    api_key = os.environ.get("OPENAI_API_KEY", "").strip() or None

    result = edit_transcript(
        raw_text,
        enabled=True,
        provider=args.provider,
        model=args.model,
        api_key=api_key,
        system_prompt=system_prompt,
        prompt_path=prompt_path,
        preprocessing_stages=stages or None,
    )

    if result["skipped"]:
        print(f"Post-edit skipped or failed: {result['error']}", file=sys.stderr)
        return 1

    corrected = result["text"]
    after_scores = score_transcript(reference, corrected)

    report = {
        "input": str(input_path),
        "reference": str(reference_path),
        "model": result["model"],
        "provider": result["provider"],
        "preprocessing_stages": stages,
        "diff": result.get("diff"),
        "before": {
            "text_preview": raw_text[:200],
            "scores": before_scores,
        },
        "after": {
            "text_preview": corrected[:200],
            "scores": after_scores,
        },
        "delta": {
            "wer": after_scores["wer"] - before_scores["wer"],
            "cer": after_scores["cer"] - before_scores["cer"],
        },
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    if diff := result.get("diff"):
        print(format_diff_log(diff))
        print()
    print(
        f"WER: {before_scores['wer']:.4f} → {after_scores['wer']:.4f} "
        f"({report['delta']['wer']:+.4f})"
    )
    print(
        f"CER: {before_scores['cer']:.4f} → {after_scores['cer']:.4f} "
        f"({report['delta']['cer']:+.4f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
