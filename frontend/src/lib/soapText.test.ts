import { describe, expect, it } from "vitest";
import { formatSoapEditableText, formatSoapPlainText, parseSoapEditableText } from "./soapText";

describe("formatSoapPlainText", () => {
  it("omits the heading for a leading, non-empty subjetivo", () => {
    const text = formatSoapPlainText({
      subjetivo: "Cefaleia vespertina.",
      objetivo: "PA 120x80.",
      avaliacao: "HAS controlada.",
      plano: "Manter conduta.",
    });
    expect(text).toBe(
      "Cefaleia vespertina.\n\nObjetivo\n\nPA 120x80.\n\nAvaliação\n\nHAS controlada.\n\nPlano\n\nManter conduta.",
    );
  });

  it("titles the first section when subjetivo is empty", () => {
    const text = formatSoapPlainText({
      subjetivo: "",
      objetivo: "PA 120x80.",
      avaliacao: "",
      plano: "",
    });
    expect(text).toBe("Objetivo\n\nPA 120x80.");
  });

  it("skips empty sections entirely", () => {
    const text = formatSoapPlainText({ subjetivo: "Só isso.", objetivo: "", avaliacao: "", plano: "" });
    expect(text).toBe("Só isso.");
  });

  it("returns an empty string when every section is blank", () => {
    expect(formatSoapPlainText({ subjetivo: "", objetivo: "  ", avaliacao: "", plano: "" })).toBe("");
  });
});

describe("formatSoapEditableText", () => {
  it("includes a heading for every section, including subjetivo", () => {
    const text = formatSoapEditableText({
      subjetivo: "Cefaleia vespertina.",
      objetivo: "PA 120x80.",
      avaliacao: "HAS controlada.",
      plano: "Manter conduta.",
    });
    expect(text).toBe(
      "Subjetivo:\nCefaleia vespertina.\n\nObjetivo:\nPA 120x80.\n\nAvaliação:\nHAS controlada.\n\nPlano:\nManter conduta.",
    );
  });

  it("keeps empty sections with a bare heading", () => {
    const text = formatSoapEditableText({ subjetivo: "Só isso.", objetivo: "", avaliacao: "", plano: "" });
    expect(text).toBe("Subjetivo:\nSó isso.\n\nObjetivo:\n\n\nAvaliação:\n\n\nPlano:\n");
  });
});

describe("parseSoapEditableText", () => {
  it("round-trips through formatSoapEditableText", () => {
    const sections = {
      subjetivo: "Cefaleia vespertina.",
      objetivo: "PA 120x80.",
      avaliacao: "HAS controlada.",
      plano: "Manter conduta.",
    };
    expect(parseSoapEditableText(formatSoapEditableText(sections))).toEqual(sections);
  });

  it("attributes text to the section under its heading, defaulting missing ones to empty", () => {
    const parsed = parseSoapEditableText("Subjetivo:\nDor de cabeça.\n\nPlano:\nAnalgésico.");
    expect(parsed).toEqual({ subjetivo: "Dor de cabeça.", objetivo: "", avaliacao: "", plano: "Analgésico." });
  });

  it("is case-insensitive on headings", () => {
    const parsed = parseSoapEditableText("subjetivo:\nDor.");
    expect(parsed.subjetivo).toBe("Dor.");
  });
});
