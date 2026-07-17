#!/usr/bin/env python3
"""Sweep ASR-fix chunking configs (chunk_max_words / chunk_max_workers) against a single,
fixed Whisper transcript, scoring each result's WER/CER against a reference. Whisper runs
once (or is skipped via --text-file) since chunking only affects the ASR-fix step — isolates
the comparison to the chunking variable. See benchmarks/README.md."""
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
from benchmarks.report import build_summary_rows, write_summary_json
from benchmarks.score import load_reference_text, score_transcript
from benchmarks.stack_config import merge_stack_env, resolve_whisper_block, stack_env_to_preprocess_kwargs

DEFAULT_AUDIO = ROOT / "public/consulta-real-1.mp4"
DEFAULT_REFERENCE = ROOT / "benchmarks/references/consulta-real-1.txt"
DEFAULT_STACKS_PATH = ROOT / "benchmarks/stacks_anamnesia-3-best.yaml"
DEFAULT_STACK_ID = "spectral_lpf_agc"
DEFAULT_PROMPT_PATH = ROOT / "benchmarks/prompts/medical-transcript-editor.md"

# id -> chunk_max_words / chunk_max_workers / label. chunk_parallel is always True — with
# chunk_max_workers=1 that's equivalent to sequential, so it's not a separate axis.
CHUNK_CONFIGS: dict[str, dict] = {
    "no_chunk": {
        "chunk_max_words": 0,
        "chunk_max_workers": 1,
        "label": "sem chunk (1 chamada só)",
    },
    "chunk_450_w1": {
        "chunk_max_words": 450,
        "chunk_max_workers": 1,
        "label": "450 palavras / 1 worker (.env atual)",
    },
    "chunk_450_w4": {
        "chunk_max_words": 450,
        "chunk_max_workers": 4,
        "label": "450 palavras / 4 workers",
    },
    "chunk_250_w4": {
        "chunk_max_words": 250,
        "chunk_max_workers": 4,
        "label": "250 palavras / 4 workers",
    },
    "chunk_700_w2": {
        "chunk_max_words": 700,
        "chunk_max_workers": 2,
        "label": "700 palavras / 2 workers",
    },
}


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


