#!/usr/bin/env python3
"""Sweep faster-whisper configs on a fixed pre-processed WAV (no upload / preprocess / LLM)."""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from dotenv import load_dotenv

from app.services.transcribe import (
    _reset_model,
    transcribe_options_from_mapping,
    transcribe_wav,
)
from benchmarks.score import load_reference_text, score_transcript
from benchmarks.stack_config import resolve_whisper_block

DEFAULT_CONFIG = ROOT / "benchmarks" / "whisper_sweep_consulta-real-1.yaml"


def _load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _merge_whisper(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if key == "label":
            continue
        merged[key] = value
    return merged


def _model_cache_key(options: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(options["model_id"]),
        str(options["device"]),
        str(options["compute_type"]),
    )


def _write_summary_markdown(
    path: Path,
    *,
    rows: list[dict[str, Any]],
    meta: dict[str, Any],
) -> None:
    lines = [
        "# Whisper config sweep",
        "",
        f"- WAV: `{meta.get('wav', '')}`",
        f"- Reference: `{meta.get('reference', '')}`",
        f"- Configs run: `{meta.get('configs_run', '')}`",
        f"- Configs failed: `{meta.get('configs_failed', 0)}`",
        f"- Postprocess: off · SOAP: off",
        "",
        "Ranked by WER (lower is better), then wall time (lower is better).",
        "",
        "| Rank | Config | WER | CER | Time (s) | RT factor | Mode | Model | Compute | Batch | Chunk |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | ---: |",
    ]
    for index, row in enumerate(rows, start=1):
        if row.get("error"):
            lines.append(
                f"| {index} | `{row['config_id']}` | — | — | — | — | — | — | — | — | **{row['error']}** |"
            )
            continue
        run = row.get("run") or {}
        wall_s = row.get("wall_duration_s")
        audio_ms = row.get("audio_duration_ms")
        rt = ""
        if wall_s and audio_ms:
            rt = f"{audio_ms / (wall_s * 1000):.2f}x"
        scores = row["scores"]
        lines.append(
            f"| {index} | `{row['config_id']}` "
            f"| {scores['wer_percent']}% | {scores['cer_percent']}% "
            f"| {row.get('wall_duration_s', '')} "
            f"| {rt} "
            f"| {run.get('inference_mode', '')} "
            f"| {run.get('model_id', '')} "
            f"| {run.get('compute_type', '')} "
            f"| {run.get('batch_size', '')} "
            f"| {run.get('chunk_length') or '—'} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _run_config(
    *,
    config_id: str,
    whisper_cfg: dict[str, Any],
    wav_path: Path,
    reference_text: str,
    remove_fillers: bool,
) -> dict[str, Any]:
    label = whisper_cfg.pop("label", config_id)
    resolved = resolve_whisper_block(whisper_cfg)
    options = transcribe_options_from_mapping(resolved)

    started = time.perf_counter()
    transcription = transcribe_wav(wav_path, **options)
    wall_duration_s = round(time.perf_counter() - started, 2)

    hypothesis = str(transcription.get("text", ""))
    scores = score_transcript(reference_text, hypothesis, remove_fillers=remove_fillers)
    run_meta = transcription.get("run") or {}

    return {
        "config_id": config_id,
        "label": label,
        "whisper": resolved,
        "transcription": {
            "text": hypothesis,
            "duration_ms": transcription.get("duration_ms"),
            "run": run_meta,
        },
        "scores": scores,
        "audio_duration_ms": transcription.get("duration_ms"),
        "wall_duration_s": wall_duration_s,
        "run": run_meta,
        "error": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sweep faster-whisper configs on a fixed processed WAV (Whisper-only benchmark).",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG.relative_to(ROOT)),
        help="YAML with wav, reference, whisper_base, and configs matrix",
    )
    parser.add_argument("--only", help="Comma-separated config ids to run")
    parser.add_argument("--output", help="Output directory override")
    parser.add_argument("--wav", help="Override WAV path from YAML")
    parser.add_argument("--remove-fillers", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    config_path = _resolve_path(args.config)
    cfg = _load_config(config_path)

    wav_path = _resolve_path(args.wav or cfg["wav"])
    reference_path = _resolve_path(cfg["reference"])
    if not wav_path.is_file():
        print(f"WAV not found: {wav_path}", file=sys.stderr)
        return 1
    if not reference_path.is_file():
        print(f"Reference not found: {reference_path}", file=sys.stderr)
        return 1

    reference_text = load_reference_text(reference_path)
    whisper_base = resolve_whisper_block(cfg.get("whisper_base") or {})
    configs: dict[str, dict[str, Any]] = cfg.get("configs") or {}
    if not configs:
        print("No configs defined in YAML", file=sys.stderr)
        return 1

    only = {item.strip() for item in (args.only or "").split(",") if item.strip()}
    selected = (
        {key: configs[key] for key in only if key in configs}
        if only
        else configs
    )
    missing = only - set(selected)
    if missing:
        print(f"Unknown config ids: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output).resolve()
        if args.output
        else ROOT / "benchmarks" / "results" / "whisper-sweep-consulta-real-1" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    model_key: tuple[str, str, str] | None = None
    failed = 0

    print(f"WAV: {wav_path}")
    print(f"Reference: {reference_path} ({len(reference_text.split())} words)")
    print(f"Configs: {len(selected)}")
    print(f"Output: {output_dir}\n")

    for config_id, overrides in selected.items():
        whisper_cfg = _merge_whisper(whisper_base, overrides)
        if "label" in overrides:
            whisper_cfg["label"] = overrides["label"]
        options = transcribe_options_from_mapping(resolve_whisper_block(dict(whisper_cfg)))
        cache_key = _model_cache_key(options)
        if model_key != cache_key:
            _reset_model()
            model_key = cache_key

        print(f"▶ {config_id} …", flush=True)
        try:
            result = _run_config(
                config_id=config_id,
                whisper_cfg=dict(whisper_cfg),
                wav_path=wav_path,
                reference_text=reference_text,
                remove_fillers=args.remove_fillers,
            )
            print(
                f"  WER={result['scores']['wer_percent']:.2f}% "
                f"CER={result['scores']['cer_percent']:.2f}% "
                f"wall={result['wall_duration_s']}s "
                f"mode={result['run'].get('inference_mode')}",
            )
        except Exception as exc:
            failed += 1
            _reset_model()
            model_key = None
            result = {
                "config_id": config_id,
                "label": overrides.get("label", config_id),
                "whisper": resolve_whisper_block(_merge_whisper(whisper_base, overrides)),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            print(f"  FAILED: {result['error']}", file=sys.stderr)

        out_json = output_dir / f"{config_id}.json"
        out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.get("transcription", {}).get("text"):
            (output_dir / f"{config_id}.txt").write_text(
                result["transcription"]["text"],
                encoding="utf-8",
            )
        results.append(result)

    ok_rows = [row for row in results if not row.get("error")]
    ranked = sorted(
        ok_rows,
        key=lambda row: (row["scores"]["wer"], row.get("wall_duration_s", 0), row["config_id"]),
    )
    failed_rows = [row for row in results if row.get("error")]
    summary_rows = ranked + failed_rows

    meta = {
        "timestamp": timestamp,
        "config_file": str(config_path.relative_to(ROOT)),
        "wav": str(wav_path.relative_to(ROOT)),
        "reference": str(reference_path.relative_to(ROOT)),
        "configs_run": len(selected),
        "configs_ok": len(ok_rows),
        "configs_failed": failed,
        "postprocess": False,
        "soap": False,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps({"meta": meta, "results": summary_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_summary_markdown(output_dir / "summary.md", rows=summary_rows, meta=meta)

    print(f"\nDone. Summary: {output_dir / 'summary.md'}")
    if ranked:
        best = ranked[0]
        print(
            f"Best WER: {best['config_id']} "
            f"({best['scores']['wer_percent']}%, wall {best['wall_duration_s']}s)",
        )
    return 1 if failed and not ok_rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
