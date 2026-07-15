import type { ChangeEvent } from "react";
import { useEffect, useRef } from "react";
import { Alert, Button, Card, Form, Spinner } from "react-bootstrap";
import type { ConsultationStatus } from "../../api/types";
import { formatElapsed, type RecorderStatus } from "../../lib/audioRecorder";
import { audioDebugLog } from "../../lib/audioDebug";

interface AudioCapturePanelProps {
  status: ConsultationStatus;
  recorderStatus: RecorderStatus;
  devices: MediaDeviceInfo[];
  selectedDeviceId: string | null;
  inputLevel: number;
  elapsedSeconds: number;
  lowAudioWarning: boolean;
  micBlocked: boolean;
  onFileSelected: (file: File) => void;
  onStartRecording: () => void;
  onPauseRecording: () => void;
  onResumeRecording: () => void;
  onStopRecording: () => void;
  onDeviceChange: (deviceId: string) => void;
}

const VU_BAR_COUNT = 14;
const ACCEPTED_EXTENSIONS = ".mp3,.wav,.mp4,.webm";
// Fixed per-bar multipliers so bars react to the same inputLevel with some
// natural-looking variance instead of moving in lockstep.
const VU_BAR_FACTORS = [0.5, 0.85, 0.65, 1, 0.55, 0.9, 0.7, 1, 0.6, 0.95, 0.5, 0.8, 0.65, 0.9];

export default function AudioCapturePanel({
  status,
  recorderStatus,
  devices,
  selectedDeviceId,
  inputLevel,
  elapsedSeconds,
  lowAudioWarning,
  micBlocked,
  onFileSelected,
  onStartRecording,
  onPauseRecording,
  onResumeRecording,
  onStopRecording,
  onDeviceChange,
}: AudioCapturePanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const prevLowWarningRef = useRef(false);

  const isUploadBusy = status === "uploading" || status === "transcribing";
  const isRecordingActive = recorderStatus === "recording" || recorderStatus === "paused";
  const isRequesting = recorderStatus === "requesting";
  const uploadDisabled = isUploadBusy || recorderStatus !== "idle";
  const showLowAudioAlert = recorderStatus === "recording" && lowAudioWarning;

  useEffect(() => {
    if (lowAudioWarning === prevLowWarningRef.current) return;
    prevLowWarningRef.current = lowAudioWarning;
    audioDebugLog("AudioCapturePanel RE-03 props", {
      recorderStatus,
      lowAudioWarning,
      showLowAudioAlert,
      inputLevel: Number(inputLevel.toFixed(4)),
      reasonHidden:
        lowAudioWarning && !showLowAudioAlert
          ? recorderStatus === "paused"
            ? "alert hidden while paused"
            : "recorderStatus is not recording"
          : undefined,
    });
  }, [recorderStatus, lowAudioWarning, showLowAudioAlert, inputLevel]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) {
      onFileSelected(file);
    }
  }

  const uploadLabel =
    status === "uploading" ? "Enviando…" : status === "transcribing" ? "Processando…" : "⭱ Enviar arquivo de áudio";

  return (
    <Card className="scribe-card h-100">
      <Card.Body>
        <Card.Title className="scribe-card-title">Captura de áudio</Card.Title>

        <div className="d-flex gap-2 mb-3">
          <Button
            variant="danger"
            className="w-100"
            disabled={isRequesting}
            onClick={isRecordingActive ? onStopRecording : onStartRecording}
          >
            {isRequesting ? (
              <>
                <Spinner animation="border" size="sm" className="me-2" />
                Solicitando…
              </>
            ) : isRecordingActive ? (
              "■ Parar"
            ) : (
              "● Gravar"
            )}
          </Button>
          <Button
            variant="outline-secondary"
            className="w-100"
            disabled={!isRecordingActive}
            onClick={recorderStatus === "paused" ? onResumeRecording : onPauseRecording}
          >
            {recorderStatus === "paused" ? "▶ Retomar" : "❚❚ Pausar"}
          </Button>
        </div>

        <div className="mb-3">
          <div className="scribe-meta-label mb-1">Nível de entrada</div>
          <div className="scribe-vu-meter" aria-hidden="true">
            {VU_BAR_FACTORS.slice(0, VU_BAR_COUNT).map((factor, index) => {
              const height = recorderStatus === "recording" ? Math.max(12, inputLevel * factor * 100) : undefined;
              return (
                <span
                  key={index}
                  className={`scribe-vu-bar${recorderStatus === "recording" ? " scribe-vu-bar-active" : ""}`}
                  style={height !== undefined ? { height: `${height}%` } : undefined}
                />
              );
            })}
          </div>
          <div className="text-muted small">
            {isRecordingActive ? formatElapsed(elapsedSeconds) : "—"}
            {recorderStatus === "paused" && " · pausado"}
          </div>
          {showLowAudioAlert && (
            <Alert variant="warning" className="py-1 px-2 small mt-2 mb-0">
              Nível de áudio muito baixo. Aproxime-se do microfone ou verifique se está mutado.
            </Alert>
          )}
        </div>

        <Form.Group className="mb-3" controlId="audio-microphone-select">
          <Form.Label className="scribe-meta-label">Microfone</Form.Label>
          <Form.Select
            disabled={recorderStatus !== "idle" || micBlocked}
            value={selectedDeviceId ?? ""}
            onChange={(event) => onDeviceChange(event.target.value)}
          >
            {devices.length === 0 && <option value="">Microfone padrão</option>}
            {devices.map((device, index) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label || (devices.length === 1 ? "Microfone padrão" : `Microfone ${index + 1}`)}
              </option>
            ))}
          </Form.Select>
          {micBlocked && (
            <div className="text-muted small mt-1">
              Microfone bloqueado pelo navegador. Libere o acesso e tente novamente.
            </div>
          )}
        </Form.Group>

        <Form.Group className="mb-4" controlId="audio-language-select">
          <Form.Label className="scribe-meta-label">Idioma</Form.Label>
          <Form.Select disabled aria-disabled="true">
            <option>Português (Brasil)</option>
          </Form.Select>
        </Form.Group>

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          className="d-none"
          onChange={handleFileChange}
        />
        <Button
          variant="outline-secondary"
          className="w-100"
          disabled={uploadDisabled}
          onClick={() => fileInputRef.current?.click()}
        >
          {isUploadBusy && <Spinner animation="border" size="sm" className="me-2" />}
          {uploadLabel}
        </Button>
      </Card.Body>
    </Card>
  );
}
