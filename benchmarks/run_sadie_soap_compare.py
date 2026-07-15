#!/usr/bin/env python3
"""Compare SOAP on Sadie transcript variants (minimal artifacts)."""
from __future__ import annotations

import argparse
import json
import re
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
from app.services.llm_client import resolve_llm_settings
from app.services.pipeline_steps import prompt_compact_for_config
from app.services.soap_draft import generate_soap_draft
from app.services.soap_format import format_soap_plain_text
from app.services.transcript_postprocess import label_diarized_transcript

DEFAULT_PIPELINE_DIR = (
    ROOT / "uploads/processed/a3962a7f-4df0-42fe-b5a5-ad7d1042e77b.pipeline"
)
_SPEAKER_LINE_RE = re.compile(r"^(Falante\s+\d+|Médico|Paciente)\s*:\s*(.*)$", re.IGNORECASE)


def _parse_speaker_lines(text: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for raw_line in text.strip().splitlines():
        match = _SPEAKER_LINE_RE.match(raw_line.strip())
        if match:
            lines.append((match.group(1), match.group(2).strip()))
    return lines


def _format_speaker_lines(lines: list[tuple[str, str]]) -> str:
    return "\n".join(f"{label}: {text}" for label, text in lines if text)


def merge_ping_pong_fragments(
    text: str,
    *,
    max_words: int = 3,
    min_run: int = 2,
) -> tuple[str, dict[str, int]]:
    """Merge short alternating speaker lines into one line (dominant word count)."""
    lines = _parse_speaker_lines(text)
    if not lines:
        return text.strip(), {"lines_before": 0, "lines_after": 0, "runs_merged": 0}

    merged: list[tuple[str, str]] = []
    runs_merged = 0
    index = 0
    while index < len(lines):
        run_end = index + 1
        while run_end < len(lines):
            chunk = lines[index:run_end]
            if len(chunk) < min_run:
                run_end += 1
                continue
            if any(len(part[1].split()) > max_words for part in chunk):
                break
            if any(chunk[pos][0] == chunk[pos + 1][0] for pos in range(len(chunk) - 1)):
                break
            if run_end < len(lines):
                nxt_label, nxt_text = lines[run_end]
                if len(nxt_text.split()) <= max_words and nxt_label != chunk[-1][0]:
                    run_end += 1
                    continue
            break

        chunk = lines[index:run_end]
        if (
            len(chunk) >= min_run
            and all(len(part[1].split()) <= max_words for part in chunk)
            and all(chunk[pos][0] != chunk[pos + 1][0] for pos in range(len(chunk) - 1))
        ):
            word_counts: dict[str, int] = {}
            for label, part_text in chunk:
                word_counts[label] = word_counts.get(label, 0) + len(part_text.split())
            winner = max(word_counts, key=word_counts.get)
            merged.append((winner, " ".join(part for _, part in chunk)))
            runs_merged += 1
            index = run_end
            continue

        merged.append(lines[index])
        index += 1

    return _format_speaker_lines(merged), {
        "lines_before": len(lines),
        "lines_after": len(merged),
        "runs_merged": runs_merged,
    }


def _load_config() -> dict:
    return {key: getattr(Config, key) for key in dir(Config) if key.isupper()}


def _label_meta(result: dict) -> dict:
    diff = result.get("diff") or {}
    return {
        "skipped": result.get("skipped"),
        "error": result.get("error"),
        "word_count_before": diff.get("word_count_before"),
        "word_count_after": diff.get("word_count_after"),
        "change_count": diff.get("change_count"),
        "speaker_lines_before": len(_parse_speaker_lines(str(result.get("text", "")))),
    }


def _run_labels(
    text: str,
    *,
    llm: dict,
    enabled: bool,
) -> tuple[str, dict]:
    if not enabled:
        return text, {"skipped": True, "error": "labels_disabled"}
    result = label_diarized_transcript(
        text,
        enabled=True,
        provider=llm["provider"],
        model=llm["model"],
        base_url=llm["base_url"],
        api_key=llm["api_key"],
        timeout=int(llm["timeout"]),
    )
    meta = _label_meta(result)
    if result.get("skipped") or result.get("error"):
        return text, meta
    labeled = str(result["text"]).strip()
    meta["speaker_lines_after"] = len(_parse_speaker_lines(labeled))
    return labeled, meta


def _soap_summary(result: dict) -> dict:
    document = result.get("document") or {}
    return {
        "skipped": result.get("skipped"),
        "error": result.get("error"),
        "failed_section": result.get("failed_section"),
        "validation_errors": result.get("validation_errors"),
        "plain_text": result.get("plain_text"),
        "subjetivo": (document.get("soap") or {}).get("subjetivo"),
        "objetivo": (document.get("soap") or {}).get("objetivo"),
        "avaliacao": (document.get("soap") or {}).get("avaliacao"),
        "plano": (document.get("soap") or {}).get("plano"),
    }


def _load_post_asr_text(pipeline_dir: Path, *, fallback: str) -> tuple[str, dict]:
    """Prefer ASR-fix output when guardrail passed (production path before 04b)."""
    asr_path = pipeline_dir / "08_transcribe_04_llm_asr_fix.json"
    if not asr_path.is_file():
        return fallback, {"source": "format_speakers", "asr_fix": None}
    payload = json.loads(asr_path.read_text(encoding="utf-8"))
    guardrail = (payload.get("response") or {}).get("guardrail") or {}
    text = str((payload.get("response") or {}).get("text", "")).strip()
    if guardrail.get("rejected"):
        return fallback, {
            "source": "format_speakers",
            "asr_fix": "guardrail_rejected",
            "guardrail_reason": guardrail.get("reason"),
        }
    if text:
        return text, {"source": "asr_fix", "asr_fix": "accepted"}
    return fallback, {"source": "format_speakers", "asr_fix": "empty"}


def main() -> int:
    parser = argparse.ArgumentParser(description="SOAP compare: Sadie transcript scenarios.")
    parser.add_argument(
        "--pipeline-dir",
        type=Path,
        default=DEFAULT_PIPELINE_DIR,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks/results/sadie-soap-compare.json",
    )
    parser.add_argument("--skip-label-llm", action="store_true", help="Skip 04b label LLM calls")
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="2x2: TRANSCRIPT_DIARIZATION_LABELS x SOAP_SPLIT (4 SOAP runs)",
    )
    args = parser.parse_args()

    format_path = args.pipeline_dir / "07_transcribe_03_format_speakers.json"
    payload = json.loads(format_path.read_text(encoding="utf-8"))
    format_text = str(payload["response"]["text"]).strip()
    soap_input_text, input_meta = _load_post_asr_text(args.pipeline_dir, fallback=format_text)

    config = _load_config()
    llm = resolve_llm_settings(config)

    merged_text, merge_stats = merge_ping_pong_fragments(soap_input_text)

    labels_on_raw, labels_raw_meta = _run_labels(
        soap_input_text,
        llm=llm,
        enabled=not args.skip_label_llm,
    )
    labels_on_merged, labels_merged_meta = _run_labels(
        merged_text,
        llm=llm,
        enabled=not args.skip_label_llm,
    )

    prompts_dir = Path(str(config.get("SOAP_PROMPTS_DIR", "benchmarks/prompts")))
    if not prompts_dir.is_absolute():
        prompts_dir = ROOT / prompts_dir
    prompt_path = Path(str(config.get("SOAP_DRAFT_PROMPT_PATH", "benchmarks/prompts/soap-draft.md")))
    if not prompt_path.is_absolute():
        prompt_path = ROOT / prompt_path
    prompt_compact = prompt_compact_for_config(config)

    def _common_kwargs(*, split_enabled: bool) -> dict:
        return {
            "enabled": True,
            "provider": llm["provider"],
            "model": llm["model"],
            "base_url": llm["base_url"],
            "api_key": llm["api_key"],
            "prompt_path": prompt_path,
            "prompts_dir": prompts_dir,
            "split_enabled": split_enabled,
            "diarization_enabled": True,
            "timeout": int(llm["timeout"]),
            "max_retries": int(llm["soap_max_retries"]),
            "prompt_compact": prompt_compact,
        }

    if args.matrix:
        matrix_scenarios: list[tuple[str, str, bool, bool, str]] = [
            (
                "labels_off_split_off",
                soap_input_text,
                False,
                False,
                "TRANSCRIPT_DIARIZATION_LABELS_ENABLED=false, SOAP_SPLIT_ENABLED=false",
            ),
            (
                "labels_off_split_on",
                soap_input_text,
                False,
                True,
                "TRANSCRIPT_DIARIZATION_LABELS_ENABLED=false, SOAP_SPLIT_ENABLED=true",
            ),
            (
                "labels_on_split_off",
                labels_on_raw,
                True,
                False,
                "TRANSCRIPT_DIARIZATION_LABELS_ENABLED=true, SOAP_SPLIT_ENABLED=false",
            ),
            (
                "labels_on_split_on",
                labels_on_raw,
                True,
                True,
                "TRANSCRIPT_DIARIZATION_LABELS_ENABLED=true, SOAP_SPLIT_ENABLED=true",
            ),
        ]
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "matrix",
            "source": str(format_path),
            "transcript_input": input_meta,
            "label_steps": {"diarization_labels": labels_raw_meta},
            "config_flags": {
                "PROMPT_COMPACT": prompt_compact,
                "DIARIZATION_ENABLED": True,
            },
            "scenarios": {
                name: {
                    "description": desc,
                    "speaker_lines": len(_parse_speaker_lines(text)),
                    "diarization_labels": labels,
                    "soap_split": split,
                }
                for name, text, labels, split, desc in matrix_scenarios
            },
            "results": {},
        }
        for name, text, labels, split, desc in matrix_scenarios:
            print(f"\n=== SOAP ({name}) — {desc}")
            print(f"    {len(_parse_speaker_lines(text))} speaker lines")
            t0 = time.perf_counter()
            result = generate_soap_draft(
                text,
                postprocess_applied=labels,
                **_common_kwargs(split_enabled=split),
            )
            elapsed = time.perf_counter() - t0
            if isinstance(result.get("document"), dict):
                result["plain_text"] = format_soap_plain_text(result["document"])
            summary = _soap_summary(result)
            summary["duration_s"] = round(elapsed, 1)
            summary["description"] = desc
            summary["speaker_lines"] = len(_parse_speaker_lines(text))
            summary["diarization_labels"] = labels
            summary["soap_split"] = split
            report["results"][name] = summary
            print(
                f"  done in {elapsed:.0f}s skipped={summary['skipped']} "
                f"failed={summary.get('failed_section')} "
                f"errors={len(summary.get('validation_errors') or [])}"
            )
        out_path = args.output if args.output.is_absolute() else ROOT / args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path.relative_to(ROOT)}")
        return 0

    split_enabled = str(config.get("SOAP_SPLIT_ENABLED", "true")).lower() in {"true", "1", "yes"}
    common_kwargs = _common_kwargs(split_enabled=split_enabled)

    scenarios: list[tuple[str, str, bool, str]] = [
        (
            "raw",
            soap_input_text,
            False,
            "Falante 1/2 sem 04b (TRANSCRIPT_DIARIZATION_LABELS_ENABLED=false)",
        ),
        (
            "diarization_labels",
            labels_on_raw,
            True,
            "04b em cima do texto pós-ASR (equivale a TRANSCRIPT_DIARIZATION_LABELS_ENABLED=true)",
        ),
        (
            "merge_plus_labels",
            labels_on_merged,
            True,
            "ping-pong merge + 04b (benchmark extra, não é o pipeline de produção)",
        ),
    ]

    report: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": str(format_path),
        "transcript_input": input_meta,
        "merge_stats": merge_stats,
        "label_steps": {
            "diarization_labels": labels_raw_meta,
            "merge_plus_labels": labels_merged_meta,
        },
        "scenarios": {
            name: {
                "description": desc,
                "speaker_lines": len(_parse_speaker_lines(text)),
            }
            for name, text, _, desc in scenarios
        },
        "results": {},
    }

    for name, text, postprocess_applied, desc in scenarios:
        print(f"\n=== SOAP ({name}) — {desc}")
        print(f"    {len(_parse_speaker_lines(text))} speaker lines")
        t0 = time.perf_counter()
        result = generate_soap_draft(
            text,
            postprocess_applied=postprocess_applied,
            **common_kwargs,
        )
        elapsed = time.perf_counter() - t0
        if isinstance(result.get("document"), dict):
            result["plain_text"] = format_soap_plain_text(result["document"])
        summary = _soap_summary(result)
        summary["duration_s"] = round(elapsed, 1)
        summary["description"] = desc
        summary["speaker_lines"] = len(_parse_speaker_lines(text))
        report["results"][name] = summary
        print(
            f"  done in {elapsed:.0f}s skipped={summary['skipped']} "
            f"failed={summary.get('failed_section')} "
            f"errors={len(summary.get('validation_errors') or [])}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {args.output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
