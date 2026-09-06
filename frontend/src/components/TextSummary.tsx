import { RouteCompareOk } from "../api/types";
import { formatDistance } from "../lib/format";
import { ROUTE_STYLES } from "../lib/routeStyle";

interface TextSummaryProps {
  result: RouteCompareOk;
}

// A11y requirement: a textual summary of the map results for anyone who
// cannot interpret the map itself -- this does not assume the reader has
// seen the three colored/patterned lines, and states the same trade-offs
// in prose. Route cards below repeat this in more structured, filterable
// form; this is the single paragraph a screen-reader user hits first.
export function TextSummary({ result }: TextSummaryProps) {
  const modes = Object.values(result.routes);
  const allSameDistance = modes.every((r) => r.distance_m === modes[0].distance_m);

  return (
    <div className="text-summary" aria-live="polite">
      <h2 className="visually-hidden">Text summary of route comparison</h2>
      <p>
        Three routes were compared between your selected origin and destination.{" "}
        {allSameDistance
          ? "All three routes follow the same path for this trip."
          : `Distances range from ${formatDistance(Math.min(...modes.map((r) => r.distance_m)))} to ${formatDistance(
              Math.max(...modes.map((r) => r.distance_m)),
            )}.`}{" "}
        The {ROUTE_STYLES.shortest.label.toLowerCase()} route is the shortest by distance only, with no regard for
        accessibility evidence. The {ROUTE_STYLES.accessible.label.toLowerCase()} route favors segments with better
        documented accessibility. The {ROUTE_STYLES.confidence_aware.label.toLowerCase()} route additionally favors
        segments with well-documented evidence over segments with no evidence at all, even if that evidence
        describes a known imperfection.
      </p>
      {result.comparison_notes.length > 0 && (
        <ul>
          {result.comparison_notes.map((note, index) => (
            <li key={index}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
