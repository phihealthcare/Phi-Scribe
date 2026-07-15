import { Button, Card } from "react-bootstrap";
import type { SoapSections } from "../../api/types";
import EntityChips from "./EntityChips";
import SoapCombinedEditor from "./SoapCombinedEditor";

interface SoapSummaryPanelProps {
  sections: SoapSections | null;
  entities: string[];
  revision: number;
  onSectionsChange: (sections: SoapSections) => void;
  onRefresh: () => void;
  refreshDisabled: boolean;
  onFinalize: () => void;
  finalizeDisabled: boolean;
}

export default function SoapSummaryPanel({
  sections,
  entities,
  revision,
  onSectionsChange,
  onRefresh,
  refreshDisabled,
  onFinalize,
  finalizeDisabled,
}: SoapSummaryPanelProps) {
  return (
    <Card className="scribe-card h-100">
      <Card.Body className="d-flex flex-column">
        <Card.Title className="scribe-card-title">Resumo (SOAP)</Card.Title>

        <div className="flex-fill overflow-auto pe-1">
          {sections ? (
            <SoapCombinedEditor key={revision} sections={sections} onChange={onSectionsChange} />
          ) : (
            <p className="text-muted">Nenhum resumo disponível ainda.</p>
          )}

          <EntityChips entities={entities} />
        </div>

        <Button variant="success" className="scribe-primary-btn mt-2" onClick={onRefresh} disabled={refreshDisabled}>
          ✦ Atualizar resumo
        </Button>
        <Button
          variant="outline-secondary"
          className="mt-2"
          onClick={onFinalize}
          disabled={finalizeDisabled}
        >
          Finalizar consulta
        </Button>
      </Card.Body>
    </Card>
  );
}
