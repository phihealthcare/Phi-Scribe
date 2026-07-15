#!/usr/bin/env python3
"""Re-run POST /transcribe flow for an existing processed file_id."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.routes.audio import _run_transcription


def _step_errors(pipeline_dir: Path) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    if not pipeline_dir.is_dir():
        return rows
    for path in sorted(pipeline_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            rows.append({"file": path.name, "step_id": "?", "error": "invalid json"})
            continue
        rows.append(
            {
                "file": path.name,
                "step_id": str(entry.get("step_id", "?")),
                "skipped": entry.get("skipped"),
                "error": entry.get("error"),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-run transcribe for an existing file_id")
    parser.add_argument("file_id", help="Processed audio UUID (without extension)")
    parser.add_argument(
        "--keep-logs",
        action="store_true",
        help="Do not delete existing pipeline log directory before run",
    )
    parser.add_argument(
        "--save",
        type=Path,
        default=None,
        help="Write the full pipeline response JSON to this path (not persisted by default, "
        "unlike the HTTP route which saves it via _save_transcript)",
    )
    args = parser.parse_args()

    file_id = args.file_id.strip()
    app = create_app()
    processed = Path(app.config["PROCESSED_FOLDER"])
    wav_path = processed / f"{file_id}.wav"
    pipeline_dir = processed / f"{file_id}.pipeline"

    if not wav_path.is_file():
        print(f"ERROR: wav not found: {wav_path}", file=sys.stderr)
        return 1

    if pipeline_dir.is_dir() and not args.keep_logs:
        shutil.rmtree(pipeline_dir)
        print(f"Cleared pipeline log: {pipeline_dir}")

    print(f"Transcribing: {file_id}")
    print(f"Audio: {wav_path}")

    with app.app_context():
        response, status = _run_transcription(
            wav_path,
            file_id=file_id,
            preprocessing="upload_pipeline",
        )

    print(f"HTTP status: {status}")
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved response: {args.save}")
    soap = response.get("soap_draft") or {}
    print(f"SOAP skipped: {soap.get('skipped')} error: {soap.get('error')}")
    if soap.get("validation_errors"):
        print(f"SOAP validation_errors: {soap['validation_errors']}")

    postprocess = response.get("postprocess") or {}
    print(f"Postprocess error: {postprocess.get('error')}")

    errors = [row for row in _step_errors(pipeline_dir) if row.get("error")]
    skipped = [row for row in _step_errors(pipeline_dir) if row.get("skipped")]

    print(f"\nPipeline steps: {len(_step_errors(pipeline_dir))} files, {len(skipped)} skipped")
    if errors:
        print("Steps with error:")
        for row in errors:
            print(f"  - {row['step_id']}: {row['error']}")
        return 2

    print("All executed steps completed without error.")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
