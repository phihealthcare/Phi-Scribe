#!/usr/bin/env python3
"""Compare ASR fix LLM latency: legacy (rules in system_prompt) vs new (rules in prompt)."""
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

from dotenv import load_dotenv

load_dotenv()

from app.config import Config
from app.services.llm_client import medgemma_generate, resolve_llm_settings
from app.services.transcript_postprocess import (
    _build_asr_user_message,
    compose_asr_user_prompt,
    load_editor_prompt,
    resolve_asr_system_prompt,
)

DEFAULT_TEXT = ROOT / "benchmarks/results/whisper-sweep-consulta-real-1/20260706T140329Z/batched_large-v3_int8_b4_beam1.txt"
DEFAULT_PROMPT = ROOT / "benchmarks/prompts/medical-transcript-editor.md"


def _truncate_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words])


def _legacy_payload(instructions: str, task_message: str) -> tuple[str, str]:
    return task_message, instructions


def _new_payload(instructions: str, task_message: str) -> tuple[str, str]:
    return compose_asr_user_prompt(instructions, task_message), resolve_asr_system_prompt()


def _run_once(
    *,
    layout: str,
    instructions: str,
    task_message: str,
    llm: dict[str, str],
    timeout: int,
) -> dict:
    if layout == "legacy":
        prompt, system_prompt = _legacy_payload(instructions, task_message)
    else:
        prompt, system_prompt = _new_payload(instructions, task_message)

    started = time.perf_counter()
    text = medgemma_generate(
        prompt=prompt,
        system_prompt=system_prompt,
        model=llm["model"],
        base_url=llm["base_url"],
        api_key=llm["api_key"],
        temperature=0,
        force_json=False,
        timeout=timeout,
    )
    duration_s = round(time.perf_counter() - started, 2)
    return {
        "layout": layout,
        "duration_s": duration_s,
        "system_prompt_chars": len(system_prompt),
        "prompt_chars": len(prompt),
        "output_words": len(str(text).split()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark ASR prompt layout latency.")
    parser.add_argument("--text-file", default=str(DEFAULT_TEXT))
    parser.add_argument("--prompt", default=str(DEFAULT_PROMPT))
    parser.add_argument("--max-words", type=int, default=400, help="Truncate input for faster runs")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    load_dotenv()
    text_path = Path(args.text_file)
    if not text_path.is_absolute():
        text_path = ROOT / text_path
    if not text_path.is_file():
        print(f"Text file not found: {text_path}", file=sys.stderr)
        return 1

    prompt_path = Path(args.prompt)
    if not prompt_path.is_absolute():
        prompt_path = ROOT / prompt_path

    app_config = {key: getattr(Config, key) for key in dir(Config) if key.isupper()}
    llm = resolve_llm_settings(app_config)
    instructions = load_editor_prompt(prompt_path=prompt_path)
    transcript = _truncate_words(text_path.read_text(encoding="utf-8"), args.max_words)
    task_message = _build_asr_user_message(transcript)

    print(f"Input: {text_path.relative_to(ROOT)} ({len(transcript.split())} words)")
    print(f"Prompt: {prompt_path.relative_to(ROOT)} ({len(instructions)} chars)")
    print(f"Model: {llm['model']}\n")

    results: list[dict] = []
    for layout in ("legacy", "new"):
        print(f"▶ {layout} layout …", flush=True)
        try:
            row = _run_once(
                layout=layout,
                instructions=instructions,
                task_message=task_message,
                llm=llm,
                timeout=args.timeout,
            )
            print(
                f"  {row['duration_s']}s | system={row['system_prompt_chars']} chars | "
                f"prompt={row['prompt_chars']} chars | out={row['output_words']} words"
            )
            results.append(row)
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            results.append({"layout": layout, "error": str(exc)})

    ok = [row for row in results if "duration_s" in row]
    if len(ok) == 2:
        legacy_s = ok[0]["duration_s"]
        new_s = ok[1]["duration_s"]
        delta = new_s - legacy_s
        pct = (delta / legacy_s * 100) if legacy_s else 0
        print(f"\nΔ new − legacy: {delta:+.2f}s ({pct:+.1f}%)")
        if new_s < legacy_s:
            print("New layout is faster.")
        elif new_s > legacy_s:
            print("New layout is slower (within normal LLM variance).")
        else:
            print("Same wall time.")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "text_file": str(text_path.relative_to(ROOT)),
        "prompt_path": str(prompt_path.relative_to(ROOT)),
        "input_words": len(transcript.split()),
        "results": results,
    }
    if args.output:
        out = Path(args.output)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = ROOT / "benchmarks/results/asr-prompt-layout-benchmark" / f"{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {out.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
