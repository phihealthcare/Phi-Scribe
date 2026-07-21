import { useEffect, useRef, useState } from "react";
import { Button, Card } from "react-bootstrap";
import type { TranscriptSegment as TranscriptSegmentData } from "../../api/types";
import TranscriptSearch from "./TranscriptSearch";
import TranscriptSegmentItem from "./TranscriptSegment";

interface TranscriptPanelProps {
  segments: TranscriptSegmentData[];
  /**
   * true while a live realtime session (useRealtimeTranscription) is
   * feeding `segments` — switches rendering from the paginated "load more"
   * mode (built for a static, complete array) to append-at-the-end with
   * auto-scroll, since new segments arrive continuously and existing ones
   * can be patched in place (a segment renders unlabeled, then gets its
   * speaker_label corrected once diarization catches up — see
   * useRealtimeTranscription.ts's applySegmentEvent). Defaults to false so
   * every existing (non-realtime) call site is unaffected.
   */
  live?: boolean;
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

export default function TranscriptPanel({
  segments,
  live = false,
  searchQuery,
  onSearchChange,
  onRenameSpeaker,
}: TranscriptPanelProps) {
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const liveScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [searchQuery]);

  // Live mode only: keep the newest segment in view as they arrive. Batch
  // mode's paginated list has no equivalent — "Carregar mais" is explicit,
  // user-initiated pagination, not something that should auto-scroll.
  useEffect(() => {
    if (!live) return;
    const el = liveScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [live, segments]);

  if (live) {
    const query = searchQuery.trim().toLowerCase();
    const liveSegments = query ? segments.filter((segment) => segment.text.toLowerCase().includes(query)) : segments;
    return (
      <Card className="scribe-card h-100">
        <Card.Body className="d-flex flex-column">
          <TranscriptSearch value={searchQuery} onChange={onSearchChange} />

          <div ref={liveScrollRef} className="flex-fill overflow-auto scribe-transcript-scroll pe-1">
            {liveSegments.length === 0 ? (
              <p className="text-muted">Aguardando fala...</p>
            ) : (
              // Keyed by start_ms (not index): segments can be patched in
              // place (partial -> final text, or a later speaker_update) via
              // the same start_ms rather than only ever being appended, so
              // an index-based key would misattribute React's reconciliation
              // across re-orders that never actually happen here anyway.
              liveSegments.map((segment) => (
                <TranscriptSegmentItem
                  key={segment.start_ms}
                  segment={segment}
                  onRenameSpeaker={(label, scope) => onRenameSpeaker(segment.start_ms, label, scope)}
                />
              ))
            )}
          </div>
        </Card.Body>
      </Card>
    );
  }

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
