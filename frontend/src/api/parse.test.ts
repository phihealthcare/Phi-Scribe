import { describe, expect, it } from "vitest";
import sectionsFallbackFixture from "../mocks/transcribe-response-sections-fallback.json";
import transcribeFixture from "../mocks/transcribe-response.json";
import uploadFixture from "../mocks/upload-response.json";
import {
  extractEntities,
  extractSegments,
  extractSoapSections,
  parseTranscribeResponse,
  parseUploadResponse,
  ParseError,
} from "./parse";
import type { TranscribeResponse } from "./types";

describe("parseUploadResponse", () => {
  it("accepts the upload-response fixture", () => {
    const result = parseUploadResponse(uploadFixture);
    expect(result.file_id).toBe(uploadFixture.file_id);
    expect(result.processed.wav.sample_rate).toBe(16000);
  });

  it("rejects an object without file_id", () => {
    expect(() => parseUploadResponse({ message: "ok", processed: {} })).toThrow(ParseError);
  });

  it("rejects non-object input", () => {
    expect(() => parseUploadResponse(null)).toThrow(ParseError);
    expect(() => parseUploadResponse("nope")).toThrow(ParseError);
  });
});

describe("parseTranscribeResponse", () => {
  it("accepts the transcribe-response fixture", () => {
    const result = parseTranscribeResponse(transcribeFixture);
    expect(result.file_id).toBe(transcribeFixture.file_id);
    expect(result.transcription.text.length).toBeGreaterThan(0);
  });

  it("rejects a response missing transcription.text", () => {
    expect(() => parseTranscribeResponse({ file_id: "x", transcription: {} })).toThrow(ParseError);
  });

  it("rejects a response missing file_id", () => {
    expect(() => parseTranscribeResponse({ transcription: { text: "hi" } })).toThrow(ParseError);
  });
});

describe("extractSoapSections", () => {
  it("prefers soap_draft.document.soap when present", () => {
    const response = parseTranscribeResponse(transcribeFixture);
    const sections = extractSoapSections(response);
    expect(sections).not.toBeNull();
    expect(Object.keys(sections!).sort()).toEqual(["avaliacao", "objetivo", "plano", "subjetivo"]);
  });

  it("falls back to soap_draft.sections[*].partial when document is null", () => {
    const response = parseTranscribeResponse(sectionsFallbackFixture);
    const sections = extractSoapSections(response);
    expect(sections).not.toBeNull();
    expect(sections).toEqual({
      subjetivo: "Refere dor leve.",
      objetivo: "Sem dados objetivos suficientes na transcrição.",
      avaliacao: "Consulta de rotina.",
      plano: "Retorno em 30 dias.",
    });
  });

  it("returns null when neither document nor sections are usable", () => {
    const response: TranscribeResponse = {
      ...parseTranscribeResponse(transcribeFixture),
      soap_draft: { ...parseTranscribeResponse(transcribeFixture).soap_draft!, document: null, sections: undefined },
    };
    expect(extractSoapSections(response)).toBeNull();
  });

  it("returns null when soap_draft is absent", () => {
    const { soap_draft, ...rest } = parseTranscribeResponse(transcribeFixture);
    void soap_draft;
    expect(extractSoapSections(rest as TranscribeResponse)).toBeNull();
  });
});

describe("extractEntities", () => {
  it("returns an empty list for null sections", () => {
    expect(extractEntities(null)).toEqual([]);
  });

  it("extracts a medication + dosage mention", () => {
    const entities = extractEntities({
      subjetivo: "Refere boa adesão à Losartana 50 mg.",
      objetivo: "",
      avaliacao: "",
      plano: "",
    });
    expect(entities).toContain("Losartana 50 mg");
  });

  it("extracts uppercase acronyms", () => {
    const entities = extractEntities({
      subjetivo: "",
      objetivo: "",
      avaliacao: "HAS em acompanhamento.",
      plano: "",
    });
    expect(entities).toContain("HAS");
  });

  it("de-duplicates case-insensitively and caps the result", () => {
    const repeated = Array.from({ length: 10 }, () => "HAS").join(" ");
    const entities = extractEntities({ subjetivo: repeated, objetivo: "", avaliacao: "", plano: "" });
    expect(entities.filter((e) => e === "HAS")).toHaveLength(1);
    expect(entities.length).toBeLessThanOrEqual(8);
  });

  it("returns an empty list when nothing matches", () => {
    expect(
      extractEntities({ subjetivo: "consulta de rotina, sem queixas.", objetivo: "", avaliacao: "", plano: "" }),
    ).toEqual([]);
  });
});

describe("extractSegments", () => {
  it("returns a non-empty list with speaker_label set", () => {
    const response = parseTranscribeResponse(transcribeFixture);
    const segments = extractSegments(response);
    expect(segments.length).toBeGreaterThan(0);
    expect(segments.every((segment) => Boolean(segment.speaker_label))).toBe(true);
  });

  it("returns an empty list when segments are absent", () => {
    const response: TranscribeResponse = {
      ...parseTranscribeResponse(transcribeFixture),
      transcription: { text: "sem segmentos" },
    };
    expect(extractSegments(response)).toEqual([]);
  });
});
