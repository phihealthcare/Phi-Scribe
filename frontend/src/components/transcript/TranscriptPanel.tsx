import { useEffect, useState } from "react";
import { Button, Card } from "react-bootstrap";
import type { TranscriptSegment as TranscriptSegmentData } from "../../api/types";
import TranscriptSearch from "./TranscriptSearch";
import TranscriptSegmentItem from "./TranscriptSegment";

interface TranscriptPanelProps {
  segments: TranscriptSegmentData[];
  searchQuery: string;
  onSearchChange: (value: string) => void;
  onRenameSpeaker: (startMs: number, label: string, scope: "single" | "all") => void;
}

// RNF-02: consultations can run 30-60+ min, producing hundreds of segments.
// Paginating (instead of rendering everything at once) keeps the DOM small
// without the risk of misconfiguring a fixed-height virtualizer against
// these variable-height segment cards. Search still runs over the full,
// unpaginated list upstream (useConsultationSession.filteredSegments) —
// this only limits how much of *that* result renders at once.
const PAGE_SIZE = 50;

export default function TranscriptPanel({ segments, searchQuery, onSearchChange, onRenameSpeaker }: TranscriptPanelProps) {
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [searchQuery]);

  const visibleSegments = segments.slice(0, visibleCount);
  const remaining = segments.length - visibleSegments.length;

  return (
    <Card className="scribe-card h-100">
      <Card.Body className="d-flex flex-column">
        <TranscriptSearch value={searchQuery} onChange={onSearchChange} />

        <div className="flex-fill overflow-auto scribe-transcript-scroll pe-1">
          {visibleSegments.length === 0 ? (
            <p className="text-muted">Nenhum segmento encontrado.</p>
          ) : (
            <>
              {visibleSegments.map((segment, index) => (
                <TranscriptSegmentItem
                  key={`${segment.start_ms}-${index}`}
                  segment={segment}
                  onRenameSpeaker={(label, scope) => onRenameSpeaker(segment.start_ms, label, scope)}
                />
              ))}
              {remaining > 0 && (
                <Button
                  variant="outline-secondary"
                  size="sm"
                  className="w-100 mb-2"
                  onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
                >
                  Carregar mais ({Math.min(PAGE_SIZE, remaining)} de {remaining} restantes)
                </Button>
              )}
            </>
          )}
        </div>
      </Card.Body>
    </Card>
  );
}
