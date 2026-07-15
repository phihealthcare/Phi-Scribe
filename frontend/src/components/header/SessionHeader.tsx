import { Badge } from "react-bootstrap";
import type { ConsultationSession } from "../../api/types";
import { formatElapsed } from "../../lib/audioRecorder";

interface SessionHeaderProps {
  session: ConsultationSession;
  isRecording: boolean;
  isPaused: boolean;
  elapsedSeconds: number;
}

function formatSessionStart(iso: string): string {
  const date = new Date(iso);
  const datePart = date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  const timePart = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return `${datePart} · ${timePart}`;
}

export default function SessionHeader({ session, isRecording, isPaused, elapsedSeconds }: SessionHeaderProps) {
  return (
    <header className="scribe-header d-flex flex-wrap align-items-center justify-content-between gap-3 p-3">
      <div className="d-flex align-items-center gap-2">
        <div className="scribe-logo-badge" aria-hidden="true">
          PS
        </div>
        <div>
          <div className="fw-semibold">Transcrição</div>
          <div className="text-muted small">Sessão da consulta</div>
        </div>
      </div>

      <div className="d-flex flex-wrap gap-4">
        <div>
          <div className="scribe-meta-label">Consulta</div>
          <div>#{session.consultationId}</div>
        </div>
        <div>
          <div className="scribe-meta-label">Paciente</div>
          <div>
            {session.patientName} · {session.patientAge}a
          </div>
        </div>
        <div>
          <div className="scribe-meta-label">Profissional</div>
          <div>{session.professionalName}</div>
        </div>
        <div>
          <div className="scribe-meta-label">Início</div>
          <div>{formatSessionStart(session.startedAt)}</div>
        </div>
      </div>

      {isRecording || isPaused ? (
        <Badge bg="danger" className="scribe-status-badge scribe-recording-badge">
          {isPaused ? `⏸ Pausado ${formatElapsed(elapsedSeconds)}` : `● Gravando ${formatElapsed(elapsedSeconds)}`}
        </Badge>
      ) : (
        <Badge bg="light" text="dark" className="scribe-status-badge">
          Sessão carregada
        </Badge>
      )}
    </header>
  );
}
