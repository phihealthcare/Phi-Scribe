#!/usr/bin/env python3
"""Test LLM Autor/Paciente labeling per turn from plain Whisper text (no acoustic diarization)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from app.services.llm_client import DEFAULT_LLM_BASE_URL, medgemma_generate, strip_markdown_fences
from app.services.soap_draft import format_segmented_transcript
from benchmarks.report import extract_hypothesis_text

DEFAULT_PROMPT_PATH = ROOT / "benchmarks/prompts/medical-transcript-speaker-inference.md"
FORMAT_CHOICES = ("plain", "timestamped", "numbered", "all")


def _load_prompt(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _load_transcription(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    transcription = payload.get("transcription")
    if isinstance(transcription, dict):
        raw = transcription.get("raw_text") or transcription.get("text") or ""
        text = str(raw).strip()
        segments = transcription.get("segments")
        if isinstance(segments, list):
            return text, [dict(item) for item in segments if isinstance(item, dict)]
        return text, []
    return extract_hypothesis_text(payload).strip(), []


def _format_plain(text: str) -> str:
    return text.strip()


def _format_timestamped(text: str, segments: list[dict[str, Any]]) -> str:
    if segments:
        return format_segmented_transcript(text, segments=segments)
    return text.strip()


def _format_numbered(text: str, segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    if segments:
        index = 1
        for segment in segments:
            segment_text = str(segment.get("text", "")).strip()
            if segment_text:
                blocks.append(f"[{index}] {segment_text}")
                index += 1
    else:
        chunks = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", text.strip()) if chunk.strip()]
        if not chunks:
            chunks = [text.strip()]
        for index, chunk in enumerate(chunks, start=1):
            blocks.append(f"[{index}] {chunk}")
    return "\n".join(blocks)


def _format_input(fmt: str, text: str, segments: list[dict[str, Any]]) -> str:
    if fmt == "plain":
        return _format_plain(text)
    if fmt == "timestamped":
        return _format_timestamped(text, segments)
    if fmt == "numbered":
        return _format_numbered(text, segments)
    raise ValueError(f"Unknown format: {fmt}")


def _build_user_message(*, input_format: str, transcript_block: str) -> str:
    format_notes = {
        "plain": (
            "A transcrição abaixo é um texto contínuo do ASR, sem rótulos de falante. "
            "Inferir turnos e papéis apenas pelo conteúdo."
        ),
        "timestamped": (
            "A transcrição abaixo está em blocos com timestamp do ASR. "
            "Cada bloco NÃO indica o falante — divida em turnos e rotule Autor vs Paciente."
        ),
        "numbered": (
            "A transcrição abaixo está em blocos numerados [1], [2], … do ASR. "
            "Cada bloco pode conter mais de um turno — divida e rotule Autor vs Paciente."
        ),
    }
    parts = [
        format_notes[input_format],
        "",
        "IMPORTANTE: divida o diálogo em turnos (uma fala por vez). "
        "Para cada turno, preencha `rotulo` como \"Autor\" ou \"Paciente\", "
        "`identificavel` e `motivo`. Complete `identificacao` e `verificacao` antes dos turnos.",
        "",
        f"FORMATO DE ENTRADA: {input_format}",
        "",
        "TRANSCRIÇÃO:",
        "<<<",
        transcript_block.strip(),
        ">>>",
        "FIM DA TRANSCRIÇÃO.",
    ]
    return "\n".join(parts)


def _parse_json_response(raw: str) -> dict[str, Any] | None:
    cleaned = strip_markdown_fences(raw.strip())
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None
    if "response" in parsed and isinstance(parsed.get("response"), str):
        try:
            inner = json.loads(parsed["response"])
            if isinstance(inner, dict):
                return inner
        except json.JSONDecodeError:
            pass
    return parsed


def _turns_list(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    turnos = parsed.get("turnos")
    if isinstance(turnos, list):
        return [item for item in turnos if isinstance(item, dict)]
    linhas = parsed.get("linhas")
    if isinstance(linhas, list):
        return [item for item in linhas if isinstance(item, dict)]
    return []


def _turn_label(item: dict[str, Any]) -> str:
    rotulo = str(item.get("rotulo") or item.get("papel") or "").strip()
    if rotulo.lower() in {"médico", "medico"}:
        return "Autor"
    return rotulo


def _lines_to_transcript(parsed: dict[str, Any]) -> str:
    formatted = parsed.get("transcricao_formatada")
    if isinstance(formatted, str) and formatted.strip():
        return formatted.strip()

    output: list[str] = []
    for item in _turns_list(parsed):
        rotulo = _turn_label(item)
        texto = str(item.get("texto", "")).strip()
        if rotulo and texto:
            output.append(f"{rotulo}: {texto}")
    return "\n".join(output)


def _summarize_identificacao(parsed: dict[str, Any]) -> dict[str, Any]:
    ident = parsed.get("identificacao")
    if not isinstance(ident, dict):
        return {"present": False}

    autor = ident.get("autor") if isinstance(ident.get("autor"), dict) else {}
    if not autor and isinstance(ident.get("medico"), dict):
        autor = ident.get("medico")
    paciente = ident.get("paciente") if isinstance(ident.get("paciente"), dict) else {}

    turnos = _turns_list(parsed)
    resumo = parsed.get("resumo_turnos") if isinstance(parsed.get("resumo_turnos"), dict) else {}
    ambiguos = sum(
        1
        for item in turnos
        if item.get("identificavel") is False or str(item.get("confianca", "")).lower() == "baixa"
    )

    return {
        "present": True,
        "mapeamento_confirmado": bool(ident.get("mapeamento_confirmado")),
        "verificacao": str(ident.get("verificacao", "")).strip(),
        "autor_nome": str(autor.get("nome", "")).strip(),
        "autor_evidencias": autor.get("evidencias") if isinstance(autor.get("evidencias"), list) else [],
        "paciente_nome": str(paciente.get("nome", "")).strip(),
        "paciente_evidencias": paciente.get("evidencias") if isinstance(paciente.get("evidencias"), list) else [],
        "alertas_count": len(parsed.get("alertas", [])) if isinstance(parsed.get("alertas"), list) else 0,
        "turnos_count": len(turnos),
        "turnos_autor": resumo.get("turnos_autor")
        or sum(1 for item in turnos if _turn_label(item) == "Autor"),
        "turnos_paciente": resumo.get("turnos_paciente")
        or sum(1 for item in turnos if _turn_label(item) == "Paciente"),
        "turnos_identificaveis": resumo.get("turnos_identificaveis")
        or sum(1 for item in turnos if item.get("identificavel") is not False),
        "turnos_ambiguos": resumo.get("turnos_ambiguos") or ambiguos,
    }


def _run_inference(
    *,
    input_format: str,
    text: str,
    segments: list[dict[str, Any]],
    system_prompt: str,
    model: str,
    base_url: str,
    api_key: str,
    timeout: int,
) -> dict[str, Any]:
    transcript_block = _format_input(input_format, text, segments)
    user_message = _build_user_message(input_format=input_format, transcript_block=transcript_block)

    t0 = time.perf_counter()
    raw, llm_raw = medgemma_generate(
        prompt=user_message,
        system_prompt=system_prompt,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        temperature=0,
        force_json=True,
        timeout=timeout,
        return_raw=True,
    )
    duration_ms = (time.perf_counter() - t0) * 1000

    parsed = _parse_json_response(raw)
    result: dict[str, Any] = {
        "input_format": input_format,
        "duration_ms": round(duration_ms, 2),
        "input_preview": transcript_block[:500],
        "input_char_count": len(transcript_block),
        "raw": raw,
        "llm_raw": llm_raw,
        "parsed": parsed,
        "error": None,
    }

    if parsed is None:
        result["error"] = "invalid_json_response"
        return result

    result["identificacao_summary"] = _summarize_identificacao(parsed)
    result["transcricao_formatada"] = _lines_to_transcript(parsed)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test LLM Autor/Paciente labeling per turn from plain Whisper text (no diarization)."
    )
    parser.add_argument(
        "--input",
        help="Transcript JSON (API upload, run_flow_test, or run_stack_benchmark output)",
    )
    parser.add_argument(
        "--text-file",
        help="Plain text file instead of --input JSON",
    )
    parser.add_argument(
        "--segments-file",
        help="Optional JSON file with Whisper segments list (used with --text-file)",
    )
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        default="all",
        help="Input shaping for the LLM (default: run all three)",
    )
    parser.add_argument(
        "--prompt",
        default=str(DEFAULT_PROMPT_PATH),
        help="Speaker inference prompt path",
    )
    parser.add_argument("--model", default=os.environ.get("TRANSCRIPT_POSTPROCESS_MODEL", "gemma3:12b-it-qat"))
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL).strip().rstrip("/"))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("LLM_TIMEOUT_SECONDS", "600")))
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: benchmarks/results/speaker-inference-<timestamp>)",
    )
    args = parser.parse_args()

    if not args.input and not args.text_file:
        print("Provide --input JSON or --text-file", file=sys.stderr)
        return 1

    text = ""
    segments: list[dict[str, Any]] = []
    source = ""

    if args.text_file:
        text_path = Path(args.text_file)
        if not text_path.is_file():
            print(f"Text file not found: {text_path}", file=sys.stderr)
            return 1
        text = text_path.read_text(encoding="utf-8").strip()
        source = str(text_path)
        if args.segments_file:
            seg_path = Path(args.segments_file)
            if not seg_path.is_file():
                print(f"Segments file not found: {seg_path}", file=sys.stderr)
                return 1
            seg_payload = json.loads(seg_path.read_text(encoding="utf-8"))
            if isinstance(seg_payload, list):
                segments = [dict(item) for item in seg_payload if isinstance(item, dict)]
            elif isinstance(seg_payload, dict):
                maybe = seg_payload.get("segments")
                if isinstance(maybe, list):
                    segments = [dict(item) for item in maybe if isinstance(item, dict)]
    else:
        input_path = Path(args.input)
        if not input_path.is_file():
            print(f"Input not found: {input_path}", file=sys.stderr)
            return 1
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        text, segments = _load_transcription(payload)
        source = str(input_path)

    if not text:
        print("No transcript text found", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output).resolve()
        if args.output
        else ROOT / f"benchmarks/results/speaker-inference-{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = Path(args.prompt).resolve()
    system_prompt = _load_prompt(prompt_path)
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        print("Warning: LLM_API_KEY not set — request may fail", file=sys.stderr)

    formats = list(FORMAT_CHOICES[:-1]) if args.format == "all" else [args.format]
    results: dict[str, Any] = {
        "source": source,
        "model": args.model,
        "prompt_path": str(prompt_path),
        "segment_count": len(segments),
        "text_char_count": len(text),
        "formats": {},
    }

    (output_dir / "00_input_plain.txt").write_text(text, encoding="utf-8")
    if segments:
        (output_dir / "00_input_segments.json").write_text(
            json.dumps(segments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    for fmt in formats:
        print(f"Running speaker inference — format={fmt} ...")
        formatted_input = _format_input(fmt, text, segments)
        (output_dir / f"00_input_{fmt}.txt").write_text(formatted_input, encoding="utf-8")

        inference = _run_inference(
            input_format=fmt,
            text=text,
            segments=segments,
            system_prompt=system_prompt,
            model=args.model,
            base_url=args.base_url,
            api_key=api_key,
            timeout=args.timeout,
        )
        results["formats"][fmt] = {
            "duration_ms": inference["duration_ms"],
            "error": inference["error"],
            "identificacao_summary": inference.get("identificacao_summary"),
            "transcricao_formatada": inference.get("transcricao_formatada"),
        }

        (output_dir / f"01_result_{fmt}.json").write_text(
            json.dumps(inference, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if inference.get("transcricao_formatada"):
            (output_dir / f"02_labeled_{fmt}.txt").write_text(
                inference["transcricao_formatada"],
                encoding="utf-8",
            )

        summary = inference.get("identificacao_summary") or {}
        if summary.get("present"):
            confirmed = "SIM" if summary.get("mapeamento_confirmado") else "NÃO"
            print(
                f"  → mapeamento_confirmado={confirmed} | "
                f"autor={summary.get('autor_nome') or '?'} | "
                f"paciente={summary.get('paciente_nome') or '?'} | "
                f"turnos={summary.get('turnos_count', 0)} "
                f"(Autor={summary.get('turnos_autor', 0)}, "
                f"Paciente={summary.get('turnos_paciente', 0)}, "
                f"ambíguos={summary.get('turnos_ambiguos', 0)})"
            )
            if summary.get("verificacao"):
                print(f"  → verificação: {summary['verificacao'][:200]}")
        elif inference.get("error"):
            print(f"  → erro: {inference['error']}")
        print()

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved results to {output_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