def _write_sweep_markdown(path: Path, rows: list[dict], *, meta: dict) -> None:
    lines = [
        "# ASR-fix chunk sweep summary",
        "",
        f"- Audio: `{meta.get('audio', '')}`",
        f"- Reference: `{meta.get('reference', '')}`",
        f"- Whisper WER (no ASR fix): `{meta.get('whisper_wer_percent', '')}%`",
        f"- Whisper CER (no ASR fix): `{meta.get('whisper_cer_percent', '')}%`",
        "",
        "Lower WER is better. `Chunks` = number of LLM calls made for that config.",
        "",
        "| Rank | Config | WER % | CER % | Time (s) | Chunks | Workers |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | {row['label']} | {row['scores']['wer_percent']} | "
            f"{row['scores']['cer_percent']} | {row['duration_s']} | "
            f"{row['chunk_count']} | {row['chunk_max_workers']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sweep ASR-fix chunk_max_words/chunk_max_workers configs, score WER/CER vs a reference."
    )
    parser.add_argument("--audio", default=str(DEFAULT_AUDIO))
    parser.add_argument("--reference", default=str(DEFAULT_REFERENCE))
    parser.add_argument("--stack", default=DEFAULT_STACK_ID, help="Preprocess stack id (from --stacks-file)")
    parser.add_argument("--stacks-file", default=str(DEFAULT_STACKS_PATH))
    parser.add_argument("--text-file", help="Skip audio/Whisper; sweep chunk configs over this raw text file")
    parser.add_argument("--prompt", default=None, help="ASR editor prompt path override")
    parser.add_argument("--only", help="Comma-separated chunk config ids to run (default: all)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output).resolve()
        if args.output
        else ROOT / f"benchmarks/results/asr-fix-chunk-sweep-consulta-real-1/{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    app_config = _config_dict()
    llm = resolve_llm_settings(app_config)
    prompt_path = _resolve_prompt_path(args.prompt)

    reference_path = Path(args.reference).resolve()
    if not reference_path.is_file():
        print(f"Reference not found: {reference_path}", file=sys.stderr)
        return 1
    reference_text = load_reference_text(reference_path)

    raw_text = ""
    stages: list[str] = []

    if args.text_file:
        text_path = Path(args.text_file).resolve()
        if not text_path.is_file():
            print(f"Text file not found: {text_path}", file=sys.stderr)
            return 1
        raw_text = text_path.read_text(encoding="utf-8").strip()
        print(f"Input: {text_path.relative_to(ROOT)} ({len(raw_text.split())} words)")
    else:
        stacks_path = Path(args.stacks_file).resolve()
        if not stacks_path.is_file():
            print(f"Stacks config not found: {stacks_path}", file=sys.stderr)
            return 1
        stack_config = yaml.safe_load(stacks_path.read_text(encoding="utf-8"))
        if args.stack not in stack_config.get("stacks", {}):
            print(f"Unknown stack: {args.stack}", file=sys.stderr)
            return 1

        audio_path = Path(args.audio).resolve()
        if not audio_path.is_file():
            print(f"Audio not found: {audio_path}", file=sys.stderr)
            return 1

        stack_env = merge_stack_env(stack_config["stacks"][args.stack])
        whisper_cfg = resolve_whisper_block(stack_config["whisper"])
        work_wav = output_dir / f"{args.stack}.wav"

        print(f"Audio: {audio_path.name}")
        print(f"Stack: {args.stack} (held constant across the whole sweep)")

        t0 = time.perf_counter()
        print("1) Preprocess...")
        processed = preprocess_audio(audio_path, work_wav, **stack_env_to_preprocess_kwargs(stack_env))
        stages = [str(stage) for stage in processed.get("stages", [])]
        print(f"   stages={stages} ({time.perf_counter() - t0:.1f}s)")

        t1 = time.perf_counter()
        print("2) Transcribe (Whisper, once — chunking only affects the ASR-fix step below)...")
        transcription = transcribe_wav(work_wav, **transcribe_options_from_mapping(whisper_cfg))
        raw_text = str(transcription.get("text", "")).strip()
        _write_text(output_dir / "00_whisper_raw.txt", raw_text)
        print(f"   done ({time.perf_counter() - t1:.1f}s, {len(raw_text.split())} words)")

    if not raw_text:
        print("No transcript text to process", file=sys.stderr)
        return 1

    whisper_scores = score_transcript(reference_text, raw_text)
    print(
        f"\nWhisper baseline (no ASR fix): WER={whisper_scores['wer_percent']:.2f}% "
        f"CER={whisper_scores['cer_percent']:.2f}%"
    )

    selected = list(CHUNK_CONFIGS.keys())
    if args.only:
        selected = [item.strip() for item in args.only.split(",") if item.strip()]

    results: list[dict] = []
    for config_id in selected:
        if config_id not in CHUNK_CONFIGS:
            print(f"Unknown chunk config id: {config_id}", file=sys.stderr)
            return 1
        cfg = CHUNK_CONFIGS[config_id]
        print(f"\nRunning config: {config_id} ({cfg['label']})")

        t0 = time.perf_counter()
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
            prompt_compact=bool(app_config.get("PROMPT_COMPACT", True)),
            chunk_max_words=cfg["chunk_max_words"],
            chunk_parallel=True,
            chunk_max_workers=cfg["chunk_max_workers"],
        )
        duration_s = round(time.perf_counter() - t0, 2)

        if result["skipped"]:
            print(f"   FAILED: {result['error']}", file=sys.stderr)
            continue

        corrected_text = str(result["text"])
        diff = result.get("diff") or {}
        chunking_meta = result.get("chunking") or {"enabled": False, "chunk_count": 1}
        chunk_count = chunking_meta.get("chunk_count", 1)

        _write_text(output_dir / f"{config_id}.txt", corrected_text)
        diff_path = save_postprocess_diff_file(
            output_dir / f"{config_id}.diff.txt",
            raw_text=raw_text,
            corrected_text=corrected_text,
            diff=diff,
            meta={
                "config_id": config_id,
                "chunk_max_words": cfg["chunk_max_words"],
                "chunk_max_workers": cfg["chunk_max_workers"],
                "chunk_count": chunk_count,
                "duration_s": duration_s,
                "model": result.get("model"),
                "provider": result.get("provider"),
            },
            label=config_id,
        )

        scores = score_transcript(reference_text, corrected_text)
        result_row = {
            "config_id": config_id,
            "label": cfg["label"],
            "chunk_max_words": cfg["chunk_max_words"],
            "chunk_max_workers": cfg["chunk_max_workers"],
            "chunk_count": chunk_count,
            "duration_s": duration_s,
            "scores": scores,
            "diff": {
                "change_count": diff.get("change_count"),
                "word_count_before": diff.get("word_count_before"),
                "word_count_after": diff.get("word_count_after"),
            },
        }
        results.append(result_row)

        result_path = output_dir / f"{config_id}.json"
        result_path.write_text(json.dumps(result_row, ensure_ascii=False, indent=2), encoding="utf-8")

        print(
            f"   ok ({duration_s:.1f}s, {chunk_count} chunk(s), "
            f"WER={scores['wer_percent']:.2f}% CER={scores['cer_percent']:.2f}%)"
        )
        if diff.get("changes"):
            print(format_diff_log(diff, stack_id=config_id))
        print(f"   diff -> {diff_path.relative_to(ROOT)}")

    if not results:
        print("\nNo config produced a result.", file=sys.stderr)
        return 1

    ranked = build_summary_rows(results)
    meta = {
        "audio": str(args.text_file or args.audio),
        "reference": str(reference_path.relative_to(ROOT)) if reference_path.is_relative_to(ROOT) else str(reference_path),
        "whisper_wer_percent": whisper_scores["wer_percent"],
        "whisper_cer_percent": whisper_scores["cer_percent"],
        "prompt_path": str(prompt_path),
        "model": llm["model"],
        "timestamp": timestamp,
    }
    write_summary_json(output_dir / "summary.json", ranked, meta=meta)
    _write_sweep_markdown(output_dir / "summary.md", ranked, meta=meta)

    print("\n" + "=" * 70)
    print("SUMMARY (ranked by WER)")
    print("=" * 70)
    for row in ranked:
        print(
            f"{row['rank']}. {row['label']:<40} WER={row['scores']['wer_percent']:>6.2f}% "
            f"CER={row['scores']['cer_percent']:>6.2f}% time={row['duration_s']:>6.1f}s "
            f"chunks={row['chunk_count']}"
        )
    print(f"\nWrote results to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
