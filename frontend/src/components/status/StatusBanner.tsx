import { Alert, Button, Spinner } from "react-bootstrap";
import type { ConsultationErrorPhase, ConsultationStatus } from "../../api/types";

interface StatusBannerProps {
  status: ConsultationStatus;
  error: string | null;
  errorPhase: ConsultationErrorPhase;
  onRetryTranscribe: () => void;
  onDismiss: () => void;
}

const ERROR_HEADING: Record<Exclude<ConsultationErrorPhase, null>, string> = {
  validation: "Não foi possível enviar este arquivo",
  upload: "Falha ao enviar áudio",
  transcribe: "Falha ao transcrever a consulta",
};

/**
 * Whether StatusBanner would render anything for this status — use this to
 * decide whether to give ConsultationLayout a banner slot at all, so an
 * "idle"/"done" status doesn't leave an empty spacer row.
 */
export function hasStatusBanner(status: ConsultationStatus): boolean {
  return status === "uploading" || status === "transcribing" || status === "error";
}

export default function StatusBanner({ status, error, errorPhase, onRetryTranscribe, onDismiss }: StatusBannerProps) {
  if (status === "uploading") {
    return (
      <Alert variant="info" className="d-flex align-items-center gap-2 mb-0">
        <Spinner animation="border" size="sm" />
        Enviando áudio…
      </Alert>
    );
  }

  if (status === "transcribing") {
    return (
      <Alert variant="info" className="d-flex align-items-center gap-2 mb-0">
        <Spinner animation="border" size="sm" />
        Processando consulta (pode levar alguns minutos)…
      </Alert>
    );
  }

  if (status === "error") {
    const heading = errorPhase ? ERROR_HEADING[errorPhase] : "Ocorreu um erro";

    return (
      <Alert variant="danger" className="d-flex align-items-center justify-content-between gap-3 flex-wrap mb-0">
        <div>
          <strong>{heading}.</strong> {error}
        </div>
        <div className="d-flex gap-2">
          {errorPhase === "transcribe" && (
            <Button variant="outline-danger" size="sm" onClick={onRetryTranscribe}>
              Tentar novamente
            </Button>
          )}
          <Button variant="outline-secondary" size="sm" onClick={onDismiss}>
            Dispensar
          </Button>
        </div>
      </Alert>
    );
  }

  return null;
}
