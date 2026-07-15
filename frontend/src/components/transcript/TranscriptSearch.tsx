import { Form, InputGroup } from "react-bootstrap";

interface TranscriptSearchProps {
  value: string;
  onChange: (value: string) => void;
}

export default function TranscriptSearch({ value, onChange }: TranscriptSearchProps) {
  return (
    <InputGroup className="mb-3">
      <InputGroup.Text aria-hidden="true">🔍</InputGroup.Text>
      <Form.Control
        type="search"
        aria-label="Buscar na transcrição"
        placeholder="Buscar na transcrição…"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </InputGroup>
  );
}
