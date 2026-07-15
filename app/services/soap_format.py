from __future__ import annotations

from typing import Any, Mapping


def format_soap_plain_text(document: Mapping[str, Any] | None) -> str:
    """Render merged SOAP JSON as ambulatory plain text (section headers + body)."""
    if not document:
        return ""

    soap = document.get("soap")
    if not isinstance(soap, dict):
        return ""

    sections: list[tuple[str, str]] = []
    for key, title in (
        ("subjetivo", "Subjetivo"),
        ("objetivo", "Objetivo"),
        ("avaliacao", "Avaliação"),
        ("plano", "Plano"),
    ):
        value = soap.get(key)
        if isinstance(value, str) and value.strip():
            sections.append((title, value.strip()))

    if not sections:
        return ""

    parts: list[str] = []
    for index, (title, body) in enumerate(sections):
        if index > 0:
            parts.append("")
        if index == 0 and title == "Subjetivo":
            parts.append(body)
        else:
            parts.append(title)
            parts.append("")
            parts.append(body)

    return "\n".join(parts).strip()
