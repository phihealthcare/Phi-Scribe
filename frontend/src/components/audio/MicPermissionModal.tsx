import { Button, Modal } from "react-bootstrap";
import type { MicError, MicErrorCode } from "../../lib/audioRecorder";

interface MicPermissionModalProps {
  error: MicError | null;
  onRetry: () => void;
  onDismiss: () => void;
}

const TITLE_BY_CODE: Record<MicErrorCode, string> = {
  denied: "Microfone bloqueado",
  not_found: "Nenhum microfone encontrado",
  busy: "Microfone em uso",
  unsupported: "Gravação não suportada",
  unknown: "Não foi possível acessar o microfone",
};

export default function MicPermissionModal({ error, onRetry, onDismiss }: MicPermissionModalProps) {
  return (
    <Modal show={error !== null} onHide={onDismiss} centered>
      <Modal.Header closeButton>
        <Modal.Title>{error ? TITLE_BY_CODE[error.code] : ""}</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {error?.code === "denied" && (
          <p>
            O navegador bloqueou o acesso ao microfone para esta página. Para liberar: clique no ícone de cadeado
            ao lado do endereço, abra as permissões do site e defina "Microfone" como "Permitir", depois tente
            novamente.
          </p>
        )}
        {error?.code === "not_found" && (
          <p>Nenhum microfone foi detectado neste dispositivo. Conecte um microfone e tente novamente.</p>
        )}
        {error?.code === "busy" && (
          <p>O microfone parece estar em uso por outro aplicativo ou aba. Feche-o e tente novamente.</p>
        )}
        {error?.code === "unsupported" && (
          <p>Este navegador não suporta gravação de áudio pelo microfone. Use um navegador atualizado (Chrome, Firefox, Edge).</p>
        )}
        {error?.code === "unknown" && <p>{error.message || "Ocorreu um erro inesperado ao tentar acessar o microfone."}</p>}
        <p className="text-muted mb-0">Você ainda pode enviar um arquivo de áudio gravado previamente.</p>
      </Modal.Body>
      <Modal.Footer>
        <Button variant="outline-secondary" onClick={onDismiss}>
          Enviar arquivo de áudio
        </Button>
        <Button variant="danger" onClick={onRetry}>
          Tentar novamente
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
