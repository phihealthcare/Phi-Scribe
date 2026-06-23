#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from app.services.audio_processor import preprocess_audio
from app.services.transcribe import transcribe_options_from_mapping, transcribe_wav
from benchmarks.score import load_reference_text
from benchmarks.report_transcribe import (
    build_summary_rows,
    write_summary_json,
    write_summary_markdown,
)
from benchmarks.score_transcribe import count_words, is_allowed_stack, score_transcribe_output
from benchmarks.stack_config import merge_stack_env, stack_env_to_preprocess_kwargs

DEFAULT_STACKS_CONFIG = ROOT / "benchmarks" / "transcribe_stacks.yaml"
EXPECTED_STACK_COUNT = 69


def _load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _load_stacks(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if "stacks" in config:
        return config["stacks"]

    stacks_source = config.get("stacks_source")
    if not stacks_source:
        raise ValueError("Config must define 'stacks' or 'stacks_source'")

    source_path = Path(stacks_source)
    if not source_path.is_absolute():
        source_path = (ROOT / source_path).resolve()
    source_cfg = _load_config(source_path)
    stacks = source_cfg.get("stacks")
    if not isinstance(stacks, dict):
        raise ValueError(f"No stacks found in {source_path}")
    return stacks


def _preprocess_metadata(processed: dict) -> dict:
    metadata = {"stages": processed.get("stages", [])}
    for key in ("enhance_deep", "enhance_voice", "loudness", "vad"):
        if key in processed:
            metadata[key] = processed[key]
    return metadata


def _load_reference_word_count(reference_path: Path) -> tuple[int, dict[str, Any]]:
    if not reference_path.is_file():
        raise FileNotFoundError(f"Reference not found: {reference_path}")
    text = load_reference_text(reference_path)
    word_count = count_words(text)
    return word_count, {
        "source": str(reference_path.relative_to(ROOT)),
        "word_count": word_count,
    }


def _run_stack(
    *,
    stack_id: str,
    stack_env: dict[str, Any],
    audio_path: Path,
    work_dir: Path,
    whisper_cfg: dict[str, Any],
    reference_word_count: int,
) -> dict[str, Any]:
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
    scores = score_transcribe_output(
        transcription.get("text", ""),
        reference_word_count=reference_word_count,
        duration_ms=transcription.get("duration_ms"),
    )
    preprocess_metadata = _preprocess_metadata(processed)
    merged_env = merge_stack_env(stack_env)
    return {
        "stack_id": stack_id,
        "label": stack_id,
        "stack_env": merged_env,
        "stages": preprocess_metadata["stages"],
        "preprocess_metadata": preprocess_metadata,
        "transcription": transcription,
        "scores": scores,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run phi-scribe transcribe word-count preprocessing benchmark.",
    )
    parser.add_argument("--stacks", default=str(DEFAULT_STACKS_CONFIG))
    parser.add_argument("--only", help="Comma-separated stack ids to run")
    parser.add_argument("--output", help="Output directory override")
    args = parser.parse_args()

    config_path = Path(args.stacks).resolve()
    if not config_path.is_file():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 1

    config = _load_config(config_path)
    audio_path = _resolve_path(config["audio"])
    if not audio_path.is_file():
        print(f"Audio not found: {audio_path}", file=sys.stderr)
        return 1

    whisper_cfg = config["whisper"]
    stacks = _load_stacks(config)

    reference_cfg = config.get("reference")
    if not reference_cfg:
        print("Config must define 'reference' (path to .txt transcript)", file=sys.stderr)
        return 1
    reference_path = _resolve_path(reference_cfg)

    selected = list(stacks.keys())
    if args.only:
        selected = [item.strip() for item in args.only.split(",") if item.strip()]

    allowed: list[str] = []
    skipped: list[str] = []
    for stack_id in selected:
        if stack_id not in stacks:
            print(f"Unknown stack id: {stack_id}", file=sys.stderr)
            return 1
        if is_allowed_stack(stacks[stack_id]):
            allowed.append(stack_id)
        else:
            skipped.append(stack_id)

    if skipped:
        print(f"Skipped {len(skipped)} excluded stack(s): {', '.join(skipped)}", file=sys.stderr)

    if not allowed:
        print("No stacks to run after filtering.", file=sys.stderr)
        return 1

    reference_word_count, reference_meta = _load_reference_word_count(reference_path)
    print(f"Reference word count: {reference_word_count}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output)
        if args.output
        else ROOT / "benchmarks/results/transcribe" / audio_path.stem / timestamp
    )
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(allowed)
    results = []
    for index, stack_id in enumerate(allowed, start=1):
        print(f"Running stack {index}/{total}: {stack_id}")
        stack_env = merge_stack_env(stacks[stack_id])
        result = _run_stack(
            stack_id=stack_id,
            stack_env=stack_env,
            audio_path=audio_path,
            work_dir=output_dir / "wav",
            whisper_cfg=whisper_cfg,
            reference_word_count=reference_word_count,
        )
        result_path = output_dir / f"{stack_id}.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
        delta = result["scores"]["delta_vs_reference"]
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        print(
            f"  Words={result['scores']['word_count']} "
            f"Δ={delta_str} "
            f"stages={result['stages']}"
        )

    ranked = build_summary_rows(results)
    meta = {
        "audio": str(audio_path.relative_to(ROOT)),
        "whisper_model": whisper_cfg["model"],
        "timestamp": timestamp,
        "reference": str(reference_path.relative_to(ROOT)),
        "reference_word_count": reference_word_count,
        "reference_meta": reference_meta,
        "stacks_run": len(results),
        "stacks_skipped": len(skipped),
        "stacks_expected": EXPECTED_STACK_COUNT if not args.only else len(allowed),
    }
    write_summary_json(output_dir / "summary.json", ranked, meta=meta)
    write_summary_markdown(output_dir / "summary.md", ranked, meta=meta)

    if not args.only and len(results) != EXPECTED_STACK_COUNT:
        print(
            f"Warning: expected {EXPECTED_STACK_COUNT} stacks, ran {len(results)} "
            f"({len(skipped)} skipped).",
            file=sys.stderr,
        )

    print(f"\nWrote results to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
