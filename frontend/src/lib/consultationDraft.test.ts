import { afterEach, describe, expect, it, vi } from "vitest";
import { clearConsultationDraft, loadConsultationDraft, saveConsultationDraft } from "./consultationDraft";

function fakeLocalStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
    key: () => null,
    get length() {
      return store.size;
    },
  } satisfies Storage;
}

describe("consultationDraft", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns null when nothing was saved", () => {
    vi.stubGlobal("localStorage", fakeLocalStorage());
    expect(loadConsultationDraft()).toBeNull();
  });

  it("round-trips a saved draft, including segments", () => {
    vi.stubGlobal("localStorage", fakeLocalStorage());
    const draft = {
      fileId: "abc-123",
      soapSections: { subjetivo: "s", objetivo: "o", avaliacao: "a", plano: "p" },
      segments: [{ start_ms: 0, end_ms: 1000, text: "Bom dia.", speaker_label: "MÉDICO" }],
      updatedAt: "2026-07-10T10:00:00.000Z",
    };

    saveConsultationDraft(draft);
    expect(loadConsultationDraft()).toEqual(draft);
  });

  it("defaults segments to null for a pre-Fase-6 draft that never had them", () => {
    const storage = fakeLocalStorage();
    storage.setItem(
      "phi-scribe:consultation-draft",
      JSON.stringify({ fileId: "abc", soapSections: null, updatedAt: "2026-07-10T10:00:00.000Z" }),
    );
    vi.stubGlobal("localStorage", storage);

    expect(loadConsultationDraft()).toEqual({
      fileId: "abc",
      soapSections: null,
      segments: null,
      updatedAt: "2026-07-10T10:00:00.000Z",
    });
  });

  it("truncates to the most recent segments when the draft exceeds the size cap", () => {
    vi.stubGlobal("localStorage", fakeLocalStorage());
    const longText = "x".repeat(10_000);
    const segments = Array.from({ length: 1000 }, (_, i) => ({
      start_ms: i * 1000,
      end_ms: i * 1000 + 900,
      text: longText,
      speaker_label: "MÉDICO",
    }));

    saveConsultationDraft({ fileId: "abc", soapSections: null, segments, updatedAt: "2026-07-10T10:00:00.000Z" });

    const restored = loadConsultationDraft();
    expect(restored?.segments?.length).toBe(200);
    expect(restored?.segments?.[0]).toEqual(segments[segments.length - 200]);
    expect(restored?.segments?.[restored!.segments!.length - 1]).toEqual(segments[segments.length - 1]);
  });

  it("clears the draft", () => {
    vi.stubGlobal("localStorage", fakeLocalStorage());
    saveConsultationDraft({ fileId: "abc", soapSections: null, segments: null, updatedAt: "2026-07-10T10:00:00.000Z" });

    clearConsultationDraft();

    expect(loadConsultationDraft()).toBeNull();
  });

  it("returns null for malformed JSON instead of throwing", () => {
    const storage = fakeLocalStorage();
    storage.setItem("phi-scribe:consultation-draft", "{not json");
    vi.stubGlobal("localStorage", storage);

    expect(loadConsultationDraft()).toBeNull();
  });

  it("returns null for a shape missing required keys", () => {
    const storage = fakeLocalStorage();
    storage.setItem("phi-scribe:consultation-draft", JSON.stringify({ fileId: "abc" }));
    vi.stubGlobal("localStorage", storage);

    expect(loadConsultationDraft()).toBeNull();
  });

  it("does not throw when localStorage is unavailable", () => {
    vi.stubGlobal("localStorage", undefined);
    expect(() => saveConsultationDraft({ fileId: "abc", soapSections: null, segments: null, updatedAt: "now" })).not.toThrow();
    expect(loadConsultationDraft()).toBeNull();
    expect(() => clearConsultationDraft()).not.toThrow();
  });
});
