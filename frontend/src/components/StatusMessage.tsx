import { ApiError } from "../api/types";

interface StatusMessageProps {
  error: ApiError;
  onRetry: () => void;
}

function RetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <button type="button" className="status-message__retry" onClick={onRetry}>
      Try again
    </button>
  );
}

// Plain-language translations of the backend's structured error codes
// (docs/week5_api_report.md's status-code table) -- the UI never shows a
// raw "error": "out_of_service_area" code to the end user. Retry is only
// offered where retrying the *same* request could plausibly succeed
// (a transient server/network issue) -- out_of_service_area,
// no_routable_network, and validation_error are all properties of the
// selected points themselves, so retrying identically would just fail
// again; the fix there is picking different points, already stated in
// the message, not a retry button that would mislead.
export function StatusMessage({ error, onRetry }: StatusMessageProps) {
  if (error.status === -1) {
    // Deployment misconfiguration (client.ts's API_BASE_URL_MISCONFIGURED),
    // not a transient failure -- no retry button, since retrying an
    // identical request can't fix a build-time missing env var.
    return (
      <div className="status-message status-message--error" role="alert">
        <h2>AccessPath is not configured</h2>
        <p>{error.message}</p>
      </div>
    );
  }

  if (error.status === 0) {
    return (
      <div className="status-message status-message--error" role="alert">
        <h2>AccessPath server unavailable</h2>
        <p>
          The route-comparison service could not be reached. Check your connection, or try again in a moment. Your
          selected points are still on the map.
        </p>
        <RetryButton onRetry={onRetry} />
      </div>
    );
  }

  const code = error.body?.error;

  if (code === "out_of_service_area") {
    return (
      <div className="status-message status-message--error" role="alert">
        <h2>Outside the supported area</h2>
        <p>
          AccessPath currently only covers Seattle. One of your selected points is outside that area &mdash; click a
          point inside the city to try again.
        </p>
      </div>
    );
  }

  if (code === "no_routable_network") {
    return (
      <div className="status-message status-message--error" role="alert">
        <h2>No nearby routable path</h2>
        <p>
          There's no mapped sidewalk or path within {Math.round(Number(error.body?.max_snap_distance_m ?? 75))} m of
          one of your selected points (it may be in a park, body of water, or unmapped area). Try clicking closer to
          a street.
        </p>
      </div>
    );
  }

  if (code === "validation_error") {
    return (
      <div className="status-message status-message--error" role="alert">
        <h2>Invalid request</h2>
        <p>The selected coordinates could not be processed. Try selecting new points on the map.</p>
      </div>
    );
  }

  return (
    <div className="status-message status-message--error" role="alert">
      <h2>Something went wrong</h2>
      <p>{error.message || "An unexpected error occurred."}</p>
      <RetryButton onRetry={onRetry} />
    </div>
  );
}
