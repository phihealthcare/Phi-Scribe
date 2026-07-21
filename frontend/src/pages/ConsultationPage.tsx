import { useEffect, useState } from "react";
import { Toast, ToastContainer } from "react-bootstrap";
import AudioCapturePanel from "../components/audio/AudioCapturePanel";
import MicPermissionModal from "../components/audio/MicPermissionModal";
import ConfirmModal from "../components/common/ConfirmModal";
import SessionHeader from "../components/header/SessionHeader";
import ConsultationLayout from "../components/layout/ConsultationLayout";
import SoapSummaryPanel from "../components/soap/SoapSummaryPanel";
import StatusBanner, { hasStatusBanner } from "../components/status/StatusBanner";
import TranscriptPanel from "../components/transcript/TranscriptPanel";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import { useConsultationSession } from "../hooks/useConsultationSession";
import { useRealtimeTranscription } from "../hooks/useRealtimeTranscription";
import { MicError, blobToUploadFile } from "../lib/audioRecorder";
import { formatSoapPlainText } from "../lib/soapText";

// Live capture (AudioWorkletNode + WebSocket) instead of the batch
// upload-then-transcribe flow. Requires the backend's own
// REALTIME_TRANSCRIPTION_ENABLED=true too — see app/routes/realtime.py.
const REALTIME_ENABLED = import.meta.env.VITE_REALTIME_TRANSCRIPTION_ENABLED === "true";

