#!/usr/bin/env python3
"""Whisper → LLM ASR fix only (improve text). No diarization, no speaker labels, no SOAP."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from dotenv import load_dotenv

load_dotenv()

from app.config import Config
from app.services.audio_processor import preprocess_audio
from app.services.llm_client import resolve_llm_settings
from app.services.transcribe import transcribe_options_from_mapping, transcribe_wav
from app.services.transcript_postprocess import (
    edit_transcript,
    format_diff_log,
    save_postprocess_diff_file,
)
from benchmarks.score import load_reference_text, score_transcript
from benchmarks.stack_config import merge_stack_env, resolve_whisper_block, stack_env_to_preprocess_kwargs

DEFAULT_STACKS_PATH = ROOT / "benchmarks/stacks_anamnesia-3-best.yaml"
DEFAULT_STACK_ID = "spectral_lpf_agc"
DEFAULT_PROMPT_PATH = ROOT / "benchmarks/prompts/medical-transcript-editor.md"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _config_dict() -> dict:
    return {key: getattr(Config, key) for key in dir(Config) if key.isupper()}


def _resolve_prompt_path(raw: str | None) -> Path:
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        return path.resolve()
    return DEFAULT_PROMPT_PATH.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Whisper (optional) + LLM ASR text improvement only."
    )
    parser.add_argument(
        "--text-file",
        help="Skip audio/Whisper; run LLM improve on this plain text file",
    )
    parser.add_argument(
        "--audio",
        help="Audio file path (default: audio from stacks_anamnesia-3-best.yaml)",
    )
    parser.add_argument(
        "--stack",
        default=DEFAULT_STACK_ID,
        help=f"Preprocess stack id (default: {DEFAULT_STACK_ID})",
    )
    parser.add_argument(
        "--reference",
        help="Optional reference transcript for WER/CER scoring",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="ASR editor prompt path (default: benchmarks/prompts/medical-transcript-editor.md)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: benchmarks/results/asr-fix-test-<timestamp>)",
    )
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output).resolve()
        if args.output
        else ROOT / f"benchmarks/results/asr-fix-test-{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    app_config = _config_dict()
    llm = resolve_llm_settings(app_config)
    prompt_path = _resolve_prompt_path(args.prompt)

    raw_text = ""
    stages: list[str] = []
    transcription_meta: dict = {}

    if args.text_file:
        text_path = Path(args.text_file).resolve()
        if not text_path.is_file():
            print(f"Text file not found: {text_path}", file=sys.stderr)
            return 1
        raw_text = text_path.read_text(encoding="utf-8").strip()
        print(f"Input: {text_path.relative_to(ROOT)} ({len(raw_text.split())} words)")
        _write_text(output_dir / "01_whisper_raw.txt", raw_text)
    else:
        stacks_path = DEFAULT_STACKS_PATH
        if not stacks_path.is_file():
            print(f"Stacks config not found: {stacks_path}", file=sys.stderr)
            return 1
        stack_config = yaml.safe_load(stacks_path.read_text(encoding="utf-8"))
        stack_id = args.stack
        if stack_id not in stack_config.get("stacks", {}):
            print(f"Unknown stack: {stack_id}", file=sys.stderr)
            return 1

        audio_path = Path(args.audio).resolve() if args.audio else (ROOT / stack_config["audio"]).resolve()
        if not audio_path.is_file():
            print(f"Audio not found: {audio_path}", file=sys.stderr)
            return 1

        stack_env = merge_stack_env(stack_config["stacks"][stack_id])
        whisper_cfg = resolve_whisper_block(stack_config["whisper"])
        work_wav = output_dir / f"{stack_id}.wav"

        print(f"Audio: {audio_path.name}")
        print(f"Stack: {stack_id}")
        print(f"Diarization: off (this test never runs diarization)")

        t0 = time.perf_counter()
        print("1) Preprocess...")
        processed = preprocess_audio(
            audio_path,
            work_wav,
            **stack_env_to_preprocess_kwargs(stack_env),
        )
        stages = [str(stage) for stage in processed.get("stages", [])]
        print(f"   stages={stages} ({time.perf_counter() - t0:.1f}s)")

        t1 = time.perf_counter()
        print("2) Transcribe (Whisper, no diarization)...")
        transcription = transcribe_wav(work_wav, **transcribe_options_from_mapping(whisper_cfg))
        raw_text = str(transcription.get("text", "")).strip()
        transcription_meta = {
            "duration_ms": transcription.get("duration_ms"),
            "language": transcription.get("language"),
            "segment_count": len(transcription.get("segments") or []),
        }
        if segments := transcription.get("segments"):
            _write_text(
                output_dir / "01_whisper_segments.json",
                json.dumps(segments, ensure_ascii=False, indent=2),
            )
        _write_text(output_dir / "01_whisper_raw.txt", raw_text)
        print(f"   done ({time.perf_counter() - t1:.1f}s, {len(raw_text.split())} words)")

    if not raw_text:
        print("No transcript text to process", file=sys.stderr)
        return 1

    reference = None
    if args.reference:
        reference_path = Path(args.reference).resolve()
        if not reference_path.is_file():
            print(f"Reference not found: {reference_path}", file=sys.stderr)
            return 1
        reference = load_reference_text(reference_path)

    if reference:
        before = score_transcript(reference, raw_text)
        print(
            f"\nWhisper WER={before['wer_percent']:.2f}% "
            f"CER={before['cer_percent']:.2f}%"
        )

    print("\n3) LLM improve text (ASR fix prompt only)...")
    print(f"   model={llm['model']}")
    print(f"   prompt={prompt_path.relative_to(ROOT)}")

    t2 = time.perf_counter()
    result = edit_transcript(
        raw_text,
        enabled=True,
        provider=llm["provider"],
        model=llm["model"],
        base_url=llm["base_url"],
        api_key=llm["api_key"],
        prompt_path=prompt_path,
        preprocessing_stages=stages or None,
        preserve_speaker_labels=False,
        timeout=int(llm["asr_fix_timeout"]),
    )
    duration_s = time.perf_counter() - t2

    if result["skipped"]:
        print(f"   FAILED: {result['error']}", file=sys.stderr)
        report = {
            "error": result["error"],
            "model": result.get("model"),
            "prompt_path": str(prompt_path),
        }
        (output_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 1

    improved_text = str(result["text"])
    diff = result.get("diff") or {}
    _write_text(output_dir / "02_llm_improved.txt", improved_text)
    if result.get("llm_raw"):
        _write_text(output_dir / "02_llm_improved_raw.json", str(result["llm_raw"]))

    save_postprocess_diff_file(
        output_dir / "diff.txt",
        raw_text=raw_text,
        corrected_text=improved_text,
        diff=diff,
        meta={
            "model": result.get("model"),
            "provider": result.get("provider"),
            "prompt_path": str(prompt_path),
        },
        label="asr_fix",
    )

    print(
        f"   ok ({duration_s:.1f}s, changes={diff.get('change_count', 0)}, "
        f"words {diff.get('word_count_before', 0)} → {diff.get('word_count_after', 0)})"
    )

    after_scores = None
    if reference:
        after_scores = score_transcript(reference, improved_text)
        delta_wer = after_scores["wer_percent"] - before["wer_percent"]
        print(
            f"   LLM WER={after_scores['wer_percent']:.2f}% "
            f"CER={after_scores['cer_percent']:.2f}% "
            f"(ΔWER {delta_wer:+.2f}pp)"
        )

    report = {
        "mode": "text_file" if args.text_file else "audio",
        "diarization": False,
        "soap": False,
        "speaker_labels": False,
        "model": result.get("model"),
        "provider": result.get("provider"),
        "prompt_path": str(prompt_path),
        "preprocessing_stages": stages,
        "transcription": transcription_meta,
        "diff": {
            "change_count": diff.get("change_count"),
            "word_count_before": diff.get("word_count_before"),
            "word_count_after": diff.get("word_count_after"),
        },
        "scores": {
            "whisper": before if reference else None,
            "llm_improved": after_scores,
        },
        "artifacts": {
            "whisper_raw": str(output_dir / "01_whisper_raw.txt"),
            "llm_improved": str(output_dir / "02_llm_improved.txt"),
            "diff": str(output_dir / "diff.txt"),
        },
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nImproved text: {(output_dir / '02_llm_improved.txt').relative_to(ROOT)}")
    print(f"Report:        {report_path.relative_to(ROOT)}")
    if diff.get("changes"):
        print()
        print(format_diff_log(diff))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
