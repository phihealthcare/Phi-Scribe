import { Badge } from "react-bootstrap";

interface EntityChipsProps {
  entities: string[];
}

export default function EntityChips({ entities }: EntityChipsProps) {
  if (entities.length === 0) return null;

  return (
    <div className="mb-3">
      <div className="scribe-meta-label mb-2">Entidades extraídas</div>
      <div className="d-flex flex-wrap gap-2">
        {entities.map((entity) => (
          <Badge key={entity} bg="light" text="dark" className="scribe-entity-chip">
            {entity}
          </Badge>
        ))}
      </div>
    </div>
  );
}
