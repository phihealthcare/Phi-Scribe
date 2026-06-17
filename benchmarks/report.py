from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def extract_hypothesis_text(payload: dict[str, Any]) -> str:
    transcription = payload.get("transcription")
    if isinstance(transcription, dict):
        return str(transcription.get("text", "")).strip()
    return str(payload.get("text", "")).strip()


def label_from_filename(path: Path) -> str:
    return path.stem


def build_summary_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(results, key=lambda item: (item["scores"]["wer"], item["label"]))
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def write_summary_json(path: Path, rows: list[dict[str, Any]], *, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "results": rows}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_summary_markdown(path: Path, rows: list[dict[str, Any]], *, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Stack benchmark summary",
        "",
        f"- Audio: `{meta.get('audio', '')}`",
        f"- Reference: `{meta.get('reference', '')}`",
        f"- Whisper model: `{meta.get('whisper_model', '')}`",
        "",
        "Lower WER is better.",
        "",
        "| Rank | Label | WER % | CER % | Stages |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        stages = ", ".join(row.get("stages", []))
        lines.append(
            f"| {row['rank']} | {row['label']} | {row['scores']['wer_percent']} | "
            f"{row['scores']['cer_percent']} | `{stages}` |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
