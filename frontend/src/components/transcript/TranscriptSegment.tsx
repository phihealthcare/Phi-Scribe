import { useState } from "react";
import type { TranscriptSegment as TranscriptSegmentData } from "../../api/types";
import SpeakerLabelEditor from "./SpeakerLabelEditor";

interface TranscriptSegmentProps {
  segment: TranscriptSegmentData;
  onRenameSpeaker: (label: string, scope: "single" | "all") => void;
}

function formatTimestamp(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function speakerClass(speakerLabel?: string): string {
  const normalized = (speakerLabel ?? "").toUpperCase();
  if (normalized.includes("MÉDIC") || normalized.includes("MEDIC")) return "scribe-speaker-medico";
  if (normalized.includes("PACIENTE")) return "scribe-speaker-paciente";
  return "scribe-speaker-outro";
}

export default function TranscriptSegment({ segment, onRenameSpeaker }: TranscriptSegmentProps) {
  const [isEditing, setIsEditing] = useState(false);

  return (
    <div className={`scribe-segment ${speakerClass(segment.speaker_label)} d-flex gap-2 mb-3`}>
      <span className="scribe-segment-bar" aria-hidden="true" />
      <div className="flex-fill">
        {isEditing ? (
          <SpeakerLabelEditor
            label={segment.speaker_label ?? ""}
            onSave={(label, scope) => {
              onRenameSpeaker(label, scope);
              setIsEditing(false);
            }}
            onCancel={() => setIsEditing(false)}
          />
        ) : (
          <div className="d-flex gap-2 align-items-baseline">
            <button
              type="button"
              className="scribe-segment-speaker-btn scribe-segment-speaker"
              onClick={() => setIsEditing(true)}
              title="Renomear locutor"
            >
              {segment.speaker_label ?? "Falante"} <span aria-hidden="true">✎</span>
            </button>
            <span className="text-muted small">{formatTimestamp(segment.start_ms)}</span>
          </div>
        )}
        <div className="scribe-segment-text">{segment.text}</div>
      </div>
    </div>
  );
}
