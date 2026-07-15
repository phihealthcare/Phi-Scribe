import type { SoapSections } from "../api/types";

export const SOAP_SECTION_TITLES: Array<[keyof SoapSections, string]> = [
  ["subjetivo", "Subjetivo"],
  ["objetivo", "Objetivo"],
  ["avaliacao", "Avaliação"],
  ["plano", "Plano"],
];

/**
 * Mirrors the backend's `format_soap_plain_text` (app/services/soap_format.py):
 * subjetivo has no heading (it opens the note), the other sections are
 * titled. Used by "Finalizar consulta" to copy the edited SOAP to the
 * clipboard in the same shape a clinician would expect in a chart note.
 */
export function formatSoapPlainText(sections: SoapSections): string {
  const parts: string[] = [];
  SOAP_SECTION_TITLES.forEach(([key, title], index) => {
    const body = sections[key]?.trim();
    if (!body) return;
    if (parts.length > 0) parts.push("");
    if (index === 0 && key === "subjetivo") {
      parts.push(body);
    } else {
      parts.push(title, "", body);
    }
  });

  return parts.join("\n").trim();
}

/**
 * All four sections combined into one editable block, each under its own
 * "Título:" heading (including Subjetivo) — backs the single textarea in
 * SoapSummaryPanel so a clinician can select-all/copy the whole SOAP in one
 * action instead of four. Paired with `parseSoapEditableText` below.
 */
export function formatSoapEditableText(sections: SoapSections): string {
  return SOAP_SECTION_TITLES.map(([key, title]) => `${title}:\n${sections[key]}`).join("\n\n");
}

/** Inverse of `formatSoapEditableText` — splits edited text back into sections by matching "Título:" heading lines. */
export function parseSoapEditableText(text: string): SoapSections {
  const keysByTitle = new Map(SOAP_SECTION_TITLES.map(([key, title]) => [title.toLowerCase(), key]));
  const result: SoapSections = { subjetivo: "", objetivo: "", avaliacao: "", plano: "" };

  let currentKey: keyof SoapSections | null = null;
  let buffer: string[] = [];

  const flush = () => {
    if (currentKey) result[currentKey] = buffer.join("\n").trim();
    buffer = [];
  };

  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    const headingKey = trimmed.endsWith(":")
      ? keysByTitle.get(trimmed.slice(0, -1).trim().toLowerCase())
      : undefined;
    if (headingKey) {
      flush();
      currentKey = headingKey;
    } else {
      buffer.push(line);
    }
  }
  flush();

  return result;
}
