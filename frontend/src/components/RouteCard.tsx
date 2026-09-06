import { RouteMode, RouteResult } from "../api/types";
import { accessibilityBand, confidenceBand, formatDistance, formatDuration, formatScore } from "../lib/format";
import { ROUTE_STYLES } from "../lib/routeStyle";
import "./RouteCard.css";

interface RouteCardProps {
  mode: RouteMode;
  result: RouteResult;
  isSelected: boolean;
  onSelect: () => void;
  onFocusSegment: (segmentId: number) => void;
  duplicateOfLabel: string | null;
}

function countLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

export function RouteCard({ mode, result, isSelected, onSelect, onFocusSegment, duplicateOfLabel }: RouteCardProps) {
  const style = ROUTE_STYLES[mode];
  const hazardCount = result.hazards.length;
  const unknownCount = result.unknown_segment_ids.length;
  const lowConfidenceCount = result.low_confidence_segment_ids.length;
  const disputedCount = result.disputed_segment_ids.length;

  return (
    <li className="route-card-item">
      <button
        type="button"
        className={`route-card${isSelected ? " route-card--selected" : ""}`}
        aria-pressed={isSelected}
        onClick={onSelect}
      >
        <div className="route-card__heading">
          <svg width="36" height="12" viewBox="0 0 36 12" aria-hidden="true" focusable="false">
            <line
              x1="2" y1="6" x2="34" y2="6"
              stroke={style.color}
              strokeWidth={style.width > 4 ? 4 : 3}
              strokeDasharray={style.dashArray ? style.dashArray.join(",") : undefined}
              strokeLinecap={style.lineCap}
            />
          </svg>
          <h3 className="route-card__title">
            {style.label} <span className="route-card__pattern">({style.patternName} line)</span>
          </h3>
        </div>

        {duplicateOfLabel && (
          <p className="route-card__note">Identical to the {duplicateOfLabel} route for this trip.</p>
        )}

        <dl className="route-card__stats">
          <div>
            <dt>Distance</dt>
            <dd>{formatDistance(result.distance_m)}</dd>
          </div>
          <div>
            <dt>Estimated time</dt>
            <dd>{formatDuration(result.estimated_travel_time_s)}</dd>
          </div>
          <div>
            <dt>Accessibility</dt>
            <dd>
              {formatScore(result.accessibility_score)} &ndash; {accessibilityBand(result.accessibility_score)}
            </dd>
          </div>
          <div>
            <dt>Confidence / evidence</dt>
            <dd>
              {formatScore(result.confidence_score)} &ndash; {confidenceBand(result.confidence_score)}
            </dd>
          </div>
        </dl>

        <p className="route-card__coverage">
          {result.coverage.labeled_segments} of {result.coverage.total_segments} segments have accessibility
          evidence; {result.coverage.unknown_segments} have none.
        </p>
      </button>

      <div className="route-card__details">
        <h4>Known hazards</h4>
        {hazardCount === 0 ? (
          <p className="route-card__empty">No known hazards documented on this route.</p>
        ) : (
          <ul className="route-card__segment-list">
            {result.hazards.map((hazard) => (
              <li key={hazard.segment_id}>
                <button type="button" onClick={() => onFocusSegment(hazard.segment_id)}>
                  <span aria-hidden="true">▲</span> {hazard.hazard_type} (segment {hazard.segment_id})
                </button>
              </li>
            ))}
          </ul>
        )}

        <details>
          <summary>
            {countLabel(unknownCount, "segment")} with missing evidence,{" "}
            {countLabel(lowConfidenceCount, "segment")} with low confidence,{" "}
            {countLabel(disputedCount, "segment")} with conflicting evidence
          </summary>
          {unknownCount > 0 && (
            <>
              <h5>Missing evidence</h5>
              <ul className="route-card__segment-list">
                {result.unknown_segment_ids.slice(0, 10).map((id) => (
                  <li key={id}>
                    <button type="button" onClick={() => onFocusSegment(id)}>
                      Segment {id}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          {disputedCount > 0 && (
            <>
              <h5>Conflicting evidence</h5>
              <ul className="route-card__segment-list">
                {result.disputed_segment_ids.slice(0, 10).map((id) => (
                  <li key={id}>
                    <button type="button" onClick={() => onFocusSegment(id)}>
                      Segment {id}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </details>

        <p className="route-card__explanation">{result.explanation}</p>
      </div>
    </li>
  );
}
