import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RouteCard } from "../src/components/RouteCard";
import { RouteResult } from "../src/api/types";

function makeResult(overrides: Partial<RouteResult> = {}): RouteResult {
  return {
    mode: "shortest",
    geometry: { type: "LineString", coordinates: [[-122.33, 47.6], [-122.32, 47.61]] },
    distance_m: 420,
    estimated_travel_time_s: 350,
    accessibility_score: 0.53,
    min_accessibility_score: 0.0,
    confidence_score: 0.14,
    min_confidence_score: 0.0,
    coverage: { total_segments: 12, labeled_segments: 5, unknown_segments: 7 },
    hazards: [{ segment_id: 111, hazard_type: "SurfaceProblem" }],
    unknown_segment_ids: [222, 223],
    low_confidence_segment_ids: [224],
    disputed_segment_ids: [],
    explanation: "shortest route: 420m across 12 segments.",
    ...overrides,
  };
}

describe("RouteCard", () => {
  it("renders distance, time, and scores", () => {
    render(
      <ul>
        <RouteCard
          mode="shortest"
          result={makeResult()}
          isSelected={false}
          onSelect={() => {}}
          onFocusSegment={() => {}}
          duplicateOfLabel={null}
        />
      </ul>,
    );
    expect(screen.getByText("420 m")).toBeInTheDocument();
    expect(screen.getByText(/0\.53/)).toBeInTheDocument();
    expect(screen.getByText(/0\.14/)).toBeInTheDocument();
  });

  it("shows an explicit empty state when there are no hazards", () => {
    render(
      <ul>
        <RouteCard
          mode="shortest"
          result={makeResult({ hazards: [] })}
          isSelected={false}
          onSelect={() => {}}
          onFocusSegment={() => {}}
          duplicateOfLabel={null}
        />
      </ul>,
    );
    expect(screen.getByText(/No known hazards documented/)).toBeInTheDocument();
  });

  it("calls onFocusSegment when a hazard is clicked", () => {
    const onFocusSegment = vi.fn();
    render(
      <ul>
        <RouteCard
          mode="shortest"
          result={makeResult()}
          isSelected={false}
          onSelect={() => {}}
          onFocusSegment={onFocusSegment}
          duplicateOfLabel={null}
        />
      </ul>,
    );
    fireEvent.click(screen.getByText(/SurfaceProblem/));
    expect(onFocusSegment).toHaveBeenCalledWith(111);
  });

  it("reflects selection state via aria-pressed", () => {
    const { rerender } = render(
      <ul>
        <RouteCard
          mode="shortest"
          result={makeResult()}
          isSelected={false}
          onSelect={() => {}}
          onFocusSegment={() => {}}
          duplicateOfLabel={null}
        />
      </ul>,
    );
    expect(screen.getByRole("button", { pressed: false })).toBeInTheDocument();

    rerender(
      <ul>
        <RouteCard
          mode="shortest"
          result={makeResult()}
          isSelected={true}
          onSelect={() => {}}
          onFocusSegment={() => {}}
          duplicateOfLabel={null}
        />
      </ul>,
    );
    expect(screen.getByRole("button", { pressed: true })).toBeInTheDocument();
  });

  it("calls onSelect when the card is activated", () => {
    const onSelect = vi.fn();
    render(
      <ul>
        <RouteCard
          mode="accessible"
          result={makeResult({ mode: "accessible" })}
          isSelected={false}
          onSelect={onSelect}
          onFocusSegment={() => {}}
          duplicateOfLabel={null}
        />
      </ul>,
    );
    fireEvent.click(screen.getByRole("button", { pressed: false }));
    expect(onSelect).toHaveBeenCalled();
  });

  it("shows a note when identical to another route", () => {
    render(
      <ul>
        <RouteCard
          mode="confidence_aware"
          result={makeResult({ mode: "confidence_aware" })}
          isSelected={false}
          onSelect={() => {}}
          onFocusSegment={() => {}}
          duplicateOfLabel="Accessibility-optimized"
        />
      </ul>,
    );
    expect(screen.getByText(/Identical to the Accessibility-optimized route/)).toBeInTheDocument();
  });

  it("names the line pattern in text, not just color", () => {
    render(
      <ul>
        <RouteCard
          mode="accessible"
          result={makeResult({ mode: "accessible" })}
          isSelected={false}
          onSelect={() => {}}
          onFocusSegment={() => {}}
          duplicateOfLabel={null}
        />
      </ul>,
    );
    expect(screen.getByText(/dashed line/)).toBeInTheDocument();
  });
});
