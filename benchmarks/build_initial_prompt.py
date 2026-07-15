#!/usr/bin/env python3
"""Build Whisper initial_prompt hotwords from benchmark reference transcripts."""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCES_DIR = ROOT / "benchmarks" / "references"
DEFAULT_OUTPUT = ROOT / "benchmarks" / "prompts" / "whisper-initial-hotwords.txt"

# High-risk ASR errors from benchmark_analysis.md (always prioritized when in refs).
RISK_TERMS = {
    "anticoncepcional",
    "churrasco",
    "colesterol",
    "eletrocardiograma",
    "enjoo",
    "hipertensão",
    "infarto",
    "micção",
    "mioma",
    "tontura",
    "vesícula",
    "visícula",
}

# Terms from benchmark_analysis.md + common clinical vocabulary in PT references.
EXTRA_CLINICAL = {
    "anamnese",
    "anticoncepcional",
    "apendicite",
    "ardência",
    "candidíase",
    "cardiovascular",
    "churrasco",
    "colesterol",
    "corrimento",
    "diabetes",
    "eletrocardiograma",
    "enjoo",
    "escarlatina",
    "febre",
    "ginecológico",
    "hipertensão",
    "infarto",
    "meningite",
    "micção",
    "mioma",
    "nauseada",
    "pneumonia",
    "preventivo",
    "tontura",
    "ultrassom",
    "urinária",
    "vesícula",
    "visícula",
    "vômito",
    "abdômen",
    "antifúngico",
    "calafrios",
    "caminhada",
    "cirurgia",
    "internação",
    "laboratorial",
    "pressão",
    "varizes",
    "endoscopia",
    "meningite",
    "apendicite",
    "escarlatina",
    "umbigo",
    "abdômen",
    "candidíase",
    "antifúngico",
    "camisinha",
    "preservativo",
    "hipertenso",
    "fumante",
    "maço",
    "cirurgia",
    "varizes",
    "tirenol",
    "advil",
    "tylenol",
    "professora",
    "ginecologia",
    "cardiologia",
    "analgésico",
    "antibiótico",
    "hospital",
    "postinho",
    "check-up",
}

CONVERSATIONAL_BLOCKLIST = {
    "relações",
    "relação",
    "alteração",
    "banheiro",
    "entendeu",
    "sentindo",
    "caminhando",
    "preocupada",
    "realmente",
    "problema",
    "medicamento",
    "frequência",
    "sintomas",
    "noite",
    "alimentação",
    "importante",
    "constante",
    "diferente",
    "pouquinho",
    "funciona",
    "melhorar",
    "patrícia",
    "médico",
    "estresse",
    "coração",
}

PT_STOPWORDS = {
    "a",
    "à",
    "ao",
    "aos",
    "aquela",
    "aquelas",
    "aquele",
    "aqueles",
    "aquilo",
    "as",
    "até",
    "com",
    "como",
    "da",
    "das",
    "de",
    "dela",
    "dele",
    "deles",
    "demais",
    "depois",
    "dia",
    "dias",
    "do",
    "dos",
    "e",
    "ela",
    "ele",
    "eles",
    "em",
    "entre",
    "era",
    "essa",
    "esse",
    "esta",
    "está",
    "este",
    "eu",
    "foi",
    "for",
    "há",
    "isso",
    "já",
    "lá",
    "mais",
    "mas",
    "me",
    "mesmo",
    "meu",
    "muito",
    "na",
    "não",
    "nas",
    "ne",
    "né",
    "no",
    "nos",
    "nós",
    "o",
    "os",
    "ou",
    "para",
    "pela",
    "pelo",
    "por",
    "pra",
    "que",
    "se",
    "sem",
    "ser",
    "só",
    "sua",
    "suas",
    "seu",
    "seus",
    "tá",
    "também",
    "te",
    "tem",
    "tenho",
    "ter",
    "toda",
    "todo",
    "todos",
    "tu",
    "um",
    "uma",
    "umas",
    "uns",
    "você",
    "vocês",
    "doutor",
    "doutora",
    "senhor",
    "senhora",
    "entendi",
    "certo",
    "bom",
    "boa",
    "tarde",
    "manhã",
    "muito",
    "bem",
    "agora",
    "aqui",
    "assim",
    "ainda",
    "coisa",
    "coisas",
    "fazer",
    "fica",
    "ficou",
    "gente",
    "hora",
    "tipo",
    "vezes",
    "vida",
    "anos",
    "ano",
    "nome",
    "filha",
    "filho",
    "mãe",
    "pai",
    "mulher",
    "marido",
    "casa",
    "trabalho",
    "escola",
    "porque",
    "quando",
    "onde",
    "sobre",
    "então",
    "disse",
    "falou",
    "perguntar",
    "falar",
    "saber",
    "acho",
    "pode",
    "vou",
    "vai",
    "estou",
    "estava",
    "senti",
    "sinto",
    "dor",
    "doutor",
    "dona",
}

MEDICAL_SUFFIXES = (
    "ção",
    "ções",
    "ite",
    "ites",
    "oma",
    "omas",
    "ose",
    "oses",
    "emia",
    "algia",
    "úria",
    "uria",
    "ico",
    "ica",
    "logia",
    "grama",
    "scopia",
    "centese",
)


def _normalize_token(token: str) -> str:
    return token.strip(".,;:!?\"'()[]").lower()