export default function ConsultationPage() {
  const {
    session,
    soapSections,
    soapRevision,
    entities,
    soapEdited,
    status,
    error,
    errorPhase,
    lastFileId,
    updateSoapSections,
    updateSegmentSpeaker,
    searchQuery,
    setSearchQuery,
    filteredSegments,
    uploadAndTranscribe,
    retryTranscribe,
    applyRealtimeResult,
    dismissError,
    resetSession,
  } = useConsultationSession();

  const recorder = useAudioRecorder();
  const realtime = useRealtimeTranscription();

  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [showRefreshConfirm, setShowRefreshConfirm] = useState(false);
  const [showFinalizeConfirm, setShowFinalizeConfirm] = useState(false);
  const [recoverDismissed, setRecoverDismissed] = useState(false);

  // The realtime session's SOAP arrives asynchronously (server sends
  // "soap_ready" once, after {"type":"stop"}) — apply it into the same
  // session state a batch /transcribe response would populate as soon as
  // it shows up, however long after handleStopRecording() already returned.
  useEffect(() => {
    if (realtime.soapResponse) {
      applyRealtimeResult(realtime.soapResponse);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [realtime.soapResponse]);

  useEffect(() => {
    if (realtime.connectionError) {
      setToastMessage(realtime.connectionError);
    }
  }, [realtime.connectionError]);

  const showRecoverModal = recorder.recoverableBackup !== null && !recoverDismissed;

  const isRecorderBusy =
    recorder.recorderStatus === "requesting" ||
    recorder.recorderStatus === "recording" ||
    recorder.recorderStatus === "paused";

  const refreshDisabled =
    !lastFileId || status === "uploading" || status === "transcribing" || isRecorderBusy;

  const finalizeDisabled = !soapSections || status === "uploading" || status === "transcribing";

  useEffect(() => {
    const active =
      recorder.recorderStatus === "recording" ||
      recorder.recorderStatus === "paused" ||
      status === "uploading" ||
      status === "transcribing";
    if (!active) return;

    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [recorder.recorderStatus, status]);

  async function handleStartRecording() {
    if (REALTIME_ENABLED) {
      try {
        await realtime.start();
      } catch (err) {
        setToastMessage(
          err instanceof Error ? err.message : "Não foi possível iniciar a transcrição em tempo real.",
        );
        return;
      }
    }
    void recorder.startRecording();
  }

  async function handleStopRecording() {
    // The MediaRecorder keeps recording either way (archival copy + fallback
    // if the WS session never delivers "soap_ready") — only what happens
    // with its blob differs: in realtime mode, SOAP comes from the WS
    // session itself (applyRealtimeResult, via the effect above), so the
    // batch upload+transcribe call is skipped entirely.
    if (REALTIME_ENABLED && realtime.isActive) {
      realtime.stop();
      await recorder.stopRecording();
      return;
    }

    const blobs = await recorder.stopRecording();
    if (!blobs || blobs.length === 0) return;

    try {
      const files = blobs.map((blob) => blobToUploadFile(blob, blob.type || "audio/webm"));
      await uploadAndTranscribe(files.length === 1 ? files[0] : files);
    } catch (err) {
      const message =
        err instanceof MicError || err instanceof Error
          ? err.message
          : "Formato de gravação não suportado.";
      setToastMessage(message);
    }
  }

  function handleRefreshRequest() {
    if (soapEdited) {
      setShowRefreshConfirm(true);
      return;
    }
    void retryTranscribe();
  }

  async function handleFinalizeConfirm() {
    if (!soapSections) return;

    const plainText = formatSoapPlainText(soapSections);
    try {
      await navigator.clipboard.writeText(plainText);
      setToastMessage("Resumo copiado para a área de transferência.");
    } catch {
      setToastMessage("Não foi possível copiar o resumo. Verifique as permissões do navegador.");
    }

    await recorder.discardBackup();
    resetSession();
    setShowFinalizeConfirm(false);
  }

  async function handleRecoverBackup() {
    const files = await recorder.recoverBackup();
    setRecoverDismissed(true);
    if (files && files.length > 0) {
      await uploadAndTranscribe(files.length === 1 ? files[0] : files);
    } else {
      setToastMessage("Não foi possível recuperar a gravação.");
    }
  }

  async function handleDiscardBackup() {
    await recorder.discardBackup();
    setRecoverDismissed(true);
  }

  async function handleContinueRecording() {
    setRecoverDismissed(true);
    try {
      await recorder.continueRecording();
    } catch (err) {
      const message =
        err instanceof MicError || err instanceof Error
          ? err.message
          : "Não foi possível continuar a gravação.";
      setToastMessage(message);
    }
  }

  return (
    <>
      <ConsultationLayout
        header={
          <SessionHeader
            session={session}
            isRecording={recorder.recorderStatus === "recording"}
            isPaused={recorder.recorderStatus === "paused"}
            elapsedSeconds={recorder.elapsedSeconds}
          />
        }
        banner={
          hasStatusBanner(status) && (
            <StatusBanner
              status={status}
              error={error}
              errorPhase={errorPhase}
              onRetryTranscribe={retryTranscribe}
              onDismiss={dismissError}
            />
          )
        }
        left={
          <AudioCapturePanel
            status={status}
            recorderStatus={recorder.recorderStatus}
            devices={recorder.devices}
            selectedDeviceId={recorder.selectedDeviceId}
            inputLevel={recorder.inputLevel}
            elapsedSeconds={recorder.elapsedSeconds}
            lowAudioWarning={recorder.lowAudioWarning}
            micBlocked={recorder.micBlocked}
            onFileSelected={uploadAndTranscribe}
            onStartRecording={() => void handleStartRecording()}
            onPauseRecording={recorder.pauseRecording}
            onResumeRecording={recorder.resumeRecording}
            onStopRecording={() => void handleStopRecording()}
            onDeviceChange={recorder.setSelectedDeviceId}
          />
        }
        center={
          <SoapSummaryPanel
            sections={soapSections}
            entities={entities}
            revision={soapRevision}
            onSectionsChange={updateSoapSections}
            onRefresh={handleRefreshRequest}
            refreshDisabled={refreshDisabled}
            onFinalize={() => setShowFinalizeConfirm(true)}
            finalizeDisabled={finalizeDisabled}
          />
        }
        right={
          <TranscriptPanel
            segments={REALTIME_ENABLED && realtime.isActive ? realtime.segments : filteredSegments}
            live={REALTIME_ENABLED && realtime.isActive}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            onRenameSpeaker={updateSegmentSpeaker}
          />
        }
      />

      <MicPermissionModal
        error={recorder.micError}
        onRetry={() => void recorder.startRecording()}
        onDismiss={recorder.dismissMicError}
      />

      <ConfirmModal
        show={showRefreshConfirm}
        title="Reprocessar resumo"
        body="Reprocessar substituirá o SOAP pelas alterações vindas do servidor. Suas edições manuais serão perdidas. Deseja continuar?"
        confirmLabel="Reprocessar mesmo assim"
        cancelLabel="Cancelar"
        onConfirm={() => {
          setShowRefreshConfirm(false);
          void retryTranscribe();
        }}
        onCancel={() => setShowRefreshConfirm(false)}
      />

      <ConfirmModal
        show={showFinalizeConfirm}
        title="Finalizar consulta"
        body="O resumo SOAP será copiado para a área de transferência e a sessão será encerrada. Deseja continuar?"
        confirmLabel="Finalizar"
        cancelLabel="Cancelar"
        confirmVariant="success"
        onConfirm={() => void handleFinalizeConfirm()}
        onCancel={() => setShowFinalizeConfirm(false)}
      />

      <ConfirmModal
        show={showRecoverModal}
        title="Gravação não enviada encontrada"
        body="Encontramos áudio de uma gravação anterior que não foi enviado. Deseja recuperar e processar agora, continuar gravando de onde parou, ou descartar?"
        confirmLabel="Recuperar"
        cancelLabel="Descartar"
        confirmVariant="primary"
        extraLabel="Continuar gravando"
        onConfirm={() => void handleRecoverBackup()}
        onCancel={() => void handleDiscardBackup()}
        onExtra={() => void handleContinueRecording()}
      />

      <ToastContainer position="bottom-end" className="p-3">
        <Toast
          bg="dark"
          show={toastMessage !== null}
          onClose={() => setToastMessage(null)}
          delay={3500}
          autohide
        >
          <Toast.Body className="text-white">{toastMessage}</Toast.Body>
        </Toast>
      </ToastContainer>
    </>
  );
}
