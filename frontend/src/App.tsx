import { useRef, useState } from "react";
import { ApiError, compareRoutes, fetchLabels, fetchSegmentGeometry, fetchSegments } from "./api/client";
import { Coordinate, GeoJSONFeatureCollection, RouteCompareNoConnection, RouteCompareOk, RouteMode } from "./api/types";
import { CoverageControl, CoverageVisibility } from "./components/CoverageControl";
import { DisclaimerBar } from "./components/DisclaimerBar";
import { MapView, MapViewHandle } from "./components/MapView";
import { RouteCard } from "./components/RouteCard";
import { SnapNotice } from "./components/SnapNotice";
import { StatusMessage } from "./components/StatusMessage";
import { TextSummary } from "./components/TextSummary";
import { annotateCoverageFeatures } from "./lib/coverage";
import { ROUTE_STYLES } from "./lib/routeStyle";
import { ROUTE_MODES } from "./api/types";
import "./App.css";

type Status = "idle" | "loading" | "success" | "no_connected_route" | "error";

const MAX_BBOX_LAT_SPAN_DEG = 0.03;
const MAX_BBOX_LON_SPAN_DEG = 0.045;

function findDuplicateLabel(routes: RouteCompareOk["routes"], mode: RouteMode): string | null {
  const thisCoords = JSON.stringify(routes[mode].geometry.coordinates);
  for (const other of ROUTE_MODES) {
    if (other === mode) continue;
    // Only report the duplicate once, against the mode earlier in ROUTE_MODES order.
    if (ROUTE_MODES.indexOf(other) < ROUTE_MODES.indexOf(mode) && JSON.stringify(routes[other].geometry.coordinates) === thisCoords) {
      return ROUTE_STYLES[other].label;
    }
  }
  return null;
}

