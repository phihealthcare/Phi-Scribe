from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_summary_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        results,
        key=lambda item: (-item["scores"]["word_count"], item["label"]),
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def write_summary_json(path: Path, rows: list[dict[str, Any]], *, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "results": rows}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _format_delta(delta: int) -> str:
    if delta > 0:
        return f"+{delta}"
    return str(delta)


def write_summary_markdown(path: Path, rows: list[dict[str, Any]], *, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Transcribe word-count benchmark summary",
        "",
        f"- Audio: `{meta.get('audio', '')}`",
        f"- Whisper model: `{meta.get('whisper_model', '')}`",
        f"- Reference: `{meta.get('reference', '')}`",
        f"- Reference words: `{meta.get('reference_word_count', '')}`",
        f"- Stacks run: `{meta.get('stacks_run', '')}`",
        f"- Stacks skipped: `{meta.get('stacks_skipped', 0)}`",
        "",
        "Higher word count is better (proxy for capture rate; not ground-truth accuracy).",
        "",
        "| Rank | Label | Words | Δ vs reference | Stages |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        stages = ", ".join(row.get("stages", []))
        delta = row["scores"]["delta_vs_reference"]
        lines.append(
            f"| {row['rank']} | {row['label']} | {row['scores']['word_count']} | "
            f"{_format_delta(delta)} | `{stages}` |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