def _is_clinical_candidate(word: str) -> bool:
    if len(word) < 4 or word in PT_STOPWORDS or word in CONVERSATIONAL_BLOCKLIST:
        return False
    if word.isdigit():
        return False
    if word in EXTRA_CLINICAL:
        return True
    if any(word.endswith(suffix) for suffix in MEDICAL_SUFFIXES):
        return True
    return False


def _reference_texts() -> str:
    return "\n".join(path.read_text(encoding="utf-8").lower() for path in sorted(REFERENCES_DIR.glob("anamnesia-*.txt")))


def _load_reference_terms(path: Path) -> Counter:
    text = path.read_text(encoding="utf-8").lower()
    text = re.sub(r"#[^\n]*", " ", text)
    tokens = [_normalize_token(token) for token in re.findall(r"[\wÀ-ÿ]+", text, flags=re.UNICODE)]
    counts: Counter = Counter()
    for token in tokens:
        if token and _is_clinical_candidate(token):
            counts[token] += 1
    return counts


def _is_expanded_candidate(word: str) -> bool:
    if len(word) < 5 or word in PT_STOPWORDS or word in CONVERSATIONAL_BLOCKLIST:
        return False
    if word.isdigit():
        return False
    return True


def _priority_terms(refs: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for bucket in (RISK_TERMS, EXTRA_CLINICAL):
        for term in sorted(bucket):
            if term in seen or term not in refs:
                continue
            seen.add(term)
            ordered.append(term)
    return ordered


def build_hotwords(*, max_terms: int = 36, strategy: str = "mixed") -> list[str]:
    refs = _reference_texts()
    combined: Counter = Counter()
    for path in sorted(REFERENCES_DIR.glob("anamnesia-*.txt")):
        combined.update(_load_reference_terms(path))

    if strategy == "expanded":
        expanded: Counter = Counter()
        for path in sorted(REFERENCES_DIR.glob("anamnesia-*.txt")):
            text = path.read_text(encoding="utf-8").lower()
            tokens = [_normalize_token(t) for t in re.findall(r"[\wÀ-ÿ]+", text, flags=re.UNICODE)]
            for token in tokens:
                if token and _is_expanded_candidate(token):
                    expanded[token] += 1
        combined = expanded

    selected: list[str] = []
    seen: set[str] = set()

    if strategy in {"mixed", "clinical_only", "risk_first"}:
        for term in _priority_terms(refs):
            if strategy == "clinical_only" and term not in RISK_TERMS and term not in EXTRA_CLINICAL:
                continue
            if len(selected) >= max_terms:
                break
            seen.add(term)
            selected.append(term)

    ranked = sorted(
        combined.items(),
        key=lambda item: (-item[1], -len(item[0]), item[0]),
    )
    for word, _count in ranked:
        if len(selected) >= max_terms:
            break
        if word in seen:
            continue
        if strategy == "clinical_only" and word not in EXTRA_CLINICAL and word not in RISK_TERMS:
            continue
        seen.add(word)
        selected.append(word)
    return selected


def build_initial_prompt(hotwords: list[str], *, compact: bool = False) -> str:
    vocabulary = ", ".join(hotwords)
    if compact:
        return f"pt-BR consulta médica: {vocabulary}."
    return (
        "Transcrição literal de consulta médica em português brasileiro. "
        f"Vocabulário clínico: {vocabulary}."
    )


def prompt_variants() -> list[dict]:
    """Preset prompt configurations for sweep benchmarks."""
    configs = [
        {"label": "terms_34_mixed", "max_terms": 34, "strategy": "mixed", "compact": False},
        {"label": "terms_48_mixed", "max_terms": 48, "strategy": "mixed", "compact": False},
        {"label": "terms_60_mixed", "max_terms": 60, "strategy": "mixed", "compact": False},
        {"label": "terms_80_mixed_compact", "max_terms": 80, "strategy": "mixed", "compact": True},
        {"label": "terms_40_clinical", "max_terms": 40, "strategy": "clinical_only", "compact": False},
        {"label": "terms_50_clinical", "max_terms": 50, "strategy": "clinical_only", "compact": False},
        {"label": "terms_48_risk_first", "max_terms": 48, "strategy": "risk_first", "compact": False},
        {"label": "terms_60_expanded", "max_terms": 60, "strategy": "expanded", "compact": True},
        {"label": "terms_70_expanded", "max_terms": 70, "strategy": "expanded", "compact": True},
    ]
    variants: list[dict] = []
    for cfg in configs:
        hotwords = build_hotwords(max_terms=cfg["max_terms"], strategy=cfg["strategy"])
        variants.append(
            {
                **cfg,
                "term_count": len(hotwords),
                "hotwords": hotwords,
                "prompt": build_initial_prompt(hotwords, compact=cfg["compact"]),
            }
        )
    return variants


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Whisper initial_prompt from reference hotwords.")
    parser.add_argument("--max-terms", type=int, default=48)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strategy", default="mixed", choices=["mixed", "clinical_only", "risk_first", "expanded"])
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    hotwords = build_hotwords(max_terms=args.max_terms, strategy=args.strategy)
    prompt = build_initial_prompt(hotwords, compact=args.compact)

    if args.print_only:
        print(prompt)
        print(f"\n# {len(hotwords)} terms", file=sys.stderr)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(prompt + "\n", encoding="utf-8")
    meta_path = args.output.with_suffix(".terms.txt")
    meta_path.write_text("\n".join(hotwords) + "\n", encoding="utf-8")
    print(f"Wrote {args.output.relative_to(ROOT)}")
    print(f"Wrote {meta_path.relative_to(ROOT)} ({len(hotwords)} terms)")
    print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