export default function App() {
  const [origin, setOrigin] = useState<Coordinate | null>(null);
  const [destination, setDestination] = useState<Coordinate | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<RouteCompareOk | null>(null);
  const [noConnection, setNoConnection] = useState<RouteCompareNoConnection | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [selectedMode, setSelectedMode] = useState<RouteMode | null>(null);

  const [coverageSegments, setCoverageSegments] = useState<GeoJSONFeatureCollection | null>(null);
  const [coverageLabels, setCoverageLabels] = useState<GeoJSONFeatureCollection | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [coverageDisabledReason, setCoverageDisabledReason] = useState<string | null>(null);
  const [coverageVisibility, setCoverageVisibility] = useState<CoverageVisibility>({
    labeled: false,
    unknown: false,
    lowConfidence: false,
    disputed: false,
    labels: false,
  });

  const mapRef = useRef<MapViewHandle | null>(null);

  function resetResults() {
    setStatus("idle");
    setResult(null);
    setNoConnection(null);
    setError(null);
    setSelectedMode(null);
  }

  function handleMapClick(coordinate: Coordinate) {
    if (!origin) {
      setOrigin(coordinate);
      resetResults();
    } else if (!destination) {
      setDestination(coordinate);
      resetResults();
    } else {
      setOrigin(coordinate);
      setDestination(null);
      resetResults();
    }
  }

  function handleClearSelection() {
    setOrigin(null);
    setDestination(null);
    resetResults();
  }

  async function handleCompare() {
    if (!origin || !destination) return;
    setStatus("loading");
    setError(null);
    try {
      const response = await compareRoutes(origin.lat, origin.lon, destination.lat, destination.lon);
      if (response.status === "ok") {
        setResult(response);
        setNoConnection(null);
        setStatus("success");
        setSelectedMode(null);
      } else {
        setNoConnection(response);
        setResult(null);
        setStatus("no_connected_route");
      }
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, null, "Unknown error"));
      setStatus("error");
    }
  }

  async function handleFocusSegment(segmentId: number) {
    try {
      const feature = await fetchSegmentGeometry(segmentId);
      mapRef.current?.focusOnFeature(feature);
    } catch {
      // Geometry not available for this segment -- fail quietly, the
      // segment id is still visible in the card for reference.
    }
  }

  async function handleLoadCoverageForView() {
    const bounds = mapRef.current?.getBounds();
    if (!bounds) return;
    const [minLon, minLat, maxLon, maxLat] = bounds;
    if (maxLat - minLat > MAX_BBOX_LAT_SPAN_DEG || maxLon - minLon > MAX_BBOX_LON_SPAN_DEG) {
      setCoverageDisabledReason("Zoom in further to load coverage data -- the current view is too large.");
      return;
    }
    setCoverageDisabledReason(null);
    setCoverageLoading(true);
    try {
      const [segments, labels] = await Promise.all([fetchSegments(bounds), fetchLabels(bounds)]);
      setCoverageSegments(annotateCoverageFeatures(segments));
      setCoverageLabels(labels);
    } catch {
      setCoverageDisabledReason("Could not load coverage data for this view.");
    } finally {
      setCoverageLoading(false);
    }
  }

  const canCompare = origin !== null && destination !== null && status !== "loading";

  return (
    <div className="app">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <header className="app__header">
        <h1 className="app__title">AccessPath</h1>
        <p className="visually-hidden">Confidence-aware accessible pedestrian routing for Seattle</p>
      </header>

      <div className="app__body" id="main-content">
        <div className="app__map">
          <MapView
            ref={mapRef}
            origin={origin}
            destination={destination}
            onMapClick={handleMapClick}
            routeResult={result}
            selectedMode={selectedMode}
            coverageSegments={coverageSegments}
            coverageLabels={coverageLabels}
            coverageVisible={coverageVisibility}
          />
        </div>

        <aside className="app__sidebar" aria-label="Route planner">
          <section aria-labelledby="selection-heading">
            <h2 id="selection-heading" className="visually-hidden">
              Point selection
            </h2>
            <p role="status">
              {!origin && "Click the map to place your origin."}
              {origin && !destination && "Origin placed. Click the map to place your destination."}
              {origin && destination && status === "idle" && "Both points placed. Ready to compare routes."}
            </p>
            <p className="app__coords">
              <strong>Origin:</strong> {origin ? `${origin.lat.toFixed(5)}, ${origin.lon.toFixed(5)}` : "not set"}
              <br />
              <strong>Destination:</strong>{" "}
              {destination ? `${destination.lat.toFixed(5)}, ${destination.lon.toFixed(5)}` : "not set"}
            </p>
            <div className="app__actions">
              <button type="button" onClick={handleCompare} disabled={!canCompare}>
                {status === "loading" ? "Comparing routes…" : "Compare routes"}
              </button>
              <button type="button" onClick={handleClearSelection} disabled={!origin}>
                Clear selection
              </button>
            </div>
          </section>

          {status === "loading" && (
            <p role="status" aria-live="polite" className="app__loading">
              Comparing shortest, accessibility-optimized, and confidence-aware routes. This can take a few seconds
              for longer trips.
            </p>
          )}

          {status === "error" && error && <StatusMessage error={error} onRetry={handleCompare} />}

          {status === "no_connected_route" && noConnection && (
            <div className="status-message status-message--warning" role="alert">
              <h2>No connected route found</h2>
              <p>
                Your origin and destination are in different, currently unconnected parts of the mapped pedestrian
                network (component {noConnection.origin_component_id} vs. component{" "}
                {noConnection.destination_component_id}). This is usually a gap in the underlying map data, not
                necessarily a real-world dead end.
              </p>
              <SnapNotice label="Origin" endpoint={noConnection.origin} />
              <SnapNotice label="Destination" endpoint={noConnection.destination} />
            </div>
          )}

          {status === "success" && result && (
            <section aria-labelledby="results-heading">
              <h2 id="results-heading">Route comparison</h2>
              <SnapNotice label="Origin" endpoint={result.origin} />
              <SnapNotice label="Destination" endpoint={result.destination} />
              <TextSummary result={result} />
              <ul className="route-card-list">
                {ROUTE_MODES.map((mode) => (
                  <RouteCard
                    key={mode}
                    mode={mode}
                    result={result.routes[mode]}
                    isSelected={selectedMode === mode}
                    onSelect={() => setSelectedMode(selectedMode === mode ? null : mode)}
                    onFocusSegment={handleFocusSegment}
                    duplicateOfLabel={findDuplicateLabel(result.routes, mode)}
                  />
                ))}
              </ul>
            </section>
          )}

          <CoverageControl
            visibility={coverageVisibility}
            onChange={setCoverageVisibility}
            onLoadForView={handleLoadCoverageForView}
            loading={coverageLoading}
            disabledReason={coverageDisabledReason}
          />
        </aside>
      </div>

      <DisclaimerBar />
    </div>
  );
}
