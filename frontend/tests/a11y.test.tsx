import { act, render } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";
import { RouteCard } from "../src/components/RouteCard";
import { RouteResult } from "../src/api/types";

vi.mock("maplibre-gl", async () => {
  const { MockMap, MockMarker } = await import("./maplibreMock");
  return {
    default: { Map: MockMap, Marker: MockMarker, NavigationControl: vi.fn(), AttributionControl: vi.fn() },
  };
});
vi.mock("../src/api/client", () => ({
  compareRoutes: vi.fn(),
  fetchSegments: vi.fn(),
  fetchLabels: vi.fn(),
  fetchSegmentGeometry: vi.fn(),
  fetchCoverageSummary: vi.fn(),
  fetchDeploymentInfo: vi.fn().mockResolvedValue({ mode: "full", message: null, coverage_boundary: null }),
}));

const result: RouteResult = {
  mode: "shortest",
  geometry: { type: "LineString", coordinates: [[-122.33, 47.6], [-122.32, 47.61]] },
  distance_m: 420,
  estimated_travel_time_s: 350,
  accessibility_score: 0.53,
  min_accessibility_score: 0,
  confidence_score: 0.14,
  min_confidence_score: 0,
  coverage: { total_segments: 12, labeled_segments: 5, unknown_segments: 7 },
  hazards: [{ segment_id: 111, hazard_type: "SurfaceProblem" }],
  unknown_segment_ids: [222],
  low_confidence_segment_ids: [],
  disputed_segment_ids: [],
  explanation: "shortest route explanation",
};

describe("accessibility", () => {
  it("RouteCard has no axe violations", async () => {
    const { container } = render(
      <ul>
        <RouteCard
          mode="shortest"
          result={result}
          isSelected={false}
          onSelect={() => {}}
          onFocusSegment={() => {}}
          duplicateOfLabel={null}
        />
      </ul>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it("App's initial state has no axe violations", async () => {
    const { default: App } = await import("../src/App");
    const { container } = render(<App />);
    // Flush App's on-mount GET /deployment-info effect before axe inspects
    // the DOM, for the same reason App.test.tsx does this -- otherwise the
    // effect resolves after this test has already finished, outside any
    // act() scope.
    await act(async () => {});
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
