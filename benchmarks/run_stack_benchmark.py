#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from dotenv import load_dotenv

from app.services.audio_processor import preprocess_audio
from app.services.transcribe import transcribe_options_from_mapping, transcribe_wav
from app.services.transcript_postprocess import edit_transcript, format_diff_log, save_postprocess_diff_file
from benchmarks.report import build_summary_rows, write_summary_json, write_summary_markdown
from benchmarks.score import load_reference_text, score_transcript
from benchmarks.stack_config import merge_stack_env, stack_env_to_preprocess_kwargs

load_dotenv()


def _load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _preprocess_metadata(processed: dict) -> dict:
    metadata = {"stages": processed.get("stages", [])}
    for key in ("enhance_deep", "enhance_voice", "loudness", "vad"):
        if key in processed:
            metadata[key] = processed[key]
    return metadata


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes"}


def _postprocess_options_from_config(config: dict, *, cli_enabled: bool | None = None) -> dict:
    postprocess_cfg = config.get("postprocess") or {}
    prompt_path_raw = postprocess_cfg.get("prompt_path") or os.environ.get(
        "TRANSCRIPT_POSTPROCESS_PROMPT_PATH",
        "",
    ).strip()
    prompt_path = None
    if prompt_path_raw:
        prompt_path = Path(prompt_path_raw)
        if not prompt_path.is_absolute():
            prompt_path = ROOT / prompt_path

    if cli_enabled is not None:
        enabled = cli_enabled
    elif "enabled" in postprocess_cfg:
        enabled = bool(postprocess_cfg.get("enabled"))
    else:
        enabled = _env_bool("TRANSCRIPT_POSTPROCESS_ENABLED", False)

    model = (
        postprocess_cfg.get("model")
        or os.environ.get("TRANSCRIPT_POSTPROCESS_MODEL", "").strip()
        or "gpt-4o-mini"
    )

    return {
        "enabled": enabled,
        "provider": str(
            postprocess_cfg.get("provider")
            or os.environ.get("TRANSCRIPT_POSTPROCESS_PROVIDER", "openai")
        ),
        "model": str(model),
        "api_key": os.environ.get("OPENAI_API_KEY", "").strip() or None,
        "prompt_path": prompt_path,
    }


def _apply_postprocess(
    *,
    transcription: dict,
    stages: list[str],
    postprocess_options: dict,
) -> tuple[dict, dict | None, dict | None]:
    if not postprocess_options.get("enabled"):
        return transcription, None, None

    raw_text = str(transcription.get("text", ""))
    postprocess_result = edit_transcript(
        raw_text,
        enabled=True,
        provider=postprocess_options["provider"],
        model=postprocess_options["model"],
        api_key=postprocess_options["api_key"],
        prompt_path=postprocess_options["prompt_path"],
        preprocessing_stages=stages,
    )
    postprocess_meta = {
        "enabled": True,
        "provider": postprocess_result["provider"],
        "model": postprocess_result["model"],
        "skipped": postprocess_result["skipped"],
        "error": postprocess_result["error"],
        "preprocessing_stages": stages,
    }

    if postprocess_result["skipped"]:
        return transcription, postprocess_meta, None

    transcription = dict(transcription)
    transcription["raw_text"] = raw_text
    transcription["text"] = postprocess_result["text"]
    if diff := postprocess_result.get("diff"):
        postprocess_meta["diff"] = diff
    return transcription, postprocess_meta, postprocess_result


