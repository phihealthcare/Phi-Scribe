from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

from app.services.soap_draft import _generate_soap_split


def _section_result(section_id: str, *, ok: bool = True) -> dict:
    if ok:
        return {
            "section_id": section_id,
            "prompt_path": f"/fake/{section_id}.md",
            "raw": "{}",
            "llm_raw": "{}",
            "partial": {section_id: "conteudo"},
            "schema_coerced": False,
            "validation_errors": None,
        }
    return {
        "section_id": section_id,
        "prompt_path": f"/fake/{section_id}.md",
        "raw": "{}",
        "llm_raw": "{}",
        "partial": None,
        "schema_coerced": False,
        "validation_errors": ["resposta não é JSON válido"],
    }


def _split_kwargs(**overrides) -> dict:
    kwargs: dict = dict(
        segmented_transcript="Paciente: dor. Médico: ok.",
        diarization_enabled=False,
        postprocess_applied=False,
        provider="phihc",
        model="test",
        base_url="https://api.example.com",
        api_key="key",
        prompts_dir=Path("benchmarks/prompts"),
        tracker=None,
        timeout=30,
        max_retries=0,
    )
    kwargs.update(overrides)
    return kwargs


def test_subjetivo_and_objetivo_run_concurrently() -> None:
    """Objetivo must be able to start before Subjetivo's blocking call returns."""
    objetivo_started = threading.Event()

    def fake_generate_section(spec, **kwargs):
        if spec.section_id == "subjetivo":
            assert objetivo_started.wait(timeout=2), "objetivo never started while subjetivo was running"
        elif spec.section_id == "objetivo":
            objetivo_started.set()
        return _section_result(spec.section_id)

    with patch("app.services.soap_draft._generate_soap_section", side_effect=fake_generate_section):
        result = _generate_soap_split(**_split_kwargs(parallel_subjetivo_objetivo=True))

    assert result["failed_section"] != "subjetivo"
    assert result["failed_section"] != "objetivo"


def test_sequential_mode_preserves_original_order() -> None:
    order: list[str] = []

    def fake_generate_section(spec, **kwargs):
        order.append(spec.section_id)
        return _section_result(spec.section_id)

    with patch("app.services.soap_draft._generate_soap_section", side_effect=fake_generate_section):
        _generate_soap_split(**_split_kwargs(parallel_subjetivo_objetivo=False))

    assert order == ["subjetivo", "objetivo", "avaliacao", "plano"]


def test_parallel_mode_still_runs_avaliacao_and_plano_after_both_finish() -> None:
    order: list[str] = []
    lock = threading.Lock()

    def fake_generate_section(spec, **kwargs):
        with lock:
            order.append(spec.section_id)
        return _section_result(spec.section_id)

    with patch("app.services.soap_draft._generate_soap_section", side_effect=fake_generate_section):
        _generate_soap_split(**_split_kwargs(parallel_subjetivo_objetivo=True))

    assert set(order[:2]) == {"subjetivo", "objetivo"}
    assert order[2:] == ["avaliacao", "plano"]


def test_subjetivo_failure_takes_priority_over_objetivo_success() -> None:
    def fake_generate_section(spec, **kwargs):
        if spec.section_id == "subjetivo":
            return _section_result("subjetivo", ok=False)
        return _section_result(spec.section_id)

    with patch("app.services.soap_draft._generate_soap_section", side_effect=fake_generate_section):
        result = _generate_soap_split(**_split_kwargs(parallel_subjetivo_objetivo=True))

    assert result["failed_section"] == "subjetivo"
    assert result["document"] is None


def test_objetivo_only_failure_is_reported_as_objetivo() -> None:
    def fake_generate_section(spec, **kwargs):
        if spec.section_id == "objetivo":
            return _section_result("objetivo", ok=False)
        return _section_result(spec.section_id)

    with patch("app.services.soap_draft._generate_soap_section", side_effect=fake_generate_section):
        result = _generate_soap_split(**_split_kwargs(parallel_subjetivo_objetivo=True))

    assert result["failed_section"] == "objetivo"
    assert result["document"] is None


def test_subjetivo_exception_propagates_even_if_objetivo_succeeds() -> None:
    def fake_generate_section(spec, **kwargs):
        if spec.section_id == "subjetivo":
            raise RuntimeError("LLM HTTP 503: overloaded")
        time.sleep(0.05)
        return _section_result(spec.section_id)

    with patch("app.services.soap_draft._generate_soap_section", side_effect=fake_generate_section):
        try:
            _generate_soap_split(**_split_kwargs(parallel_subjetivo_objetivo=True))
        except RuntimeError as exc:
            assert "overloaded" in str(exc)
        else:
            raise AssertionError("expected RuntimeError from subjetivo to propagate")
