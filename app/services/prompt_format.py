from __future__ import annotations

import re


def compact_prompt_text(text: str) -> str:
    """Remove markdown decoration; keep plain instructions to save LLM tokens."""
    stripped = text.strip()
    if not stripped:
        return ""
    out = stripped
    out = re.sub(r"```\w*\n?", "", out)
    out = out.replace("```", "")
    out = re.sub(r"^#{1,6}\s*", "", out, flags=re.M)
    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
    out = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", out)
    out = re.sub(r"`([^`]+)`", r"\1", out)
    out = re.sub(r"^---+\s*$", "", out, flags=re.M)
    out = re.sub(r"\|", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
