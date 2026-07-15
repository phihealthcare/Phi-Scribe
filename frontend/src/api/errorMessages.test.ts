import { describe, expect, it } from "vitest";
import { ApiRequestError } from "./client";
import { toUserMessage } from "./errorMessages";
import { ValidationError } from "./validateAudioFile";

describe("toUserMessage", () => {
  it("passes ValidationError messages through unchanged (already pt-BR)", () => {
    expect(toUserMessage(new ValidationError("Formato não suportado. Use MP3, WAV ou MP4."))).toBe(
      "Formato não suportado. Use MP3, WAV ou MP4.",
    );
  });

  it("maps HTTP 413 to a clear server-side size message", () => {
    expect(toUserMessage(new ApiRequestError("Request Entity Too Large", 413))).toBe(
      "Arquivo muito grande para o servidor.",
    );
  });

  it("maps HTTP 404 (e.g. missing processed audio for transcribe) to a retry hint", () => {
    expect(toUserMessage(new ApiRequestError("Processed audio not found for file_id: abc", 404))).toBe(
      "Áudio processado não encontrado. Envie o arquivo novamente.",
    );
  });

  it("maps status 0 with a timeout message to a transcription-took-too-long message", () => {
    expect(toUserMessage(new ApiRequestError("Request to /x/transcribe timed out after 1200000ms", 0))).toBe(
      "A transcrição demorou demais. Tente novamente.",
    );
  });

  it("maps status 0 without a timeout message to a can't-reach-server message", () => {
    expect(toUserMessage(new ApiRequestError("Failed to reach the API: Failed to fetch", 0))).toBe(
      "Não foi possível conectar ao servidor. Verifique se o backend está rodando.",
    );
  });

  it("falls back to the backend-provided message for other statuses", () => {
    expect(toUserMessage(new ApiRequestError("Transcription failed: model error", 500))).toBe(
      "Transcription failed: model error",
    );
  });

  it("falls back to a plain Error's message", () => {
    expect(toUserMessage(new Error("boom"))).toBe("boom");
  });

  it("falls back to a generic message for non-Error throwables", () => {
    expect(toUserMessage("just a string")).toBe("Erro inesperado. Tente novamente.");
  });
});
