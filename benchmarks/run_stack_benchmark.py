#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from app.services.audio_processor import preprocess_audio
from app.services.transcribe import transcribe_options_from_mapping, transcribe_wav
from benchmarks.report import build_summary_rows, write_summary_json, write_summary_markdown
from benchmarks.score import load_reference_text, score_transcript
from benchmarks.stack_config import merge_stack_env, stack_env_to_preprocess_kwargs


def _load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _preprocess_metadata(processed: dict) -> dict:
    metadata = {"stages": processed.get("stages", [])}
    for key in ("enhance_deep", "enhance_voice", "loudness", "vad"):
        if key in processed:
            metadata[key] = processed[key]
    return metadata


def _run_stack(
    *,
    stack_id: str,
    stack_env: dict,
    audio_path: Path,
    work_dir: Path,
    whisper_cfg: dict,
    reference_text: str,
    remove_fillers: bool,
) -> dict:
    output_wav = work_dir / f"{stack_id}.wav"
    processed = preprocess_audio(
        audio_path,
        output_wav,
        **stack_env_to_preprocess_kwargs(stack_env),
    )
    transcription = transcribe_wav(
        output_wav,
        **transcribe_options_from_mapping(whisper_cfg),
    )
    scores = score_transcript(
        reference_text,
        transcription["text"],
        remove_fillers=remove_fillers,
    )
    preprocess_metadata = _preprocess_metadata(processed)
    return {
        "stack_id": stack_id,
        "label": stack_id,
        "stack_env": stack_env,
        "stages": preprocess_metadata["stages"],
        "preprocess_metadata": preprocess_metadata,
        "transcription": transcription,
        "scores": scores,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run phi-scribe preprocessing stack benchmark.")
    parser.add_argument("--stacks", default="benchmarks/stacks.yaml")
    parser.add_argument("--only", help="Comma-separated stack ids to run")
    parser.add_argument("--remove-fillers", action="store_true")
    parser.add_argument("--output", help="Output directory override")
    args = parser.parse_args()

    config_path = (ROOT / args.stacks).resolve()
    config = _load_config(config_path)
    audio_path = (ROOT / config["audio"]).resolve()
    reference_path = (ROOT / config["reference"]).resolve()
    if not audio_path.is_file():
        print(f"Audio not found: {audio_path}", file=sys.stderr)
        return 1
    if not reference_path.is_file():
        print(f"Reference not found: {reference_path}", file=sys.stderr)
        return 1

    reference_text = load_reference_text(reference_path)
    whisper_cfg = config["whisper"]
    stacks: dict = config["stacks"]

    selected = list(stacks.keys())
    if args.only:
        selected = [item.strip() for item in args.only.split(",") if item.strip()]
    if "baseline" not in selected:
        selected = ["baseline", *selected]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output) if args.output else ROOT / "benchmarks/results" / audio_path.stem / timestamp
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for stack_id in selected:
        if stack_id not in stacks:
            print(f"Unknown stack id: {stack_id}", file=sys.stderr)
            return 1
        print(f"Running stack: {stack_id}")
        stack_env = merge_stack_env(stacks[stack_id])
        result = _run_stack(
            stack_id=stack_id,
            stack_env=stack_env,
            audio_path=audio_path,
            work_dir=output_dir / "wav",
            whisper_cfg=whisper_cfg,
            reference_text=reference_text,
            remove_fillers=args.remove_fillers,
        )
        result_path = output_dir / f"{stack_id}.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
        print(
            f"  WER={result['scores']['wer_percent']}% "
            f"CER={result['scores']['cer_percent']}% "
            f"stages={result['stages']}"
        )

    ranked = build_summary_rows(results)
    meta = {
        "audio": str(audio_path.relative_to(ROOT)),
        "reference": str(reference_path.relative_to(ROOT)),
        "whisper_model": whisper_cfg["model"],
        "timestamp": timestamp,
    }
    write_summary_json(output_dir / "summary.json", ranked, meta=meta)
    write_summary_markdown(output_dir / "summary.md", ranked, meta=meta)
    print(f"\nWrote results to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
