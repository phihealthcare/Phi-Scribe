import { useState } from "react";
import { Form } from "react-bootstrap";
import type { SoapSections } from "../../api/types";
import { formatSoapEditableText, parseSoapEditableText } from "../../lib/soapText";

interface SoapCombinedEditorProps {
  sections: SoapSections;
  onChange: (sections: SoapSections) => void;
}

/**
 * All four SOAP sections in one textarea, each under its own "Título:"
 * heading, so a clinician can select-all/copy the whole note in one action.
 * Local text state is seeded once from `sections` and re-parsed into the
 * structured shape on every change; SoapSummaryPanel remounts this (via
 * `key`) whenever a fresh SOAP arrives from the server so edits never fight
 * a reformatted value while typing.
 */
export default function SoapCombinedEditor({ sections, onChange }: SoapCombinedEditorProps) {
  const [text, setText] = useState(() => formatSoapEditableText(sections));

  function handleChange(value: string) {
    setText(value);
    onChange(parseSoapEditableText(value));
  }

  return (
    <Form.Group controlId="soap-combined" className="mb-3">
      <Form.Control
        as="textarea"
        rows={18}
        className="scribe-soap-combined"
        value={text}
        onChange={(event) => handleChange(event.target.value)}
      />
    </Form.Group>
  );
}