def _run_stack(
    *,
    stack_id: str,
    stack_env: dict,
    audio_path: Path,
    work_dir: Path,
    whisper_cfg: dict,
    reference_text: str,
    remove_fillers: bool,
    postprocess_options: dict,
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
    preprocess_metadata = _preprocess_metadata(processed)
    stages = preprocess_metadata["stages"]

    scores_raw = score_transcript(
        reference_text,
        transcription["text"],
        remove_fillers=remove_fillers,
    )
    transcription, postprocess_meta, _ = _apply_postprocess(
        transcription=transcription,
        stages=stages,
        postprocess_options=postprocess_options,
    )
    scores = (
        score_transcript(reference_text, transcription["text"], remove_fillers=remove_fillers)
        if postprocess_meta and not postprocess_meta["skipped"]
        else scores_raw
    )

    result = {
        "stack_id": stack_id,
        "label": stack_id,
        "stack_env": stack_env,
        "stages": stages,
        "preprocess_metadata": preprocess_metadata,
        "transcription": transcription,
        "scores": scores,
    }
    if postprocess_meta:
        result["postprocess"] = postprocess_meta
        result["scores_raw"] = scores_raw
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run phi-scribe preprocessing stack benchmark.")
    parser.add_argument("--stacks", default="benchmarks/stacks.yaml")
    parser.add_argument("--only", help="Comma-separated stack ids to run")
    parser.add_argument("--remove-fillers", action="store_true")
    parser.add_argument(
        "--postprocess",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run LLM post-edit after Whisper (overrides YAML/env; requires OPENAI_API_KEY)",
    )
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
    postprocess_options = _postprocess_options_from_config(config, cli_enabled=args.postprocess)
    if postprocess_options.get("enabled") and not postprocess_options.get("api_key"):
        print("Warning: postprocess enabled but OPENAI_API_KEY is not set.", file=sys.stderr)
    stacks: dict = config["stacks"]

    selected = list(stacks.keys())
    if args.only:
        selected = [item.strip() for item in args.only.split(",") if item.strip()]
    elif "baseline" not in selected:
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
            postprocess_options=postprocess_options,
        )
        result_path = output_dir / f"{stack_id}.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        postprocess = result.get("postprocess", {})
        transcription = result.get("transcription", {})
        if (
            postprocess
            and not postprocess.get("skipped")
            and transcription.get("raw_text")
            and transcription.get("text")
        ):
            diff_path = save_postprocess_diff_file(
                output_dir / f"{stack_id}.postprocess.diff.txt",
                raw_text=str(transcription["raw_text"]),
                corrected_text=str(transcription["text"]),
                diff=postprocess.get("diff"),
                meta={
                    "stack_id": stack_id,
                    "provider": postprocess.get("provider"),
                    "model": postprocess.get("model"),
                    "preprocessing_stages": ", ".join(postprocess.get("preprocessing_stages", [])),
                },
                label=stack_id,
            )
            print(f"  Wrote {diff_path.relative_to(ROOT)}")
        results.append(result)
        line = (
            f"  WER={result['scores']['wer_percent']}% "
            f"CER={result['scores']['cer_percent']}% "
            f"stages={result['stages']}"
        )
        if postprocess_options.get("enabled"):
            postprocess = result.get("postprocess", {})
            if postprocess.get("skipped"):
                line += f" postprocess=skipped ({postprocess.get('error')})"
            elif "scores_raw" in result:
                line += (
                    f" postprocess=ok "
                    f"WER_raw={result['scores_raw']['wer_percent']}%"
                )
                diff = postprocess.get("diff")
                if diff:
                    print(format_diff_log(diff, stack_id=stack_id))
        print(line)

    ranked = build_summary_rows(results)
    meta = {
        "audio": str(audio_path.relative_to(ROOT)),
        "reference": str(reference_path.relative_to(ROOT)),
        "whisper_model": whisper_cfg.get("model", whisper_cfg.get("MODEL", "")),
        "postprocess_enabled": postprocess_options.get("enabled", False),
        "postprocess_model": postprocess_options.get("model") if postprocess_options.get("enabled") else None,
        "timestamp": timestamp,
    }
    write_summary_json(output_dir / "summary.json", ranked, meta=meta)
    write_summary_markdown(output_dir / "summary.md", ranked, meta=meta)
    print(f"\nWrote results to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
