import { useState } from "react";
import { Button, Form } from "react-bootstrap";

interface SpeakerLabelEditorProps {
  label: string;
  onSave: (label: string, scope: "single" | "all") => void;
  onCancel: () => void;
}

const QUICK_LABELS = ["MÉDICO", "PACIENTE"];

export default function SpeakerLabelEditor({ label, onSave, onCancel }: SpeakerLabelEditorProps) {
  const [value, setValue] = useState(label);
  const [applyToAll, setApplyToAll] = useState(false);

  function handleSave() {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSave(trimmed, applyToAll ? "all" : "single");
  }

  return (
    <div className="scribe-speaker-editor mb-2">
      <div className="d-flex gap-1 mb-1">
        {QUICK_LABELS.map((quick) => (
          <Button key={quick} size="sm" variant="outline-secondary" onClick={() => setValue(quick)}>
            {quick}
          </Button>
        ))}
      </div>
      <Form.Control
        size="sm"
        className="mb-1"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        aria-label="Rótulo do locutor"
        autoFocus
      />
      <Form.Check
        type="checkbox"
        id="speaker-editor-apply-all"
        label="Aplicar a todos os trechos deste locutor"
        checked={applyToAll}
        onChange={(event) => setApplyToAll(event.target.checked)}
        className="small mb-2"
      />
      <div className="d-flex gap-2">
        <Button size="sm" variant="success" onClick={handleSave}>
          Salvar
        </Button>
        <Button size="sm" variant="outline-secondary" onClick={onCancel}>
          Cancelar
        </Button>
      </div>
    </div>
  );
}
