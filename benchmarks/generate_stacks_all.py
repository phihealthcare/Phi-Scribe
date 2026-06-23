#!/usr/bin/env python3
from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.score_transcribe import is_allowed_stack

# Spectral matrix only — never sweep RNNoise or DeepFilterNet in generated stacks.
ENHANCE_EXCLUDE_OVERRIDES: dict[str, bool] = {
    "ENHANCE_VOICE_ENABLED": False,
    "ENHANCE_DEEP_ENABLED": False,
}


def _stack_id(
    *,
    denoiser: str,
    hpf_enabled: bool,
    lpf_enabled: bool,
    agc_enabled: bool,
    loudness_enabled: bool,
    vad_enabled: bool,
) -> str:
    """
    Deterministic, readable ID.
    Enabled blocks are encoded as tokens in a fixed order.
    """

    if denoiser == "denoise":
        base = "spectral"
    elif denoiser == "none":
        base = "none"
    else:
        raise ValueError(f"Unknown denoiser: {denoiser}")

    tokens: list[str] = []
    if hpf_enabled:
        tokens.append("hpf")
    if lpf_enabled:
        tokens.append("lpf")
    if agc_enabled:
        tokens.append("agc")
    if loudness_enabled:
        tokens.append("loudness")
    if vad_enabled:
        tokens.append("vad")

    return base if not tokens else f"{base}_" + "_".join(tokens)


def _build_overrides(
    *,
    denoiser: str,
    hpf_enabled: bool,
    lpf_enabled: bool,
    agc_enabled: bool,
    loudness_enabled: bool,
    vad_enabled: bool,
) -> dict[str, Any]:
    """
    Overrides to apply on top of DEFAULT_STACK_ENV.
    """

    overrides: dict[str, Any] = {}

    if denoiser == "denoise":
        overrides["DENOISE_ENABLED"] = True
        # keep DENOISE_PROP_DECREASE at DEFAULT_STACK_ENV (no sweep)
    elif denoiser == "none":
        pass
    else:
        raise ValueError(f"Unknown denoiser: {denoiser}")

    if hpf_enabled:
        overrides["HPF_ENABLED"] = True
    if lpf_enabled:
        overrides["LPF_ENABLED"] = True
    if agc_enabled:
        overrides["AGC_ENABLED"] = True
    if loudness_enabled:
        overrides["LOUDNESS_ENABLED"] = True
    if vad_enabled:
        overrides["VAD_ENABLED"] = True

    overrides.update(ENHANCE_EXCLUDE_OVERRIDES)
    return overrides


def main() -> None:
    stacks_path = ROOT / "benchmarks" / "stacks.yaml"
    out_path = ROOT / "benchmarks" / "stacks_all_generated.yaml"

    base_cfg = yaml.safe_load(stacks_path.read_text(encoding="utf-8"))

    audio = base_cfg["audio"]
    reference = base_cfg["reference"]
    whisper_cfg = base_cfg["whisper"]
    postprocess_cfg = base_cfg.get("postprocess")

    denoisers = ["denoise", "none"]

    hpf_vals = [False, True]
    lpf_vals = [False, True]
    agc_vals = [False, True]
    loudness_vals = [False, True]
    vad_vals = [False, True]

    # Keep baseline for compatibility with run_stack_benchmark.py.
    # Note: the "none + all blocks off" combination is equivalent to baseline,
    # so we skip generating a duplicate stack ID for it.
    stacks: dict[str, dict[str, Any]] = {"baseline": {}}

    generated_ids: list[str] = []
    for denoiser, hpf_enabled, lpf_enabled, agc_enabled, loudness_enabled, vad_enabled in itertools.product(
        denoisers, hpf_vals, lpf_vals, agc_vals, loudness_vals, vad_vals
    ):
        if (
            denoiser == "none"
            and not hpf_enabled
            and not lpf_enabled
            and not agc_enabled
            and not loudness_enabled
            and not vad_enabled
        ):
            continue

        stack_id = _stack_id(
            denoiser=denoiser,
            hpf_enabled=hpf_enabled,
            lpf_enabled=lpf_enabled,
            agc_enabled=agc_enabled,
            loudness_enabled=loudness_enabled,
            vad_enabled=vad_enabled,
        )
        overrides = _build_overrides(
            denoiser=denoiser,
            hpf_enabled=hpf_enabled,
            lpf_enabled=lpf_enabled,
            agc_enabled=agc_enabled,
            loudness_enabled=loudness_enabled,
            vad_enabled=vad_enabled,
        )
        stacks[stack_id] = overrides
        generated_ids.append(stack_id)

    skipped_enhance: list[str] = []
    for stack_id, overrides in (base_cfg.get("stacks") or {}).items():
        if stack_id == "baseline":
            continue
        if not isinstance(overrides, dict):
            continue
        if not is_allowed_stack(overrides):
            skipped_enhance.append(stack_id)
            continue
        stacks[stack_id] = overrides

    if len(set(stacks.keys())) != len(stacks.keys()):
        raise RuntimeError("Duplicate stack IDs detected.")

    out_payload: dict[str, Any] = {
        "audio": audio,
        "reference": reference,
        "whisper": whisper_cfg,
        "stacks": stacks,
    }
    if postprocess_cfg:
        out_payload["postprocess"] = postprocess_cfg

    out_path.write_text(
        yaml.safe_dump(out_payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    generated_total = len(stacks)
    examples = sorted(set(generated_ids))[:3]
    print(f"Wrote: {out_path}")
    print(f"Total stacks (including baseline): {generated_total}")
    if skipped_enhance:
        print(
            f"Skipped {len(skipped_enhance)} enhance stack(s) from stacks.yaml: "
            f"{', '.join(skipped_enhance)}"
        )
    if examples:
        print("Example stack IDs:")
        for ex in examples:
            print(f"  - {ex}")


if __name__ == "__main__":
    main()
