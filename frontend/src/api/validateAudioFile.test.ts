import { describe, expect, it } from "vitest";
import { DEFAULT_MAX_UPLOAD_BYTES, ValidationError, validateAudioFile } from "./validateAudioFile";

function makeFile(name: string, sizeBytes: number, type = "audio/mpeg"): File {
  const content = sizeBytes > 0 ? new Uint8Array(sizeBytes) : new Uint8Array(0);
  return new File([content], name, { type });
}

describe("validateAudioFile", () => {
  it("accepts a valid mp3 under the default size limit", () => {
    const file = makeFile("consulta.mp3", 1024);
    expect(() => validateAudioFile(file)).not.toThrow();
  });

  it("accepts wav, mp4, and webm extensions", () => {
    expect(() => validateAudioFile(makeFile("consulta.wav", 1024))).not.toThrow();
    expect(() => validateAudioFile(makeFile("consulta.mp4", 1024))).not.toThrow();
    expect(() => validateAudioFile(makeFile("consulta-gravada.webm", 1024))).not.toThrow();
  });

  it("rejects an empty file", () => {
    const file = makeFile("consulta.mp3", 0);
    expect(() => validateAudioFile(file)).toThrow(ValidationError);
    expect(() => validateAudioFile(file)).toThrow(/vazio/i);
  });

  it("rejects an unsupported extension with a clear pt-BR message", () => {
    const file = makeFile("relatorio.pdf", 1024);
    expect(() => validateAudioFile(file)).toThrow(ValidationError);
    expect(() => validateAudioFile(file)).toThrow(/MP3, WAV, MP4 ou WEBM/);
  });

  it("rejects a file without an extension", () => {
    const file = makeFile("consulta", 1024);
    expect(() => validateAudioFile(file)).toThrow(ValidationError);
  });

  it("rejects a file over the given max size, with the limit in the message", () => {
    const file = makeFile("consulta.mp3", 2000);
    expect(() => validateAudioFile(file, 1000)).toThrow(ValidationError);
    expect(() => validateAudioFile(file, 1000)).toThrow(/muito grande/i);
  });

  it("rejects a file over the default 110 MB limit", () => {
    const file = makeFile("consulta.mp3", DEFAULT_MAX_UPLOAD_BYTES + 1);
    expect(() => validateAudioFile(file)).toThrow(/Tamanho máximo: 110 MB/);
  });

  it("accepts a file exactly at the size limit", () => {
    const file = makeFile("consulta.mp3", 1000);
    expect(() => validateAudioFile(file, 1000)).not.toThrow();
  });
});
