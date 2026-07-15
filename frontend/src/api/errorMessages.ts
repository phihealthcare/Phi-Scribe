import { ApiRequestError } from "./client";
import { ValidationError } from "./validateAudioFile";

/**
 * Maps any error thrown by the API layer to a short pt-BR message safe to
 * show directly in the UI. Falls back to the backend's own `error` message
 * (already surfaced as `ApiRequestError.message` by `client.ts`) when no
 * more specific mapping applies.
 */
export function toUserMessage(err: unknown): string {
  if (err instanceof ValidationError) {
    return err.message;
  }

  if (err instanceof ApiRequestError) {
    if (err.status === 0) {
      if (/timed out/i.test(err.message)) {
        return "A transcrição demorou demais. Tente novamente.";
      }
      return "Não foi possível conectar ao servidor. Verifique se o backend está rodando.";
    }
    if (err.status === 413) {
      return "Arquivo muito grande para o servidor.";
    }
    if (err.status === 404) {
      return "Áudio processado não encontrado. Envie o arquivo novamente.";
    }
    return err.message || "Erro ao comunicar com o servidor.";
  }

  if (err instanceof Error) {
    return err.message;
  }

  return "Erro inesperado. Tente novamente.";
}
